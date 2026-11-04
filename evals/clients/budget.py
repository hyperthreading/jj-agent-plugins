"""Durable admission ledger. A reservation is charged until usage settles it."""
import json
import fcntl
import math
import os
from pathlib import Path
import threading
import time


class LimitReached(RuntimeError):
    pass


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".new")
    with temp.open("w") as file:
        json.dump(value, file, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    temp.replace(path)


class Budget:
    def __init__(self, path, plan, clock=time.time):
        self.path, self.plan, self.clock = Path(path), plan, clock
        self.lock = threading.RLock()
        if not plan.get("approved"):
            raise LimitReached("plan is not approved")
        for key in ("total_cost_usd", "total_seconds", "run_seconds", "run_cost_usd", "max_steps"):
            if type(plan.get(key)) not in (int, float) or not math.isfinite(plan[key]) or plan[key] <= 0:
                raise ValueError(f"invalid limit: {key}")
        self.file_lock = self.path.with_suffix(".lock").open("a")
        try:
            fcntl.flock(self.file_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file_lock.close()
            raise LimitReached("another campaign launcher owns the ledger") from None
        try:
            if self.path.exists():
                self.data = json.loads(self.path.read_text())
                if self.data["plan"] != plan:
                    raise LimitReached("campaign plan changed")
                if any(r["pending"] for r in self.data["runs"].values()):
                    self.data["stop"] = self.data["stop"] or "unsettled reservation from previous process"
            else:
                self.data = {"plan": plan, "started": clock(), "stop": None, "runs": {}}
            self.save()
        except Exception:
            self.file_lock.close()
            raise

    def close(self):
        self.file_lock.close()

    def save(self):
        write_json(self.path, self.data)

    def stop(self, reason):
        with self.lock:
            self.data["stop"] = self.data["stop"] or reason
            self.save()

    def total(self):
        with self.lock:
            return sum(r["charged"] + sum(r["pending"].values()) for r in self.data["runs"].values())

    def check(self, run=None):
        with self.lock:
            if self.data["stop"]:
                raise LimitReached(self.data["stop"])
            if self.clock() >= self.data["started"] + self.plan["total_seconds"]:
                raise LimitReached("campaign wall-time limit")
            if self.total() >= round(self.plan["total_cost_usd"] * 1_000_000):
                raise LimitReached("campaign cost limit")
            if run is not None:
                state = self.data["runs"][run]
                if self.clock() >= state["started"] + self.plan["run_seconds"]:
                    raise LimitReached("run wall-time limit")

    def start(self, run):
        with self.lock:
            self.check()
            if run in self.data["runs"]:
                raise LimitReached("run id already used; turns must share the existing run")
            self.data["runs"][run] = {"started": self.clock(), "steps": 0, "charged": 0,
                                      "pending": {}, "requests": []}
            self.save()

    def reserve(self, run, model, input_bound, output_bound):
        with self.lock:
            self.check(run)
            state = self.data["runs"][run]
            if state["steps"] >= self.plan["max_steps"]:
                raise LimitReached("run model-request limit")
            rate = self.plan["rates_per_million"][model]
            amount = math.ceil(input_bound * rate["input"] + output_bound * rate["output"])
            used = state["charged"] + sum(state["pending"].values())
            if used + amount > round(self.plan["run_cost_usd"] * 1_000_000):
                raise LimitReached("run reservation would exceed cost limit")
            if self.total() + amount > round(self.plan["total_cost_usd"] * 1_000_000):
                raise LimitReached("campaign reservation would exceed cost limit")
            state["steps"] += 1
            key = str(state["steps"])
            state["pending"][key] = amount
            state["requests"].append({"id": key, "model": model, "reserved": amount,
                                      "input_bound": input_bound, "output_bound": output_bound})
            self.save()
            return key

    def settle(self, run, key, usage):
        with self.lock:
            state = self.data["runs"][run]
            record = next(r for r in state["requests"] if r["id"] == key)
            if key not in state["pending"]:
                raise ValueError("request already settled")
            valid = usage is not None and all(type(usage.get(k)) is int and usage[k] >= 0
                                             for k in ("input", "output"))
            if not valid:
                self.stop("missing or invalid upstream usage; reservation retained")
                return
            rate = self.plan["rates_per_million"][record["model"]]
            actual = math.ceil(usage["input"] * rate["input"] + usage["output"] * rate["output"])
            record.update(usage=usage, charged=actual)
            if usage["input"] > record["input_bound"] or usage["output"] > record["output_bound"]:
                self.stop("upstream exceeded the admitted token bound")
                state["charged"] += max(actual, state["pending"].pop(key))
            else:
                state["charged"] += actual
                del state["pending"][key]
            self.save()
