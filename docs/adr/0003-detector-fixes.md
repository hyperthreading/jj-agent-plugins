# ADR 0003: git 변경 감지 보완

- Status: Accepted
- Date: 2026-10-10

## Context

다른 세션이 이 plugin을 별도 line에서 다시 구현하면서 ADR 0001의 감지 로직에 몇 가지 문제를 지적했다. 그 line(hook을 Python으로 다시 쓰고, git shim을 기본으로 통과시키는 버전)은 합치지 않는다. 같은 조건에서 재 보니 Bash 호출 1회의 hook 시간이 약 2배(62–67ms → 124–133ms, host load 9~10)였다. matcher를 `*`로 넓혀 Read 같은 다른 tool에도 호출마다 57–60ms가 붙었다. 지적 가운데 지금 코드에도 해당하고 bash로 작게 고칠 수 있는 것만 가져온다.

1. **index 경로 고정:** `save_index`와 `post-tool.sh`는 `<root>/.git/index`를 바로 읽는다. `.git`이 디렉터리가 아니라 `gitdir: <path>`를 담은 파일이면(git worktree, submodule) index 사본을 만들지 못한다. 그러면 신호 2(git이 다시 쓴 파일)가 아무 경고 없이 꺼진다.
2. **op 목록 50개 제한:** `git_report`는 `jj op log -n 50`에서 baseline op를 찾는다. 명령 하나가 그 사이에 jj op를 50개 넘게 만들면 baseline을 찾지 못한다. 그러면 신호 1(HEAD/ref 변경)을 놓친다. 신호 2는 `at_operation(<op>, @)`를 직접 쓰므로 영향이 없다.

## Decision

1. `.git`이 파일이면 첫 줄의 `gitdir:` 값을 읽어 index 경로를 정한다. 상대 경로는 repo root 기준으로 푼다. bash 내장 기능만 쓰고 git 프로세스는 띄우지 않는다. 경로를 정하지 못하면 지금처럼 신호 2를 건너뛴다.
2. 처음 50개에서 baseline op를 찾지 못했을 때만, `--ignore-working-copy`로 개수 제한 없이 한 번 더 읽는다. 첫 호출에서 이미 snapshot했으므로 다시 snapshot할 필요는 없다. 그래도 없으면 신호 1을 건너뛴다.

## 가져오지 않은 것

| 지적 | 이유 |
|---|---|
| 명령 직전에도 snapshot | ADR 0001의 "명령 시작 상태"에서 이미 정했다. 30,000 파일 repo에서 hook 하나에 약 36ms가 더 들고, turn 사이의 사용자 변경은 UserPromptSubmit이 snapshot한다. 남는 빈틈(turn 도중 다른 프로세스의 변경)도 그 ADR에 적혀 있다 |
| Python으로 JSON 파싱 | Python 프로세스 비용이 bash 정규식 파싱보다 크다. 지금 쓰는 key(`cwd`, `file_path`, `tool_use_id`, `session_id`, `tool_response`)는 첫 번째 일치가 맞는 값이다. ADR 0002에서 새로 쓰는 `command`는 세 agent의 입력 형태로 테스트에 넣어 확인한다 |
| git shim 기본 통과 | 이번 범위가 아니다. Claude Code의 shim 정책은 ADR 0001 그대로 둔다 |
| 감시할 repo 목록 설정(`JJ_AGENT_REPOS`) | 요구가 없다 |
| 줄바꿈이 든 파일 이름 | 드물다. 그런 이름은 지금 path 목록에서 빠질 수 있다 |

## Consequences

- git worktree나 submodule 안의 colocated repo에서도 신호 2가 동작한다.
- jj op가 많이 쌓이는 명령에서도 신호 1을 놓치지 않는다. 대신 그 드문 경우에만 op log 전체를 읽는다.
- 보통 경로의 비용은 그대로다. `.git`이 디렉터리인지 한 번 더 확인하는 것만 늘어난다.
- 검증: `tests/hooks-test.sh`에 `.git`이 `gitdir:` 파일인 repo(`git init --separate-git-dir` 뒤 `jj git init --colocate`)와 한 명령 안의 jj op 55개 시나리오를 넣었고 통과했다. jj는 git worktree 안에서도 colocate된다. `tests/hooks-bench.sh`로 잰 보통 경로의 지연은 0.3.1과 같았다(`BENCHMARK.md`).
