#!/usr/bin/env python3
"""Normalize only random IDs, the fixture root and OpenCode's documented backend sentence."""
from pathlib import Path
import subprocess
import sys


def normalize(text, root):
    def ids(rev):
        return subprocess.check_output(
            ["jj", "log", "--ignore-working-copy", "--no-graph", "-r", rev, "-T", 'change_id.short(8) ++ "\\n"'],
            cwd=root, text=True,
        ).splitlines()

    text = text.replace(str(Path(root).resolve()), "<ROOT>")
    text = text.replace(" OpenCode has no VCS backend for this directory.", "")
    replacements = [(ids("@")[0], "<WC>")]
    parents = ids("@-")
    if len(parents) == 1:
        replacements.append((parents[0], "<PARENT>"))
    else:
        for name in ("left", "right"):
            replacements.append((ids(name)[0], f"<{name.upper()}>"))
    replacements.extend((value, f"<CHILD{index + 1}>") for index, value in enumerate(ids("children(@)")))
    replacements.extend((value, "<LEFT-TIP>") for value in ids('description(substring:"left-tip")'))
    for value, replacement in replacements:
        text = text.replace(value, replacement)
    return text.rstrip() + "\n"


if __name__ == "__main__":
    print(normalize(sys.stdin.read(), sys.argv[1]), end="")
