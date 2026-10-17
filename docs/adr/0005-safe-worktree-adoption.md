# ADR 0005: 작업 파일을 이동하지 않는 worktree 자동 초기화

- Status: Accepted
- Date: 2026-10-17

## Context

Harness가 만든 Git worktree에는 `.jj`가 없다. 중첩 worktree에서 부모의 `.jj`까지 올라가면 부모 working copy에 snapshot을 남기는 버그가 생긴다. 외부 worktree에서는 plugin이 동작하지 않는다.

PR #5의 첫 구현은 worktree의 파일을 복사한 뒤 삭제하고 `jj workspace add --colocate`로 다시 만들었다. 리뷰에서 강제 종료 시 파일 유실, 선행 `git worktree prune`으로 인한 등록 손상, mtime 변경, 다른 세션의 worktree까지 전환하는 문제가 확인됐다. 자동 전환 기능은 유지하되 이 경로는 제거한다.

jj 0.46의 `workspace add`는 기존의 비어 있지 않은 경로를 거부한다. 같은 jj repo의 workspace로 편입하려고 작업 파일을 이동하거나 jj 내부 저장 형식을 수정하는 방법은 사용하지 않는다.

## Decision

1. `.git` 파일은 repo 탐색 경계다. `.jj`가 함께 있으면 해당 jj checkout을 사용한다. 줄바꿈 없는 상대 `gitdir:`도 처리하고, malformed 파일이나 submodule에서는 부모 jj repo로 넘어가지 않는다.
2. cwd 또는 tool file path로 직접 만난, 본체에 `.jj`가 있는 Git worktree만 `jj git init --colocate`로 초기화한다. 부모에서 worktree를 만들었더라도 첫 접근까지 기다린다. 전체 worktree 순회와 `WT_ADOPTED` ref 보고 예외는 없앤다.
3. 작업 파일과 Git 등록을 그대로 둔다. `cp`, 작업 파일의 `mv`/삭제, `git worktree prune`, jj 내부 metadata 편집은 하지 않는다. jj의 정상 초기화·snapshot만 사용한다.
4. **Git 저장소는 공유하고 jj 저장소는 분리한다.** 새 `.jj/repo`는 이 worktree의 op log와 working-copy change를 보관한다. 부모의 `workspace list`에는 추가되지 않는다. 완성한 변경은 bookmark를 통해 Git ref로 공유한다. 공통 jj op log가 필요하면 사용자가 새 경로에 `jj workspace add --colocate`를 사용한다.
5. 최초 초기화 경로만 Python 3의 POSIX `flock`을 쓴다. 잠금 이름은 실제 Git admin 경로로 정하며, 자식 jj에도 fd를 전달한다. hook/helper만 종료되고 jj가 계속 실행 중이어도 잠금은 유지된다. 잠금 파일은 unlink하지 않아 다른 프로세스가 다른 inode를 잠그는 경쟁을 피한다. 보통 jj hook 경로에는 Python 호출이 없다.
6. pending 기록과 오류 로그는 plugin data에 둔다. `.jj/jj-agent-wt` 같은 프로젝트 marker는 쓰지 않는다. 중단 뒤 `.jj`가 없다면 초기화를 재시도하고, jj가 읽을 수 있으면 snapshot으로 마친다. 읽을 수 없는 `.jj`는 삭제하지 않고 오류 경로를 안내한다. 재시도는 여전히 대상 Git worktree인 경우에만 하며, worktree와 Git admin 디렉터리의 경로·device·inode로 같은 대상인지 확인한다. 재사용된 일반 디렉터리나 repo는 오래된 기록에 막히지 않는다. 서로 다른 plugin-data 경로를 쓰는 세션은 같은 잠금을 공유하지 않으므로 설정을 일관되게 유지한다.
7. 초기화 안내는 완료한 뒤 한 번 전달한다. Muse의 첫 PreToolUse에서는 완료 안내를 baseline 옆에 보관하고 PostToolUse 결과로 전달한다. 실패하거나 큰 도구 결과 때문에 전달할 수 없으면 다음 호출을 보류해 안내한다(ADR 0002). 다음 세션은 일반 jj 안내만 받는다. HEAD/ref 변경 보고는 worktree 초기화 여부와 무관하게 유지한다.
8. Git admin의 `gitdir` backlink가 현재 checkout의 `.git` 파일을 가리키는지 확인한다. 복사되거나 수동 이동 후 repair하지 않은 worktree는 공유 index/HEAD를 건드리지 않고 등록 수정을 안내한다.

## Consequences

- 자동 초기화는 유지하며 ignored 파일의 수·크기에 비례하는 복사나 파일이 사라지는 구간을 없앤다. jj의 초기 snapshot 비용과 일반적인 Git/jj metadata 쓰기는 남는다.
- Python 3/POSIX 잠금이 없으면 자동 초기화를 건너뛴다. 경계 보호는 계속 동작하며 Git worktree를 훼손하지 않는다.
- Git index에 staged 변경이 있으면 자동 초기화를 건너뛰고 안내한다. 작업 파일과 다른 staged-only 내용을 잃지 않기 위해서다. 초기화 시 HEAD가 detach될 수 있지만 파일 내용·mtime·권한·inode 및 tracked deletion은 유지한다.
- sparse checkout이나 skip-worktree index entry가 있으면 누락 파일을 삭제로 snapshot하지 않도록 초기화·재시도를 건너뛴다. HEAD commit이 없는 orphan worktree도 초기 commit이 필요하다는 안내와 함께 그대로 둔다.
- Git harness는 기존 등록으로 worktree를 제거한다. 부모의 jj repo에 삭제된 workspace나 그 working-copy commit을 남기지 않는다. 제거 전 원하는 변경을 bookmark로 보존해야 하며, 해당 디렉터리의 삭제는 그 로컬 op log도 삭제한다.
- 강제 종료가 불완전한 jj metadata를 남길 수는 있다. plugin은 사용자 파일이나 기존 metadata를 지워 복구하려 하지 않고, 원래 Git worktree를 사용할 수 있는 상태로 남기며 검토할 오류 로그를 알린다.

## Validation

- `tests/hooks-test.sh`: 기존 감지/Muse 시나리오, worktree 생성과 무관한 ref 이동 보고, 초기화된 worktree와 명시적 공유 workspace의 Git 파일 변경 감지.
- `tests/worktree-boundary-test.sh`: 다른 worktree를 건드리지 않는 범위, ignored/dirty/untracked 파일의 inode·mtime·내용, 상대 gitdir와 마지막 줄바꿈, submodule·malformed 경계, shim, Muse 첫 실행 안내, 재안내 방지와 harness cleanup.
- `tests/adoption-failure-test.py`: 초기화 실패, 중단된 유효/불완전 metadata, 동시 실행과 강제 종료 후 잠금·재시도, sparse/skip-worktree와 staged-only 보존, 등록 검증 및 경로 재사용.
