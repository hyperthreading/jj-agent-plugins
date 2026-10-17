# ADR 0005: 작업 파일을 이동하지 않는 공유 jj workspace 연결

- Status: Accepted
- Date: 2026-10-17

## Context

Harness가 만든 Git worktree에는 `.jj`가 없다. 중첩 worktree에서 부모의 `.jj`까지 올라가면 부모 working copy에 snapshot을 남기는 버그가 생기며, 외부 worktree에서는 plugin이 동작하지 않는다. 자동 전환은 유지한다.

PR #5의 첫 구현은 작업 파일을 복사·삭제·복원하고 Git 등록을 prune했다. 중단 시 파일 유실과 등록 손상이 발생하므로 이 경로를 제거했다. 이어서 시도한 `jj git init --colocate`는 파일을 보존했지만 **같은 Git 저장소에 독립된 jj repo 두 개**를 만들었다. 각 repo의 `jj util gc`가 다른 repo의 `refs/jj/keep/*`를 지우고, Git GC가 상대의 `@`와 이력 객체를 삭제하는 문제가 재현됐다. 경고로 남기지 않고 이 구조를 폐기한다.

`jj workspace add`는 기존의 비어 있지 않은 경로를 거부한다. 작업 파일을 이동하거나 jj 내부 protobuf/registry를 편집하지 않고, 공개 명령으로 새 metadata만 준비해서 연결한다.

## Decision

1. `.git` 파일은 repo 탐색 경계다. 상대 gitdir와 마지막 줄바꿈 없는 파일을 처리하고 submodule·malformed 파일에서는 부모로 넘어가지 않는다. cwd 또는 tool file path로 직접 만난 worktree만 연결한다. 다른 worktree를 전환하는 전체 순회와 ref 보고 예외는 두지 않는다.
2. Git admin의 backlink와 common dir를 확인한다. staged-only 내용, sparse/skip-worktree, unborn HEAD 또는 잘못된 등록은 그대로 두고 안내한다. 부모 디렉터리 권한 때문에 임시 metadata를 만들 수 없는 경우도 거절한다. 거절은 plugin data에 session별로 cache하며, index/HEAD/ref/config/등록/부모 디렉터리 signature가 바뀌면 다시 검사한다. cache hit에는 Git/jj 호출이나 중복 알림이 없다. metadata 갱신 후 같은 거절 사유가 확인되어도 다시 안내하지 않는다. 그 밖의 초기화 실패에는 기존 진단·재시도 동작을 유지한다.
3. worktree와 같은 부모 아래에 고유한 빈 임시 디렉터리를 만든다. 본체에서 `jj workspace add --ignore-working-copy --no-colocate --sparse-patterns full --name <unique> -r 'root()' <tmp>`를 실행한다. `root()`의 tree가 비어 있으므로 작업 파일은 생성되지 않는다. 본체 working copy도 snapshot하지 않는다.
4. 새 `.jj/.gitignore`를 준비하고 **생성한 metadata 디렉터리만** `<tmp>/.jj`에서 `<worktree>/.jj`로 rename한다. 같은 깊이의 형제 디렉터리라 `.jj/repo`의 상대 경로는 그대로 본체 저장소를 가리킨다. 작업 디렉터리 자체, `.git`, 기존 파일 및 삭제된 파일은 건드리지 않는다.
5. 대상에서 `jj util snapshot`을 실행한다. jj 0.46은 새 workspace의 colocation을 감지하고 기존 Git HEAD를 import한 다음 파일을 snapshot한다. 실제 삭제는 계속 삭제로 남는다. 대상에서 `sparse reset`을 실행해 삭제된 파일을 재생성하는 중간 상태도 만들지 않는다. **Git과 jj 저장소를 모두 공유**하므로 GC의 보존 참조 소유자는 하나다.
6. 실제 Git admin 경로에 따른 POSIX `flock`을 사용하고 자식 jj에 fd를 전달한다. helper만 죽어도 자식 종료까지 잠금이 남는다. pending 기록은 대상·admin identity, 임시 경로, workspace 이름, 생성 metadata identity를 보관한다. 중단 시 새 workspace를 중복 생성하지 않고 준비·연결·snapshot을 재개한다. 읽을 수 없는 metadata는 지우지 않고 오류 로그를 안내한다. 서로 다른 plugin-data 경로는 잠금을 공유하지 않으므로 일관된 설정이 필요하다.
7. 완료한 workspace의 실제 경로와 identity를 plugin data에 기록한다. SessionStart는 같은 repo에서 plugin이 완료한 workspace 중 checkout과 Git admin 디렉터리가 모두 제거된 것만 `jj workspace forget --ignore-working-copy`로 정리한다. 등록이 남아 있으면 수동 이동 후 repair 전 상태나 일시 미접근 경로일 수 있으므로 보존한다. 경로 검사 오류도 삭제의 증거로 보지 않는다. unrelated explicit workspace와 진행 중인 초기화는 건드리지 않는다. 손상되거나 읽을 수 없는 정리 기록은 남기고 다음 기록을 처리하며, cleanup 출력이 hook JSON에 섞이지 않게 한다.
8. 완료 안내는 한 번 전달한다. Muse PreToolUse에서는 baseline 옆에 보관했다가 실제 도구 결과로 전달하며 실패·큰 결과에서는 다음 호출을 보류한다(ADR 0002). Native Muse `path`는 hook cwd 기준으로 해석한다. HEAD/ref 변경 보고는 초기화와 무관하게 유지한다.

## Consequences and limits

- main/worktree 양쪽 GC가 같은 jj view와 op store를 사용한다. 기본 GC 뒤 양쪽의 현재 상태와 이전 snapshot을 읽을 수 있으며, 명시적 `--expire=now` 뒤에도 살아 있는 각 workspace의 현재 commit은 보호한다. 사용자가 명시적으로 만료시킨 과거 op까지 보존한다는 뜻은 아니다.
- 기존 파일의 내용·inode·mtime·mode·hardlink 및 tracked deletion을 보존한다. 작업 파일의 복사·이동·삭제, Git prune, private metadata 편집은 없다. 임시 디렉터리와 새 `.jj` metadata는 plugin이 생성한다.
- **jj 0.46의 기록 경로 한계:** jj의 workspace registry는 고유 임시 경로를 계속 가리킨다. 현재 checkout 안의 명령이나 `jj -R <actual-path>`는 정상 동작한다. 자동 연결한 workspace에 `workspace root --name`이나 `workspace remove`를 사용하지 않는다. Git harness가 원래 등록으로 제거하고, 이후 SessionStart가 해당 workspace를 forget한다. shared op log는 본체에 남으며 일반적인 jj retention을 따른다. 원하는 결과는 bookmark로 보존한다.
- 상대 repo pointer와 colocation import 동작은 jj 0.46에서 실제 검증한 계약이다. jj upgrade 시 GC·파일 보존·중단 테스트를 다시 실행해야 한다. 기존 독립 `.jj` 저장소의 이력을 자동으로 합치거나 재배치하지 않는다. 이전 미출시 PR 구현으로 만든 독립 repo는 별도 검토·복구가 필요하다.
- Python 3/POSIX 잠금이 없으면 자동 연결을 건너뛰며 경계 보호는 유지한다. 이미 연결한 workspace의 일반 훅에는 Python이 필요하지 않다. 거절 cache 확인과 SessionStart 정리는 예외다.
- 전역 jj operation history를 공유하므로 다른 workspace 작업도 op log에 보인다. 파일 복구 시 해당 checkout의 `at_operation(<op>, @)`를 확인하며, repo 전체 `op restore`는 다른 workspace에도 영향을 줄 수 있다.

## Validation

- `tests/hooks-test.sh`: 기존 감지/Muse 동작, worktree 생성과 unrelated ref 이동 보고, 공유 workspace의 Git 파일 변경 감지.
- `tests/worktree-boundary-test.sh`: 범위, 파일 metadata, 상대/no-newline gitdir, submodule 경계, shim, Muse native path·알림, Git cleanup.
- `tests/adoption-failure-test.py`: 준비/연결 전후 실패, 불완전 metadata 보존, 동시 실행, SIGKILL과 자식 잠금, 경로 재사용 및 staged/sparse 보호.
- `tests/gc-safety-test.py`: 양방향 GC, 현재/이전 작업 상태, 소유 workspace cleanup, session별 거절 cache와 상태 변경 재시도.
