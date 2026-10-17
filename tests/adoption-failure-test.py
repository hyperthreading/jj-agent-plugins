#!/usr/bin/env python3
"""Fault injection against real Git/jj repositories and the SessionStart hook."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/jj-agent/scripts"
REAL_JJ = shutil.which("jj")
WRAPPER = r'''
import os, pathlib, subprocess, sys, time
args = sys.argv[1:]
if args[:2] == ['git', 'init']:
    with open(os.environ['CALLS'], 'a') as f: f.write('init\n')
    mode = os.environ.get('FAULT', '')
    if mode == 'before':
        print('injected initialization failure'); sys.exit(23)
    if mode == 'partial':
        pathlib.Path(args[-1], '.jj').mkdir()
        print('injected partial metadata'); sys.exit(23)
    if mode in ('pause', 'after'):
        rc = subprocess.call([os.environ['REAL_JJ']] + args)
        if rc: sys.exit(rc)
        if mode == 'after':
            print('injected failure after jj initialization'); sys.exit(23)
        pathlib.Path(os.environ['READY']).write_text(str(os.getppid()))
        while not pathlib.Path(os.environ['RELEASE']).exists(): time.sleep(.01)
        sys.exit(0)
os.execv(os.environ['REAL_JJ'], [os.environ['REAL_JJ']] + args)
'''


class AdoptionFailures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jj-adoption-fault-")
        self.base = Path(self.temp.name).resolve()
        self.main, self.wt = self.base / "main", self.base / "worktree"
        self.env = dict(os.environ, JJ_SHIM_OFF="1", JJ_USER="Test", JJ_EMAIL="test@example.com")
        self.run_cmd(REAL_JJ, "git", "init", str(self.main))
        (self.main / "f").write_text("base\n")
        (self.main / "deleted").write_text("delete me\n")
        for directory in ("keep", "drop"):
            (self.main / directory).mkdir()
            (self.main / directory / "f").write_text(f"{directory}\n")
        (self.main / ".gitignore").write_text(".env\nnode_modules/\n")
        self.run_cmd(REAL_JJ, "-R", str(self.main), "commit", "-m", "base")
        self.run_cmd("git", "-C", str(self.main), "worktree", "add", "-b", "task", str(self.wt))
        (self.wt / "f").write_text("dirty\n")
        (self.wt / "f").chmod(0o751)
        (self.wt / "deleted").unlink()
        (self.wt / ".env").write_text("ignored\n")
        (self.wt / "local").write_text("untracked\n")
        (self.wt / "link").symlink_to("f")
        os.link(self.wt / "f", self.wt / "hardlink")
        (self.wt / "node_modules").mkdir()
        for i in range(100):
            (self.wt / "node_modules" / str(i)).write_text("ignored dependency\n")
        for p in [self.wt / "f", self.wt / ".env", self.wt / "local"]:
            os.utime(p, (1000000000, 1000000000))
        self.remember()
        self.processes = []
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        wrapper = bin_dir / "jj"
        wrapper.write_text(f"#!{sys.executable}\n" + WRAPPER)
        wrapper.chmod(0o755)
        self.env.update(PATH=f"{bin_dir}:{self.env['PATH']}", REAL_JJ=REAL_JJ,
                        CLAUDE_PLUGIN_DATA=str(self.base / "data"),
                        CALLS=str(self.base / "calls"), READY=str(self.base / "ready"),
                        RELEASE=str(self.base / "release"))

    def tearDown(self):
        for p in self.processes:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.communicate()
        self.temp.cleanup()

    def run_cmd(self, *args):
        return subprocess.run(args, env=self.env, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=True).stdout

    def files(self):
        result = {}
        for p in self.wt.rglob("*"):
            rel = p.relative_to(self.wt)
            if rel.parts[0] in (".git", ".jj") or p.is_dir():
                continue
            stat = p.lstat()
            result[str(rel)] = (os.readlink(p) if p.is_symlink() else p.read_bytes(),
                                stat.st_ino, stat.st_mode, stat.st_mtime_ns)
        return result

    def intact(self):
        self.assertEqual(self.files(), self.before)
        self.assertEqual(self.wt.stat().st_ino, self.root_inode)
        self.assertEqual((self.wt / ".git").read_bytes(), self.gitfile)
        self.assertTrue(self.admin.is_dir())
        self.run_cmd("git", "-C", str(self.wt), "status", "--porcelain")

    def remember(self):
        self.before = self.files()
        self.root_inode = self.wt.stat().st_ino
        self.gitfile = (self.wt / ".git").read_bytes()
        self.admin = Path(self.gitfile.decode().strip()[8:])

    def clean_worktree(self, path=None):
        self.wt = path or self.base / "clean"
        self.run_cmd("git", "-C", str(self.main), "worktree", "add", "-b", "clean", str(self.wt))
        self.remember()

    def start(self, fault=""):
        env = dict(self.env, FAULT=fault)
        p = subprocess.Popen([os.environ.get("HOOK_BASH", "/bin/bash"), str(SCRIPTS / "session-start.sh")],
                             env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        p.stdin.write(json.dumps({"session_id": "fault", "cwd": str(self.wt)}))
        p.stdin.close()
        p.stdin = None
        self.processes.append(p)
        return p

    def hook(self, fault=""):
        p = self.start(fault)
        out, err = p.communicate(timeout=15)
        self.assertEqual(p.returncode, 0, err)
        return out

    def ready(self):
        deadline = time.monotonic() + 10
        while not (self.base / "ready").exists():
            if time.monotonic() > deadline:
                self.fail("initializer did not reach the injected pause")
            time.sleep(.01)

    def test_failed_init_preserves_files_and_retries(self):
        self.assertIn("did not finish", self.hook("before"))
        self.assertFalse((self.wt / ".jj").exists())
        self.assertEqual(self.run_cmd("git", "-C", str(self.wt), "show", ":f"), "base\n")
        self.intact()
        self.assertIn("Initialized Git worktree", self.hook())
        self.intact()

    def test_staged_only_content_is_not_discarded(self):
        (self.wt / "f").write_text("staged-only content\n")
        self.run_cmd("git", "-C", str(self.wt), "add", "f")
        (self.wt / "f").write_text("different working content\n")
        self.before = self.files()
        self.assertIn("staged changes", self.hook())
        self.assertFalse((self.wt / ".jj").exists())
        self.assertFalse((self.base / "calls").exists())
        self.assertEqual(self.run_cmd("git", "-C", str(self.wt), "show", ":f"), "staged-only content\n")
        self.intact()

    def test_existing_jj_file_is_not_claimed_or_removed(self):
        (self.wt / ".jj").write_text("existing user file")
        out = self.hook()
        self.assertIn("not a directory", out)
        self.assertNotIn("vcs=jj", out)
        self.assertEqual((self.wt / ".jj").read_text(), "existing user file")
        self.assertFalse((self.base / "calls").exists())
        self.intact()

    def test_sparse_checkout_does_not_become_deletions(self):
        self.clean_worktree()
        self.run_cmd("git", "-C", str(self.wt), "sparse-checkout", "set", "--cone", "keep")
        self.remember()
        self.assertFalse((self.wt / "drop/f").exists())
        self.assertEqual(self.run_cmd("git", "-C", str(self.wt), "status", "--porcelain"), "")
        index = (self.admin / "index").read_bytes()
        self.assertIn("sparse checkout", self.hook())
        self.assertFalse((self.wt / ".jj").exists())
        self.assertFalse((self.base / "calls").exists())
        self.assertEqual((self.admin / "index").read_bytes(), index)
        self.intact()

    def test_manual_skip_worktree_does_not_become_deletion(self):
        self.clean_worktree()
        self.run_cmd("git", "-C", str(self.wt), "update-index", "--skip-worktree", "drop/f")
        (self.wt / "drop/f").unlink()
        self.remember()
        index = (self.admin / "index").read_bytes()
        self.assertIn("skip-worktree", self.hook())
        self.assertFalse((self.wt / ".jj").exists())
        self.assertFalse((self.base / "calls").exists())
        self.assertEqual((self.admin / "index").read_bytes(), index)
        self.intact()

    def test_orphan_head_has_specific_notice(self):
        self.clean_worktree()
        self.run_cmd("git", "-C", str(self.wt), "checkout", "--orphan", "orphan")
        self.assertIn("no valid HEAD commit", self.hook())
        self.assertFalse((self.wt / ".jj").exists())
        self.assertFalse((self.base / "calls").exists())
        self.intact()

    def test_copied_worktree_registration_is_rejected(self):
        original = self.wt
        index = (self.admin / "index").read_bytes()
        head = (self.admin / "HEAD").read_bytes()
        for symlink in (False, True):
            with self.subTest(gitfile_symlink=symlink):
                self.wt = self.base / f"copy-{symlink}"
                shutil.copytree(original, self.wt, symlinks=True)
                if symlink:
                    (self.wt / ".git").unlink()
                    (self.wt / ".git").symlink_to(original / ".git")
                self.remember()
                self.assertIn("registration points to another path", self.hook())
                self.assertFalse((self.wt / ".jj").exists())
                self.assertFalse((self.base / "calls").exists())
                self.assertEqual((self.admin / "index").read_bytes(), index)
                self.assertEqual((self.admin / "HEAD").read_bytes(), head)
                self.assertEqual(self.files(), self.before)
        self.assertFalse((original / ".jj").exists())

    def test_unrepaired_move_is_rejected_until_repaired(self):
        original = self.wt
        self.wt = self.base / "moved"
        original.rename(self.wt)
        index = (self.admin / "index").read_bytes()
        head = (self.admin / "HEAD").read_bytes()
        self.assertIn("registration points to another path", self.hook())
        self.assertFalse((self.wt / ".jj").exists())
        self.assertFalse((self.base / "calls").exists())
        self.assertEqual((self.admin / "index").read_bytes(), index)
        self.assertEqual((self.admin / "HEAD").read_bytes(), head)
        self.intact()
        self.run_cmd("git", "-C", str(self.main), "worktree", "repair", str(self.wt))
        self.assertIn("Initialized Git worktree", self.hook())
        self.intact()

    def test_pending_path_reused_as_regular_jj_repo(self):
        self.assertIn("did not finish", self.hook("before"))
        self.run_cmd("git", "-C", str(self.main), "worktree", "remove", "--force", str(self.wt))
        self.run_cmd(REAL_JJ, "git", "init", str(self.wt))
        out = self.hook()
        self.assertIn("vcs=jj-colocated", out)
        self.assertNotIn("could not initialize", out)
        self.assertEqual((self.base / "calls").read_text(), "init\n")

    def test_pending_path_reused_as_plain_child_directory(self):
        self.clean_worktree(self.main / "nested")
        self.assertIn("did not finish", self.hook("before"))
        self.run_cmd("git", "-C", str(self.main), "worktree", "remove", "--force", str(self.wt))
        self.wt.mkdir()
        out = self.hook()
        self.assertIn(f"vcs=jj-colocated at {self.main} (", out)
        self.assertNotIn("could not initialize", out)
        self.assertEqual((self.base / "calls").read_text(), "init\n")

    def test_pending_path_reused_by_another_worktree(self):
        self.assertIn("did not finish", self.hook("before"))
        self.run_cmd("git", "-C", str(self.main), "worktree", "move", str(self.wt), str(self.base / "old"))
        self.run_cmd("git", "-C", str(self.main), "worktree", "add", "-b", "replacement", str(self.wt))
        out = self.hook()
        self.assertIn("bookmark 'replacement'", out)
        self.assertNotIn("bookmark 'task'", out)
        self.assertEqual((self.base / "calls").read_text(), "init\ninit\n")

    def test_loadable_metadata_resumes_without_second_init(self):
        self.assertIn("did not finish", self.hook("after"))
        self.intact()
        self.assertIn("Initialized Git worktree", self.hook())
        self.assertEqual((self.base / "calls").read_text(), "init\n")
        self.assertNotIn("Initialized Git worktree", self.hook())
        self.intact()

    def test_partial_metadata_is_preserved_and_reported(self):
        self.assertIn("did not finish", self.hook("partial"))
        marker = self.wt / ".jj" / "keep"
        marker.write_text("must not discard incomplete metadata")
        self.assertIn("did not finish", self.hook())
        self.assertTrue(marker.exists())
        self.assertEqual((self.base / "calls").read_text(), "init\n")
        self.intact()

    def test_parallel_hooks_do_not_initialize_twice(self):
        first = self.start("pause")
        self.ready()
        self.assertIn("already running", self.hook())
        self.assertEqual((self.base / "calls").read_text(), "init\n")
        self.intact()
        (self.base / "release").touch()
        out, _ = first.communicate(timeout=10)
        self.assertIn("Initialized Git worktree", out)
        self.intact()

    def test_sigkill_releases_lock_and_resumes(self):
        first = self.start("pause")
        self.ready()
        os.killpg(first.pid, signal.SIGKILL)
        first.communicate(timeout=10)
        self.intact()
        self.assertIn("Initialized Git worktree", self.hook())
        self.assertEqual((self.base / "calls").read_text(), "init\n")
        self.intact()

    def test_killed_helper_keeps_child_lock(self):
        first = self.start("pause")
        self.ready()
        helper_pid = int((self.base / "ready").read_text())
        os.kill(helper_pid, signal.SIGKILL)
        self.assertIn("already running", self.hook())
        self.intact()
        (self.base / "release").touch()
        first.communicate(timeout=10)
        self.assertIn("Initialized Git worktree", self.hook())
        self.assertEqual((self.base / "calls").read_text(), "init\n")
        self.intact()


if __name__ == "__main__":
    unittest.main(verbosity=2)
