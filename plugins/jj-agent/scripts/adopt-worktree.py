#!/usr/bin/env python3
"""Attach a touched Git worktree to its main jj repo, moving only new metadata."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def identity(path):
    info = path.stat()
    return [info.st_dev, info.st_ino]


def missing(path):
    # Inaccessible paths and dangling symlinks are not evidence of deletion.
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    return False


def signature(paths):
    result = []
    for path in paths:
        try:
            st = path.stat()
            result.append([str(path), st.st_dev, st.st_ino, st.st_size,
                           st.st_mtime_ns, st.st_ctime_ns])
        except FileNotFoundError:
            result.append([str(path), None])
    return result


def lock_path(data, gd):
    locks = Path(data) / 'adoption-locks'
    locks.mkdir(parents=True, exist_ok=True)
    return locks / hashlib.sha256(os.fsencode(gd)).hexdigest()


def registered_gitfile(gd):
    backlink = Path((gd / 'gitdir').read_text().rstrip('\r\n'))
    if not backlink.is_absolute():
        backlink = gd / backlink
    return backlink.parent.resolve() / backlink.name


def repo_dir(root):
    repo = root / '.jj/repo'
    if repo.is_file():
        repo = repo.parent / repo.read_text().strip()
    return repo.resolve()


def adopt(worktree, data, session='default'):
    wt = Path(worktree).resolve()
    gitfile = wt / '.git'
    line = gitfile.read_text().splitlines()[0]
    if not line.startswith('gitdir: '):
        return 1
    gd = (wt / line[8:]).resolve()
    if gd.parent.name != 'worktrees' or gd.parent.parent.name != '.git':
        return 1
    main = gd.parents[2]
    if not (main / '.jj').is_dir():
        return 1
    state = Path(data) / 'adoptions' / str(wt).lstrip('/')
    state.mkdir(parents=True, exist_ok=True)
    pending = state / 'pending'
    refusal = state / ('refused-' + hashlib.sha256(session.encode()).hexdigest())
    # A cache hit performs only stat/read operations: no Git/jj subprocesses and
    # no repeated notice. Index, refs, config or registration changes invalidate it.
    watched = [wt, wt.parent, gitfile, wt / '.jj', gd, gd / 'index', gd / 'HEAD', gd / 'gitdir',
               gd / 'commondir', gd / 'config.worktree', gd / 'info/sparse-checkout',
               main / '.git/config', main / '.git/packed-refs',
               main / '.git/info/sparse-checkout', main / '.jj', pending, Path(__file__)]
    for ref in (gd / 'HEAD', main / '.git/HEAD'):
        try:
            value = ref.read_text().strip()
            if value.startswith('ref: '):
                watched.append(main / '.git' / value[5:])
        except OSError:
            pass
    watched.extend([Path(os.environ.get('GIT_CONFIG_GLOBAL', '~/.gitconfig')).expanduser(),
                    Path(os.environ.get('XDG_CONFIG_HOME', '~/.config')).expanduser() / 'git/config'])
    current_signature = signature(watched)
    cached = {}
    if refusal.exists():
        cached = json.loads(refusal.read_text())
        if cached.get('signature') == current_signature:
            return 1

    def refuse(reason):
        atomic_json(refusal, {'reason': reason, 'signature': signature(watched)})
        # A stat-only index refresh requires a recheck, not another identical notice.
        if cached.get('reason') != reason:
            print(f'jj-agent: left Git worktree {wt} unchanged because {reason}')
        return 1

    env = dict(os.environ, JJ_SHIM_OFF='1')
    with lock_path(data, gd).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f'jj-agent: jj initialization is already running in {wt}; retry after it finishes.')
            return 1

        def run(*args, cwd=wt):
            return subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  pass_fds=(lock.fileno(),))

        def checked(*args, cwd=wt):
            result = run(*args, cwd=cwd)
            if result.returncode:
                raise RuntimeError(result.stdout)
            return result.stdout.strip()

        if os.path.lexists(wt / '.jj') and not (wt / '.jj').is_dir():
            return refuse('.jj exists but is not a directory.')
        if registered_gitfile(gd) != gitfile:
            return refuse('its Git registration points to another path. Inspect the checkout '
                          'and repair its worktree registration before automatic jj initialization.')
        common = run('git', 'rev-parse', '--path-format=absolute', '--git-common-dir')
        if common.returncode or Path(common.stdout.strip()).resolve() != main / '.git':
            return 1
        ident = {'gitdir': str(gd), 'directories': [identity(wt), identity(gd)]}
        saved = json.loads(pending.read_text()) if pending.exists() else None
        if saved is not None and saved.get('identity') != ident:
            # Preserve old recovery information, but do not apply it to a reused path.
            pending.rename(state / ('superseded-' + uuid.uuid4().hex))
            saved = None
        if (wt / '.jj').is_dir() and saved is None:
            return 0
        if saved is not None and not {'stage', 'name', 'phase'}.issubset(saved):
            return refuse('an older initialization record needs manual inspection. '
                          f'Preserve the existing metadata and review {pending} before retrying.')

        def preflight():
            sparse = run('git', 'config', '--bool', 'core.sparseCheckout')
            entries = run('git', 'ls-files', '-t', '-z')
            if (sparse.returncode not in (0, 1) or sparse.stdout.strip() == 'true'
                    or entries.returncode or any(e.startswith('S ') for e in entries.stdout.split('\0'))):
                return refuse('sparse checkout or skip-worktree entries are enabled, or could not '
                              'be checked. Materialize the full checkout before automatic jj initialization.')
            head = run('git', 'rev-parse', '--verify', 'HEAD')
            if head.returncode:
                return refuse('it has no valid HEAD commit. Create an initial commit before '
                              'automatic jj initialization.')
            staged = run('git', 'diff', '--cached', '--quiet', 'HEAD', '--')
            if staged.returncode:
                return refuse('its index has staged changes or could not be checked. Preserve '
                              "or commit the staged work first; jj uses the working files, not Git's staging area.")
            return 0

        if preflight():
            return 1
        if saved is None:
            try:
                stage = Path(tempfile.mkdtemp(prefix='.jj-agent-', dir=wt.parent))
            except PermissionError:
                return refuse('its parent directory does not permit creating temporary jj metadata. '
                              'Restore parent-directory write access before automatic jj initialization.')
            saved = {'identity': ident, 'worktree': str(wt), 'main': str(main),
                     'stage': str(stage), 'name': 'jj-agent-' + uuid.uuid4().hex,
                     'phase': 'prepare'}
            atomic_json(pending, saved)
        stage = Path(saved['stage'])
        registry = Path(data) / 'managed-workspaces' / hashlib.sha256(os.fsencode(repo_dir(main))).hexdigest() / (saved['name'] + '.json')
        try:
            if not (wt / '.jj').exists():
                if not (stage / '.jj').exists():
                    # root() has an empty tree: workspace creation writes no user
                    # files, and full sparsity needs no reset/materialization later.
                    checked('jj', '-R', str(main), 'workspace', 'add', '--ignore-working-copy',
                            '--no-colocate', '--sparse-patterns', 'full', '--name', saved['name'],
                            '-r', 'root()', str(stage))
                checked('jj', '-R', str(stage), 'op', 'log', '--ignore-working-copy',
                        '--no-graph', '-n', '1', '-T', 'id')
                if set(p.name for p in stage.iterdir()) != {'.jj'}:
                    raise RuntimeError('The metadata staging directory contains unexpected files; inspect it before retrying.')
                if preflight():
                    return 1
                (stage / '.jj/.gitignore').write_text('/*\n')
                saved['metadata_identity'] = identity(stage / '.jj')
                atomic_json(pending, saved)
                (stage / '.jj').rename(wt / '.jj')
            if identity(wt / '.jj') != saved.get('metadata_identity'):
                raise RuntimeError('Existing .jj does not match this initialization record; it was left untouched.')
            pointer = wt / '.jj/repo'
            if not pointer.is_file() or repo_dir(wt) != repo_dir(main):
                raise RuntimeError('Workspace does not point to the main jj repository; inspect the existing metadata.')
            # A newly colocated shared workspace imports the existing Git HEAD
            # and snapshots in place. Never run sparse reset in the user checkout.
            branch = run('git', 'symbolic-ref', '--quiet', '--short', 'HEAD')
            checked('jj', '-R', str(wt), 'util', 'snapshot')
            saved['phase'] = 'complete'
            atomic_json(registry, saved)
            pending.unlink()
            refusal.unlink(missing_ok=True)
            try:
                stage.rmdir()
            except OSError:
                pass
            branch_note = f" (bookmark '{branch.stdout.strip()}' at @-)" if branch.returncode == 0 else ''
            print(f"Initialized Git worktree at {wt} as shared jj workspace '{saved['name']}'{branch_note}. "
                  'Git commits and jj operation history are shared with the main repository.')
            return 0
        except (OSError, RuntimeError) as error:
            (state / 'last-error').write_text(str(error))
            print(f'jj-agent: automatic jj initialization did not finish in {wt}. '
                  f'Working files and Git registration were left in place. Inspect {state / "last-error"} '
                  f'and metadata in {stage} or {wt / ".jj"} before retrying; the plugin will not delete it.')
            return 1


def cleanup(root, data):
    """Forget only completed workspaces after Git removes their registration."""
    root = Path(root).resolve()
    records = Path(data) / 'managed-workspaces' / hashlib.sha256(os.fsencode(repo_dir(root))).hexdigest()
    if not records.is_dir():
        return 0
    for record in records.glob('*.json'):
        try:
            saved = json.loads(record.read_text())
            if saved['phase'] != 'complete':
                continue
            wt = Path(saved['worktree'])
            gd = Path(saved['identity']['gitdir'])
            with lock_path(data, gd).open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                # Missing paths may be unrepaired moves or unavailable volumes.
                # Git remove/prune deletes the admin directory; its presence is
                # enough to retain the workspace, even with a stale backlink.
                if not missing(wt) or not missing(gd):
                    continue
                result = subprocess.run(['jj', '-R', str(root), 'workspace', 'forget', '--ignore-working-copy', saved['name']],
                                        env=dict(os.environ, JJ_SHIM_OFF='1'), stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, pass_fds=(lock.fileno(),))
                if result.returncode == 0:
                    record.unlink()
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            # Preserve unreadable/invalid records and continue with other owned
            # workspaces. Cleanup must never add text to the hook's JSON output.
            continue
    return 0


if __name__ == '__main__':
    try:
        if sys.argv[1] == '--cleanup':
            sys.exit(cleanup(*sys.argv[2:]))
        sys.exit(adopt(*sys.argv[1:]))
    except (OSError, ValueError, IndexError) as error:
        print(f'jj-agent: could not initialize this Git worktree: {error}',
              file=sys.stderr if '--cleanup' in sys.argv[1:2] else sys.stdout)
        sys.exit(1)
