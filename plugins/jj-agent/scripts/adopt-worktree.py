#!/usr/bin/env python3
"""Initialize a touched Git worktree without moving any working-copy files.

The Git object store/refs stay shared; jj metadata and operation history are local
to this checkout. Only jj's public CLI writes repository metadata.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def adopt(worktree, data):
    wt = Path(worktree).resolve()
    gitfile = wt / ".git"
    line = gitfile.read_text().splitlines()[0]
    if not line.startswith("gitdir: "):
        return 1
    gd = (wt / line[8:]).resolve()
    # Only linked worktrees of a colocated jj repository qualify, not submodules.
    if gd.parent.name != "worktrees" or gd.parent.parent.name != ".git":
        return 1
    main = gd.parents[2]
    if not (main / ".jj").is_dir():
        return 1
    if os.path.lexists(wt / ".jj") and not (wt / ".jj").is_dir():
        print(f"jj-agent: left {wt} unchanged because .jj exists but is not a directory.")
        return 1
    state = Path(data) / "adoptions" / str(wt).lstrip("/")
    state.mkdir(parents=True, exist_ok=True)
    locks = Path(data) / "adoption-locks"
    locks.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(os.fsencode(gd)).hexdigest()
    env = dict(os.environ, JJ_SHIM_OFF="1")
    with (locks / key).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"jj-agent: jj initialization is already running in {wt}; retry after it finishes.")
            return 1

        def run(*args):
            # Keep the lock in the child too if the hook/this helper is killed.
            return subprocess.run(args, cwd=wt, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  pass_fds=(lock.fileno(),))

        pending = state / "pending"
        if (wt / ".jj").exists() and not pending.exists():
            return 0
        # Verify the registration using Git before any jj initialization.
        backlink = Path((gd / "gitdir").read_text().rstrip("\r\n"))
        if not backlink.is_absolute():
            backlink = gd / backlink
        # Resolve the parent only: a copied .git symlink must not qualify as the
        # original registered worktree's .git file.
        if backlink.parent.resolve() / backlink.name != gitfile:
            print(f"jj-agent: left Git worktree {wt} unchanged because its Git registration "
                  "points to another path. Inspect the checkout and repair its worktree "
                  "registration before automatic jj initialization.")
            return 1
        common = run("git", "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common.returncode or Path(common.stdout.strip()).resolve() != main / ".git":
            return 1
        identity = {"gitdir": str(gd), "directories": [
            [p.stat().st_dev, p.stat().st_ino] for p in (wt, gd)]}
        saved = json.loads(pending.read_text()) if pending.exists() else None
        if saved is not None and saved.get("identity") != identity:
            # The old worktree was removed and this path was reused. Its retry
            # record must not govern a different checkout or an existing jj repo.
            pending.unlink()
            saved = None
            if (wt / ".jj").exists():
                return 0
        sparse = run("git", "config", "--bool", "core.sparseCheckout")
        entries = run("git", "ls-files", "-t", "-z")
        if (sparse.returncode not in (0, 1) or sparse.stdout.strip() == "true"
                or entries.returncode or any(e.startswith("S ") for e in entries.stdout.split("\0"))):
            print(f"jj-agent: left Git worktree {wt} unchanged because sparse checkout or "
                  "skip-worktree entries are enabled, or could not be checked. Materialize "
                  "the full checkout before automatic jj initialization so omitted files "
                  "are not treated as deletions.")
            return 1
        if not (wt / ".jj").exists():
            head = run("git", "rev-parse", "--verify", "HEAD")
            if head.returncode:
                print(f"jj-agent: left Git worktree {wt} unchanged because it has no valid "
                      "HEAD commit. Create an initial commit before automatic jj initialization.")
                return 1
            staged = run("git", "diff", "--cached", "--quiet", "HEAD", "--")
            if staged.returncode:
                print(f"jj-agent: left Git worktree {wt} unchanged because its index has "
                      "staged changes or could not be checked. Preserve or commit the staged "
                      "work before automatic jj initialization; jj uses the working files, "
                      "not Git's staging area.")
                return 1
        if saved is None:
            branch = run("git", "symbolic-ref", "--quiet", "--short", "HEAD")
            saved = {"identity": identity,
                     "branch": branch.stdout.strip() if branch.returncode == 0 else ""}
            temporary = state / "pending.tmp"
            temporary.write_text(json.dumps(saved))
            temporary.replace(pending)

        if (wt / ".jj").exists():
            # Resume only metadata that jj can load. Never delete an interrupted
            # .jj: it may already contain useful snapshots or concurrent work.
            result = run("jj", "-R", str(wt), "op", "log", "--ignore-working-copy",
                         "--no-graph", "-n", "1", "-T", "id")
            if result.returncode == 0:
                result = run("jj", "-R", str(wt), "util", "snapshot")
        else:
            result = run("jj", "git", "init", "--colocate", str(wt))
        if result.returncode:
            (state / "last-error").write_text(result.stdout)
            print(f"jj-agent: automatic jj initialization did not finish in {wt}. "
                  f"Working files and Git registration were left in place. "
                  f"Inspect {state / 'last-error'} and the existing .jj before retrying; "
                  "the plugin will not delete it.")
            return 1
        pending.unlink()
        branch_note = f" (bookmark '{saved['branch']}' at @-)" if saved["branch"] else ""
        print(f"Initialized Git worktree at {wt} as a colocated jj repo{branch_note}. "
              "Git commits and branches are shared; jj operation history is local to this worktree.")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(adopt(*sys.argv[1:]))
    except (OSError, ValueError, IndexError) as error:
        print(f"jj-agent: could not initialize this Git worktree: {error}")
        sys.exit(1)
