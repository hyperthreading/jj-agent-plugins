#!/usr/bin/env python3
"""Real Git/jj regressions for shared GC ownership and refusal caching."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/jj-agent/scripts'
REAL_JJ, REAL_GIT = shutil.which('jj'), shutil.which('git')


class SharedRepository(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jj-gc-safety-')
        self.base = Path(self.temp.name).resolve()
        self.main, self.wt = self.base / 'main', self.base / 'wt'
        self.data = self.base / 'data'
        (self.base / 'gitconfig').write_text('')
        (self.base / 'jjconfig.toml').write_text('')
        self.env = dict(os.environ, JJ_SHIM_OFF='1', JJ_USER='Test',
                        JJ_EMAIL='test@example.test', GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL=str(self.base / 'gitconfig'),
                        JJ_CONFIG=str(self.base / 'jjconfig.toml'),
                        CLAUDE_PLUGIN_DATA=str(self.data))
        self.run_cmd(REAL_JJ, 'git', 'init', str(self.main))
        for name in ('f', 'deleted', 'ignored-tracked'):
            (self.main / name).write_text(name + '\n')
        self.jj(self.main, 'commit', '-m', 'base')
        (self.main / '.gitignore').write_text('.env\nignored-tracked\n')
        self.jj(self.main, 'commit', '-m', 'ignore already tracked file')
        self.git(self.main, 'worktree', 'add', '-b', 'task', str(self.wt))
        self.calls = self.base / 'calls'
        bindir = self.base / 'bin'
        bindir.mkdir()
        for name, real in (('git', REAL_GIT), ('jj', REAL_JJ)):
            wrapper = bindir / name
            wrapper.write_text(f'#!{sys.executable}\n'
                               'import os, sys\n'
                               f'with open({str(self.calls)!r}, "a") as f: f.write({name!r} + "\\n")\n'
                               f'os.execv({real!r}, [{real!r}] + sys.argv[1:])\n')
            wrapper.chmod(0o755)
        self.env['PATH'] = str(bindir) + os.pathsep + self.env['PATH']

    def tearDown(self):
        self.temp.cleanup()

    def run_cmd(self, *args, cwd=None):
        return subprocess.run(args, cwd=cwd or self.base, env=self.env,
                              text=True, capture_output=True, check=True,
                              timeout=30).stdout

    def jj(self, root, *args):
        return self.run_cmd(REAL_JJ, *args, cwd=root)

    def git(self, root, *args):
        return self.run_cmd(REAL_GIT, *args, cwd=root)

    def hook(self, root=None, session='test', event='session-start'):
        payload = {'session_id': session, 'cwd': str(root or self.wt),
                   'tool_name': 'Bash', 'tool_use_id': 'test-call',
                   'tool_input': {'command': 'true'}}
        p = subprocess.run(['/bin/bash', str(SCRIPTS / (event + '.sh'))],
                           input=json.dumps(payload), cwd=self.base, env=self.env,
                           text=True, capture_output=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def adopt(self, root=None):
        root = root or self.wt
        self.assertIn('Initialized Git worktree', self.hook(root))
        pointer = root / '.jj/repo'
        self.assertTrue(pointer.is_file())
        self.assertEqual((pointer.parent / pointer.read_text().strip()).resolve(),
                         self.main / '.jj/repo')

    def commit_id(self, root):
        return self.jj(root, 'log', '--ignore-working-copy', '--no-graph',
                       '-r', '@', '-T', 'commit_id').strip()

    def operation(self, root):
        return self.jj(root, 'op', 'log', '--ignore-working-copy', '--no-graph',
                       '-n', '1', '-T', 'id').strip()

    def snapshot(self, root, value):
        (root / 'f').write_text(value)
        self.jj(root, 'util', 'snapshot')
        return (root, self.operation(root), self.commit_id(root), value)

    def assert_snapshot(self, snapshot, history=True):
        root, operation, commit, value = snapshot
        self.git(self.main, 'cat-file', '-e', commit + '^{commit}')
        self.assertEqual(self.jj(root, 'file', 'show', '-r', commit, 'f'), value)
        if history:
            self.assertEqual(self.jj(root, '--at-operation', operation,
                                     'file', 'show', '-r', '@', 'f'), value)

    def test_default_gc_in_either_workspace_preserves_current_and_operation_history(self):
        previous = [self.snapshot(self.main, 'main old\n')]
        self.adopt()
        previous.append(self.snapshot(self.wt, 'worktree old\n'))
        current = [self.snapshot(self.main, 'main current\n'),
                   self.snapshot(self.wt, 'worktree current\n')]
        for root in (self.main, self.wt):
            with self.subTest(gc_from=root.name):
                self.jj(root, 'util', 'gc')
                self.git(self.main, 'gc', '--prune=now')
                for snapshot in previous + current:
                    self.assert_snapshot(snapshot)

    def test_explicit_expiration_in_either_workspace_preserves_live_workspaces(self):
        self.adopt()
        current = [self.snapshot(self.main, 'main current\n'),
                   self.snapshot(self.wt, 'worktree current\n')]
        for root in (self.main, self.wt):
            with self.subTest(gc_from=root.name):
                self.jj(root, 'util', 'gc', '--expire=now')
                self.git(self.main, 'gc', '--prune=now')
                for snapshot in current:
                    self.assert_snapshot(snapshot, history=False)

    def test_adoption_preserves_ignored_tracked_files_deletions_and_file_metadata(self):
        (self.wt / 'f').write_text('dirty\n')
        (self.wt / 'ignored-tracked').write_text('dirty ignored tracked\n')
        (self.wt / 'deleted').unlink()
        (self.wt / '.env').write_text('ignored\n')
        (self.wt / 'local').write_text('untracked\n')
        (self.wt / 'f').chmod(0o751)
        os.link(self.wt / 'f', self.wt / 'hardlink')
        (self.wt / 'symlink').symlink_to('f')

        def metadata():
            result = {}
            for path in self.wt.iterdir():
                if path.name == '.jj':
                    continue
                st = path.lstat()
                result[path.name] = (os.readlink(path) if path.is_symlink() else path.read_bytes(),
                                     st.st_ino, st.st_mode, st.st_mtime_ns)
            return result

        before, inode = metadata(), self.wt.stat().st_ino
        self.adopt()
        self.assertEqual(metadata(), before)
        self.assertEqual(self.wt.stat().st_ino, inode)
        self.assertFalse((self.wt / 'deleted').exists())
        self.assertEqual(self.jj(self.wt, 'file', 'show', '-r', '@', 'ignored-tracked'),
                         'dirty ignored tracked\n')
        self.assertIn('D deleted', self.jj(self.wt, 'diff', '--summary'))

    def names(self):
        return set(self.jj(self.main, 'workspace', 'list', '--ignore-working-copy',
                           '-T', 'name ++ "\\n"').splitlines())

    def test_session_cleanup_forgets_only_owned_missing_checkout(self):
        explicit = self.base / 'explicit'
        self.jj(self.main, 'workspace', 'add', '--name', 'explicit', str(explicit))
        self.adopt()
        self.hook(self.main)
        names = self.names()
        self.assertEqual(len(names), 3)
        self.git(self.main, 'worktree', 'remove', str(self.wt))
        self.hook(self.main)
        self.assertEqual(self.names(), {'default', 'explicit'})
        self.assertTrue(explicit.exists())

    def test_session_cleanup_retains_git_moved_checkout(self):
        self.adopt()
        before = self.names()
        moved = self.base / 'moved'
        self.git(self.main, 'worktree', 'move', str(self.wt), str(moved))
        self.hook(self.main)
        self.assertEqual(self.names(), before)
        self.jj(moved, 'status')

    def call_count(self):
        return len(self.calls.read_text().splitlines()) if self.calls.exists() else 0

    def assert_cached(self, reason):
        self.assertIn(reason, self.hook())
        count = self.call_count()
        for event in ('pre-tool', 'post-tool') * 4:
            self.assertNotIn('left Git worktree', self.hook(event=event))
        self.assertEqual(self.call_count(), count, 'cache hits spawned Git/jj')
        self.assertFalse((self.wt / '.jj').exists())

    def test_staged_refusal_is_cached_per_session_and_retries_after_index_change(self):
        (self.wt / 'f').write_text('staged\n')
        self.git(self.wt, 'add', 'f')
        self.assert_cached('staged changes')
        count = self.call_count()
        self.assertIn('staged changes', self.hook(session='new-session'))
        self.assertGreater(self.call_count(), count)
        self.git(self.wt, 'restore', '--staged', 'f')
        self.adopt()

    def test_sparse_refusal_retries_when_config_and_index_change(self):
        self.git(self.wt, 'config', 'core.sparseCheckout', 'true')
        self.assert_cached('sparse checkout')
        self.git(self.wt, 'config', 'core.sparseCheckout', 'false')
        self.adopt()

    def test_skip_worktree_refusal_retries_after_index_change(self):
        self.git(self.wt, 'update-index', '--skip-worktree', 'f')
        self.assert_cached('skip-worktree')
        self.git(self.wt, 'update-index', '--no-skip-worktree', 'f')
        self.adopt()

    def test_unborn_refusal_retries_when_referenced_branch_appears(self):
        head = self.git(self.wt, 'rev-parse', 'HEAD').strip()
        self.git(self.wt, 'symbolic-ref', 'HEAD', 'refs/heads/unborn')
        self.assert_cached('no valid HEAD')
        self.git(self.wt, 'update-ref', 'refs/heads/unborn', head)
        self.adopt()

    def test_refusal_retries_when_head_changes(self):
        head = self.git(self.wt, 'rev-parse', 'HEAD').strip()
        self.git(self.wt, 'symbolic-ref', 'HEAD', 'refs/heads/unborn')
        self.assert_cached('no valid HEAD')
        self.git(self.wt, 'update-ref', '--no-deref', 'HEAD', head)
        self.adopt()

    def test_registration_refusal_retries_after_repair(self):
        moved = self.base / 'manual-move'
        self.wt.rename(moved)
        self.wt = moved
        self.assert_cached('registration points to another path')
        self.git(self.main, 'worktree', 'repair', str(self.wt))
        self.adopt()


if __name__ == '__main__':
    unittest.main(verbosity=2)
