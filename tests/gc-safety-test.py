#!/usr/bin/env python3
"""Real Git/jj regressions for shared GC ownership and refusal caching."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


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

    def test_session_cleanup_retains_unrepaired_move_and_wip_identity(self):
        self.adopt()
        self.jj(self.wt, 'commit', '-m', 'completed step')
        self.snapshot(self.wt, 'work in progress\n')
        self.jj(self.wt, 'describe', '-m', 'WIP must survive a move')
        template = 'change_id ++ "\\n" ++ description'
        before = self.jj(self.wt, 'log', '--no-graph', '-r', '@', '-T', template)
        names = self.names()
        records = list(self.data.glob('managed-workspaces/*/*.json'))
        moved = self.base / 'unrepaired-move'
        self.wt.rename(moved)
        self.hook(self.main)
        self.assertEqual(self.names(), names)
        self.assertTrue(all(p.exists() for p in records))
        self.git(self.main, 'worktree', 'repair', str(moved))
        self.assertEqual(self.jj(moved, 'log', '--no-graph', '-r', '@', '-T', template), before)
        self.assertEqual((moved / 'f').read_text(), 'work in progress\n')
        self.git(self.main, 'worktree', 'remove', '--force', str(moved))
        self.hook(self.main)
        self.assertEqual(self.names(), {'default'})
        self.assertFalse(any(p.exists() for p in records))

    def test_cleanup_keeps_missing_checkout_until_git_registration_is_removed(self):
        self.adopt()
        names = self.names()
        admin = Path((self.wt / '.git').read_text().strip()[8:])
        shutil.rmtree(self.wt)
        self.assertTrue(admin.is_dir())
        self.hook(self.main)
        self.assertEqual(self.names(), names)
        self.git(self.main, 'worktree', 'prune', '--expire=now')
        self.assertFalse(admin.exists())
        self.hook(self.main)
        self.assertEqual(self.names(), {'default'})

    def test_malformed_cleanup_records_do_not_corrupt_json_or_stop_valid_cleanup(self):
        self.adopt()
        record = next(self.data.glob('managed-workspaces/*/*.json'))
        directory = record.parent
        saved = record.read_text()
        # Insert invalid records before the valid one, so abort-on-error would
        # leave the owned workspace behind. Both parse and schema errors matter.
        record.unlink()
        invalid = [directory / '000-invalid.json', directory / '001-invalid.json']
        invalid[0].write_text('{broken')
        invalid[1].write_text('{}')
        record.write_text(saved)
        self.git(self.main, 'worktree', 'remove', str(self.wt))
        result = json.loads(self.hook(self.main, session='cleanup-json'))
        self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'SessionStart')
        self.assertEqual(self.names(), {'default'})
        self.assertTrue(all(p.exists() for p in invalid))

    def test_missing_jj_leaves_cleanup_records_and_valid_hook_output(self):
        self.adopt()
        record = next(self.data.glob('managed-workspaces/*/*.json'))
        self.git(self.main, 'worktree', 'remove', str(self.wt))
        minimal = self.base / 'minimal-bin'
        minimal.mkdir()
        for name, target in (('python3', sys.executable),
                             ('mkdir', '/bin/mkdir'), ('find', '/usr/bin/find')):
            (minimal / name).symlink_to(target)
        old_path = self.env['PATH']
        try:
            self.env['PATH'] = str(minimal)
            result = json.loads(self.hook(self.main, session='no-jj'))
            self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'SessionStart')
            self.assertTrue(record.exists())
        finally:
            self.env['PATH'] = old_path
        self.hook(self.main)
        self.assertFalse(record.exists())

    def test_deeply_nested_record_does_not_stop_later_cleanup(self):
        self.adopt()
        record = next(self.data.glob('managed-workspaces/*/*.json'))
        invalid = record.parent / 'deeply-nested.json'
        invalid.write_text('[' * 2000 + ']' * 2000)
        self.git(self.main, 'worktree', 'remove', str(self.wt))
        spec = importlib.util.spec_from_file_location('adoption', SCRIPTS / 'adopt-worktree.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        # Force the bad record first regardless of the filesystem's directory order.
        with patch.object(Path, 'glob', return_value=iter([invalid, record])):
            self.assertEqual(helper.cleanup(self.main, self.data), 0)
        self.assertEqual(self.names(), {'default'})
        self.assertTrue(invalid.exists())
        self.assertFalse(record.exists())

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

    def test_index_stat_refresh_rechecks_without_repeating_same_refusal(self):
        (self.wt / 'f').write_text('staged\n')
        self.git(self.wt, 'add', 'f')
        self.assert_cached('staged changes')
        admin = Path((self.wt / '.git').read_text().strip()[8:])
        index = admin / 'index'
        before = index.stat()
        os.utime(index, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
        count = self.call_count()
        self.assertNotIn('left Git worktree', self.hook())
        self.assertGreater(self.call_count(), count)
        count = self.call_count()
        self.assertNotIn('left Git worktree', self.hook())
        self.assertEqual(self.call_count(), count)
        self.git(self.wt, 'config', 'core.sparseCheckout', 'true')
        self.assertIn('sparse checkout', self.hook())

    @unittest.skipIf(os.geteuid() == 0, 'root bypasses directory write permissions')
    def test_unwritable_parent_refusal_is_cached_until_permissions_change(self):
        parent = self.base / 'read-only-parent'
        parent.mkdir()
        moved = parent / 'wt'
        self.git(self.main, 'worktree', 'move', str(self.wt), str(moved))
        self.wt = moved
        parent.chmod(0o555)
        try:
            self.assert_cached('parent directory does not permit')
        finally:
            parent.chmod(0o755)
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
