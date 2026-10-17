# jj-agent 설계

coding agent(Claude Code, Codex, Muse Code)가 jj repo에서는 git 대신 jj를 쓰게 한다. 그래도 git이 repo를 바꾸면 그 사실과 복구 지점을 agent에게 알린다. `.jj`가 없는 곳에서는 아무것도 하지 않는다.

이 문서는 전체 구조와 결정의 요약이다. 결정의 근거와 측정은 ADR과 `BENCHMARK.md`에 있다.

| 문서 | 내용 |
|---|---|
| [ADR 0001](adr/0001-apm-portable-packaging.md) | 패키징(plugin, APM), git shim, git 변경 감지 알고리즘 |
| [ADR 0002](adr/0002-muse-code-support.md) | Muse Code 지원과 알림 전달 방식, 그 실험 |
| [ADR 0003](adr/0003-detector-fixes.md) | 감지 보완(gitdir 파일, 긴 op log)과 가져오지 않은 제안 |
| [ADR 0004](adr/0004-step-names-in-snapshots.md) | snapshot에 task와 step 이름 남기기, Codex 명령 접두어 실험 |
| [BENCHMARK.md](../BENCHMARK.md) | hook 지연, 단계별 비용, 측정 환경 |

## 원칙

- **jj repo에서만 동작한다.** 각 hook은 `.jj`를 찾아 디렉터리를 거슬러 올라가는 것으로 시작한다. 없으면 jj 프로세스를 띄우지 않고 바로 끝난다. repo를 `jj git init`으로 바꾸는 순간부터 동작한다. 세션 중간이어도 같다. 본체 repo가 jj repo인 곳에서 만든 `git worktree`(harness가 세션을 열기 전에 만든 worktree나 명령으로 추가한 worktree)는 만나는 즉시 같은 자리에서 colocated jj workspace(`jj workspace add --colocate`)로 바꾸고 안내한다. 본체에 `.jj`가 없는 일반 git worktree는 건드리지 않는다.
- **jj를 쓰게 하는 것은 skill이다.** 차단과 감지는 그 뒤를 받친다. agent가 skill을 잘 따른다면 hook 없이 skill만 담은 `plugins/jj-skill`을 대신 설치할 수 있다. skill 파일은 두 plugin에 같은 내용으로 복사해 두고 `tests/skill-sync-test.sh`로 확인한다. symlink는 plugin cache 복사, APM, Windows checkout에서의 동작을 보장할 수 없어서 쓰지 않는다.
- **명령을 고쳐 쓰지 않는다.** 명령 문자열을 분석해서 막지 않고, 명령 전후의 실제 상태를 비교한다. 그래야 스크립트 안의 git도 잡히고, agent의 승인 규칙이나 화면 표시에 영향을 주지 않는다.
- **stable component를 조합한다.** jj의 public 명령(`op log`, `diff`, `util snapshot`, `at_operation()`), git의 public 명령(`ls-files --debug`), 각 agent의 public hook protocol만 쓴다. 상태 저장소나 daemon을 새로 만들지 않는다.
- **hook은 Bash 호출마다 돈다.** 그래서 bash 내장 기능으로 입력을 파싱하고, jj 프로세스는 hook당 하나만 띄운다. 목표는 Bash 호출 1회에 100ms 미만이다.

## 구성 요소

```
plugins/jj-agent/
├── skills/jj/SKILL.md      # jj 작업 절차, 의도→명령 표, 충돌·push 절차, --help fallback
├── hooks/hooks.json        # 아래 hook 5개
└── scripts/
    ├── lib.sh              # 공용 함수 (입력 파싱, repo 탐색, worktree 전환, 감지, Muse 보류 상태)
    ├── session-start.sh    # SessionStart
    ├── user-prompt.sh      # UserPromptSubmit
    ├── pre-tool.sh         # PreToolUse (Bash|Edit|Write|MultiEdit|NotebookEdit)
    ├── post-tool.sh        # PostToolUse (Edit|Write|MultiEdit|NotebookEdit|Bash), PostToolUseFailure (Bash)
    └── shim/git            # Claude Code 전용 git wrapper
```

| 요소 | 하는 일 |
|---|---|
| skill `jj` | 모든 버전 관리 작업을 jj로 한다. jj 0.46 기준이며, 명령이 실패하면 `--help`로 확인하는 절차가 있다 |
| git shim | Claude Code에서 SessionStart가 `CLAUDE_ENV_FILE`로 PATH 맨 앞에 넣는다. jj repo 안에서 상태를 바꾸는 git(commit, checkout, reset, stash 등)을 막고 jj 명령을 안내한다. 읽기 전용 git과 jj가 내부에서 부르는 git은 통과시킨다. `JJ_SHIM_OFF=1`이면 그대로 git을 부른다 |
| SessionStart | shim을 PATH에 넣는다(Claude Code). 세션이 jj repo(또는 jj repo의 git worktree)에서 시작하면 그 사실을 알린다. 오래된 상태 파일을 지운다 |
| UserPromptSubmit | snapshot한다. 사용자가 turn 사이에 바꾼 것을 agent가 움직이기 전에 기록해 둔다. turn 사이에 jj repo가 된 곳이나 새로 만든 git worktree도 여기서 알린다 |
| PreToolUse | Bash 명령 전에 baseline(마지막 op id와 git index 사본)을 남긴다. Muse에서는 보류된 알림이 있으면 이 호출을 한 번 막는다 |
| PostToolUse, PostToolUseFailure | 매 편집과 명령 뒤에 snapshot해서 각 단계가 `jj op log`에 남게 한다. snapshot op에는 그 단계의 이름(`jj-agent.step`)이 붙는다. Bash 명령 뒤에는 새로 추가된 git worktree를 colocated jj workspace로 전환하고, git 변경을 판정해 알린다 |

## agent별 동작

| | Claude Code | Codex | Muse Code |
|---|---|---|---|
| 설치 | plugin marketplace, 또는 APM | plugin marketplace(같은 파일을 읽음), 또는 APM | plugin marketplace + `muse plugins approve` |
| git 예방 | shim | 없음(hook이 PATH를 바꿀 수 없음) | 없음(같은 이유) |
| 사후 감지 | 있음(shim의 backstop) | 있음 | 있음 |
| 실패한 명령 | PostToolUseFailure로 감지 | PostToolUse로 감지(실패해도 PostToolUse가 옴) | PostToolUseFailure로 감지 |
| 알림 전달 | `additionalContext` (tool 결과 바로 뒤에 붙음) | `additionalContext` | tool 결과 안. 아래 "Muse Code의 알림 전달" |

APM으로 설치할 수 있는 target은 `claude`, `codex`로 제한한다. 다른 target에는 matcher와 입출력이 맞지 않는 hook이 조용히 설치되기 때문이다(ADR 0001).

## Bash 호출 1회의 흐름

1. **PreToolUse:** `jj op log --ignore-working-copy -n1`로 마지막 op id를 읽고, git index를 copy-on-write로 복제한다(`cp -c`, `--reflink=auto`). 둘을 `tool_use_id`별 baseline 파일로 남긴다. snapshot은 하지 않는다. 직전 PostToolUse와 이번 turn의 UserPromptSubmit이 이미 했기 때문이다.
2. **명령 실행.**
3. **PostToolUse 또는 PostToolUseFailure:**
   1. 어떤 jj 명령보다 먼저 현재 git index를 baseline 사본과 비교한다(`cmp`). 다르면 지금 index도 복제한다. 다음 단계의 jj가 index를 다시 쓰기 때문이다.
   2. `jj op log -n 50 --config 'jj-agent.step=<step>'`을 실행한다. 이 명령이 snapshot과 op 목록 읽기를 한 번에 한다. jj가 명령 인자를 op에 남기므로 snapshot op에 step 이름이 붙는다. baseline op가 그 안에 없으면 전체 log를 한 번 더 읽는다.
   3. 아래 두 신호로 판정한다.
   4. 알림을 만들어 agent별 경로로 전달한다. baseline 파일은 지운다.

Edit·Write 뒤의 PostToolUse는 snapshot만 한다. 이때도 step 이름을 붙인다.

## task와 step 이름

자세한 내용은 ADR 0004에 있다.

- **task:** agent가 일을 시작할 때 `jj describe -m`(`@`가 비었을 때)이나 `jj new -m`으로 `@`에 붙인다. skill의 task loop에 있다.
- **step:** hook이 snapshot하는 jj 명령 끝에 `--config 'jj-agent.step=<step>'`을 붙인다. jj는 명령 인자를 op의 `args`로 남긴다. Bash는 Claude Code Bash 도구의 `description`, 없으면 명령 첫 줄을 쓴다. 파일 도구는 도구 이름과 경로, Codex patch는 patch가 건드린 파일을 쓴다. 첫 줄만, 최대 100바이트이고 문자 경계에서 자른다. jj가 인자를 거부하면 태그 없이 다시 snapshot한다.
- `jj op log`의 `args:` 줄에 보인다. change 하나의 단계별 기록은 `jj evolog -r <id> -T 'operation.description() ++ "  " ++ operation.attributes() ++ "\n"'`로 본다.

## git 변경 감지

자세한 내용과 사례 표는 ADR 0001에 있다.

- **신호 1, HEAD나 ref 이동:** baseline op 뒤에 `import git head`나 `import git refs` op가 생겼다. jj는 git이 HEAD를 옮긴 것을 다음 snapshot에서 이렇게 기록한다.
- **신호 2, git이 다시 쓴 파일:** 아래 A와 B의 교집합이다. index가 바뀌었을 때만 계산한다.
  - B는 명령 전후로 내용이 바뀐 path다. `jj diff --from 'at_operation(<baseline>, @)' --to @ --name-only`로 구한다.
  - A는 그 path 가운데 git이 index entry의 stat을 새로 채운 것이다. `git ls-files --debug`로 두 index 사본을 비교한다.
  - 이것이 git의 쓰기를 가려내는 이유: jj는 index entry를 stat 없이(0으로) 쓴다. git은 파일 내용이 index와 같은 entry에만 stat을 채운다. 그래서 내용이 바뀌었는데 stat이 채워졌다면 git이 그 파일을 index 내용으로 다시 쓴 것이다(`checkout --`, `restore`, `stash`, `reset --hard`). `git status`의 stat 갱신만으로는 B에 들지 않고, `sed` 같은 편집은 A에 들지 않는다.
- **index 위치:** `.git`이 디렉터리면 `.git/index`, `gitdir:`을 담은 파일이면 그 경로의 `index`다(git worktree, submodule, `--separate-git-dir`).

**보호 범위:** 보호 대상은 명령이 시작되기 전의 상태다. 같은 명령 안에서 만든 것을 그 명령이 다시 버리는 경우는 명령의 의도로 보고 알리지 않는다.

**알려진 한계:**
- **오탐:** 같은 명령 안에서 파일을 git 없이 `@-` 내용으로 되돌리고(`jj restore`, `sed`) 그 뒤에 git이 그 파일을 읽으면 알림이 나간다. 알림에 "직접 되돌렸다면 무시하라"는 안내가 있다.
- **빈틈:** turn 도중에 다른 사람이나 프로세스가 바꾼 파일은 명령 시작 상태에 없다. git이 그것을 덮어써도 알리지도, 복구하지도 못한다.
- **jj가 기록하는 것만 복구할 수 있다.** ignored 파일(`.env` 등)은 snapshot 대상이 아니다.

## 알림

알림 한 개에 들어가는 내용:
- 명령 이름: "during the command \`./x.sh\` that you just ran in <repo>". 나중에 전달할 때는 "that you ran earlier"로 쓴다.
- 이유: "git moved HEAD or refs", "git rewrote these files: <paths>" (최대 20개).
- 복구 지점: 명령 직전의 op id.
- 확인과 복구 방법: `jj op log`, `jj op show`로 확인하고, 파일 단위로 `jj restore --from 'at_operation(<op>, @)' <paths>`, 또는 repo 전체를 `jj op restore <op>`로 되돌린다(명령이 한 다른 일도 함께 되돌아간다).
- 파일을 직접 되돌렸다면 무시하라는 안내(파일 목록이 있을 때).

agent가 처음 jj repo를 만나면(세션 시작, `jj git init` 직후, 다른 jj repo로 `cd`) 한 번 알린다. 이 안내에는 jj skill을 쓰고 상태를 바꾸는 git은 쓰지 말라는 내용이 들어 있다.

## Muse Code의 알림 전달

Muse는 hook의 `additionalContext`를 요청 맨 앞의 developer 메시지에 합친다. 거기 들어간 알림을 모델은 놓치거나, 세션 전에 일어난 일로 해석했다. 실험에서는 성공한 명령 3/8, 실패한 명령 0/8만 제대로 처리됐다. Stop hook의 피드백도 같은 자리로 갔다. 그래서 Muse에서는(`MUSE_PLUGIN_ID`가 있을 때) 알림을 tool 결과 자리에 넣는다. 자세한 근거는 ADR 0002에 있다.

| 상황 | 동작 |
|---|---|
| 명령이 성공했고 알림이 있음 | exit 2로 끝내고, stderr에 "원래 결과 + 빈 줄 + 알림"을 쓴다. Muse는 이것으로 그 명령의 결과를 바꾼다. 알림은 "전달됨"으로 저장한다 |
| 위 출력이 16 KiB를 넘음 | Muse는 출력이 16 KiB를 넘는 hook을 강제 종료하므로 결과는 그대로 둔다. 알림을 "미전달"로 저장한다 |
| 명령이 실패했고 알림이 있음 | 실패 결과는 바꿀 수 없다. 알림을 "미전달"로 저장한다 |
| 다음 PreToolUse(Bash, Edit, Write)에 저장된 알림이 있음 | 이 호출을 `permissionDecision: deny`로 한 번 막고 알림을 지운다. reason에는 "미전달"이면 알림 전체, "전달됨"이면 앞선 결과를 가리키는 문장이 들어간다. 막힌 호출의 결과 자리로 들어간다 |
| 알림이 "전달됨"이고 다음 호출이 `jj` 명령 | 막지 않고 알림만 지운다. 모델이 알림을 보고 점검하거나 복구하는 경우다 |

- **성공한 명령 뒤에도 보류하는 이유:** 모델이 script와 다음 편집을 한 응답에 묶어 요청하면, 결과의 알림을 읽기 전에 편집이 실행된다.
- **보류 범위:** 보류는 한 번뿐이고, Read와 Grep 같은 읽기 도구는 막지 않는다.
- **turn이 끝나도 남는다:** 저장된 알림은 다음 turn의 첫 상태 변경 호출에서 전달된다.
- **실측:** 실제 Muse 실행 6회(성공 3, 실패 3) 모두, 모델이 이어지는 작업 전에 jj로 점검했다. 그리고 알림을 그 명령의 일로 받아들였다.

기대는 동작 두 가지는 Muse 문서에 없다. 하나는 PostToolUse exit 2가 결과를 대체한다는 것, 다른 하나는 deny reason이 막힌 호출의 결과 자리로 간다는 것이다. Muse를 올릴 때는 `tests/hooks-test.sh`와 실제 실행으로 다시 확인한다.

## 상태 파일

모두 `CLAUDE_PLUGIN_DATA`(없으면 `$TMPDIR/jj-agent`) 아래에 둔다. project 디렉터리에는 쓰지 않는다.

| 경로 | 내용 | 정리 |
|---|---|---|
| `sessions/<session_id>` | 이 세션에서 이미 알린 jj repo 목록 | SessionStart가 비우고, 14일 지난 파일을 지운다 |
| `baselines/<tool_use_id>`, `.index`, `.post` | Bash 명령 1회의 baseline op와 index 사본 | PostToolUse가 지운다. 남은 것(중단, 거부)은 하루 뒤 SessionStart가 지운다 |
| `pending/<session_id>` | Muse에서 보류한 알림. 1행은 `delivered`나 `undelivered`, 그 뒤는 명령이나 알림 본문 | 다음 상태 변경 호출이 지운다. 하루 지난 것은 SessionStart가 지운다 |

## 성능

| repo | Bash 호출 1회 (pre + post, 0.3.1) |
|---|---|
| jj repo 아님 | 약 6ms |
| 파일 10개 | 약 51ms |
| 파일 30,000개 | 약 91ms |

- **비용 구성:** 대부분은 jj 프로세스 시작(hook당 약 15ms)과, 파일 수에 비례하는 post의 snapshot이다.
- **비용을 줄이는 방법:**
  - hook을 `/bin/bash`로 띄운다. 입력 파싱과 repo 탐색은 bash 내장 기능으로만 한다.
  - pre에서는 snapshot하지 않는다.
  - index는 copy-on-write로 복제한다.
  - `ls-files`는 내용이 바뀐 path에만 돌린다.
- **Muse 보류 추가 뒤:**
  - Bash 경로는 0.3.1과 같았다.
  - Claude Code와 Codex의 Edit·Write에 새로 걸린 PreToolUse는 입력만 읽고 끝난다.
- 수치와 측정 환경은 `BENCHMARK.md`에 있다.

## 하지 않기로 한 것

| 제안 | 이유 | 근거 |
|---|---|---|
| PreToolUse에서 명령 문자열을 분석해 막기 | heuristic이고, 스크립트 안의 git을 놓친다 | ADR 0001 |
| 명령을 고쳐 쓰기(wrapper로 감싸기) | 승인 규칙과 화면 표시에 영향을 준다 | ADR 0001 |
| 명령 직전에도 snapshot | 30,000 파일에서 hook당 약 36ms. turn 사이의 변경은 UserPromptSubmit이 잡는다 | ADR 0001, 0003 |
| hook을 Python으로 다시 쓰기, matcher `*` | 같은 조건에서 Bash 호출이 약 2배, 다른 tool마다 약 60ms 추가 | ADR 0003 |
| shim을 기본으로 통과시키기 | Claude Code의 예방 수단을 없앤다. 이번 범위가 아니다 | ADR 0003 |
| Muse에서 `additionalContext`나 Stop hook으로 알리기 | 모델이 놓치거나 세션 전 일로 해석했다 | ADR 0002 |
| Muse에서 정해진 점검 명령이 끝날 때까지 모든 tool 보류 | 순서를 지키는 데 필요한 것보다 크다. 1회 보류로 실측 6/6 | ADR 0002 |
| Gemini, Copilot, Cursor 지원 | hook 입출력이 맞지 않는다. 필요해지면 별도 package로 만든다 | ADR 0001 |
| agent가 부르는 snapshot 도구(MCP) | 매 단계 부르는 규칙은 빠뜨리기 쉽고, bash와 jj 외의 runtime이 필요하다 | ADR 0004 |
| Codex에서 명령 앞에 이유 붙이기(`# ...`, `echo ...;`) | 주석은 `forbidden` 규칙을 끄고, 둘 다 sandbox 밖 실행에서 허용된 명령도 다시 묻게 한다 | ADR 0004 |

## 테스트와 측정

- `tests/hooks-test.sh`: 실제 jj repo에서 hook을 Claude Code·Codex·Muse 형식의 입력으로 부르는 시나리오 테스트다. 전체 PATH와 jq·shim이 없는 최소 PATH에서 각각 돈다. 다음을 확인한다.
  - git 변경 판정
  - 알려진 오탐과 빈틈
  - shim
  - `.jj`가 없는 곳에서 아무것도 하지 않는지
  - Muse 보류 상태 전이
  - snapshot op에 붙는 step 이름(길이 제한, UTF-8 경계 포함)
- `tests/hooks-bench.sh`, `tests/hooks-profile.sh`: repo 크기별 hook 지연과 단계별 비용을 잰다.
- 실제 Muse 모델로 하는 행동 실험은 repo에 넣지 않았다. 방법과 결과는 ADR 0002의 실험 1~6에 있다.
