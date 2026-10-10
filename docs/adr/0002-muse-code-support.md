# ADR 0002: Muse Code 지원

- Status: Accepted (Decision C, 실험 6으로 확인)
- Date: 2026-10-10

## Context

Muse Code(1.4.4)도 Claude 형식의 plugin을 설치할 수 있다. `muse plugins install <path>` 또는 marketplace로 설치하고, hook은 `muse plugins approve`로 승인해야 동작한다. 참고한 공식 문서는 다음 두 개다.
- [Hooks](https://meta-models.github.io/muse-code-sdk/1.4/guides/extend/hooks/#how-a-hook-answers)
- [Hook events reference](https://meta-models.github.io/muse-code-sdk/1.4/guides/plugins/reference/hook-events/)

### 문서로 확인한 것

| 항목 | 문서 내용 | 이 plugin |
|---|---|---|
| manifest | Claude 형식(`claude-compatible`) 설치 지원 | hook 5개와 `jj` skill이 모두 인식된다 |
| matcher | PreToolUse, PostToolUse, PostToolUseFailure에서 지원한다. 생략·빈 문자열·`*`은 모두 매칭하고, 영문·숫자·`_`·`\|`로만 된 값은 정확한 이름 목록이다. 기본 도구는 다른 agent의 이름에도 매칭된다: shell은 `Bash`/`shell`, 파일 도구는 `Read`, `Edit`, `Write`, 검색은 `Grep` | `Bash`, `Edit\|Write`가 그대로 걸린다 |
| PostToolUse 입력 | `tool_name`, `tool_input`, `tool_use_id`, `tool_response` | 같다(관찰) |
| PostToolUseFailure 입력 | `tool_name`, `tool_input`, `tool_use_id`, `error`, `is_interrupt`, `duration_ms`. `tool_response`는 없다 | 같다(관찰) |
| 출력 | exit 0이고 stdout이 JSON일 때만 읽는다. schema는 닫혀 있고 camelCase이며, `hookEventName`이 실행된 event와 같아야 한다 | 맞게 쓴다 |
| `additionalContext` | "Appended to the model's context." 어디에 붙는지는 문서에 없다 | |
| PostToolUse exit 2 | status `blocked`. stderr가 이유이며 "feedback to the model"이다. 결과를 대체하는지는 문서에 없다 | |
| PostToolUseFailure exit 2 | "Feedback only; the failed result stands." status `completed` | |
| PreToolUse deny | `permissionDecision: deny`와 비어 있지 않은 `permissionDecisionReason`으로 호출을 막는다. reason이 모델에게 어디로 가는지는 문서에 없다 | |
| 크기 한도 | hook 출력은 stream마다 16 KiB. 256 KiB를 넘는 hook 입력은 hook에 전달하지 않는다 | |
| reminder | 문서에 없다. third-party plugin에는 권하지 않는다 | 쓰지 않는다 |
| 환경 | 사용자 환경을 물려받지 않는다(PATH, HOME 등만 전달). plugin hook에는 `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, `MUSE_PLUGIN_ID` 등이 들어온다(관찰). `CLAUDE_ENV_FILE`은 없다 | shim을 쓸 수 없다. Codex와 같은 상황이다 |

PostToolUseFailure는 tool(명령)이 실패했을 때 호출된다. hook이 실패하거나 차단해서 호출되는 것이 아니다. 세션 기록으로 확인했다. 명령이 exit 0으로 끝났을 때는 우리 PostToolUse hook이 exit 2(`blocked`)로 끝나도 PostToolUseFailure가 호출되지 않았다. 명령이 exit 3으로 끝났을 때만 호출됐다.

### 실험 1: 이 저장소의 행동 테스트 (mitm 캡처 포함)

**방법**
- `mitmdump`을 reverse proxy로 띄워 `api.meta.ai`로 그대로 전달하고, `muse exec --base-url`로 이 proxy를 거치게 했다.
- 모델 요청 body(`/v1/responses`)만 저장했다. 인증 header는 저장하지 않았다.
- 지시는 "`./reset2.sh`를 실행한 뒤 `log.txt`에 `done`을 추가하라"로 했다. 여기에 "git이 이 repo의 파일을 바꿨다는 것을 알게 되면 즉시 `jj op log -n 3`을 실행하라"는 규칙을 붙였다.
- `reset2.sh`는 저장되지 않은 줄을 `git checkout --`으로 지우는 스크립트다. 모델이 미리 읽지 못하게 했다.
- 판정 기준은 알림을 본 뒤 `jj op log`를 실행했는가이다. 각 변형은 1~2회 실행했다.

| 변형 | 요청 안 알림 위치 | 행동 |
|---|---|---|
| `additionalContext`, 성공한 명령 | `input[0]` developer 메시지(약 46KB, workspace·rules·skills 등) 끝부분 97% 지점. 사용자 메시지(`input[1]`)와 tool 호출·결과보다 앞 | 실행하지 않음 |
| `additionalContext`, 실패한 명령(exit 3) | 위와 같음 | 실행하지 않음 |
| `additionalContext` + "알림은 developer context에 들어가니 명령마다 확인하라"는 일반 지시(SessionStart 안내에 추가), 성공·실패 | 알림 96%, 지시 99%. 둘 다 같은 developer 메시지 안 | 둘 다 실행하지 않음 |
| UserPromptSubmit `additionalContext`에 같은 일반 지시 | developer 메시지 | 2회 중 1회 실행 |
| 사용자 프롬프트에 같은 지시를 직접 씀(상한선) | 사용자 메시지 | 2회 모두 실행 |
| PostToolUse exit 2, stderr에 알림만 | `function_call_output`(tool 결과) 자리. 원래 결과는 사라짐 | 알림을 인용함 |
| PostToolUse `{"decision":"block","reason":…}` | 위와 같음 | 알림을 인용함 |
| PostToolUse exit 2, stderr에 "원래 `tool_response` + 빈 줄 + 알림" | `function_call_output` 안, 원래 결과 바로 뒤 | 곧바로 `jj op log -n 3`을 실행함 |
| PostToolBatch hook | | `muse exec`에서 호출되지 않음 |

### 실험 2: 다른 세션의 통제 실험

같은 문제를 다른 agent 세션이 따로 조사했다. 실험 1과 조건이 다르다.
- 지시는 중립적이다("`./reset2.sh`를 실행하고 결과를 보고하라"). 별도 규칙이 없다.
- 실제 Muse 요청 하나를 고정하고 알림 부분만 바꿔 같은 모델에 다시 보냈다(replay, 변형마다 5회, 도구는 실행하지 않음). 첫 응답이 알림을 직접 점검하는지를 blind로 판정했다.
- 효과가 있던 변형은 native Muse에서 3회 더 실행했다. 첫 명령만 고정하고, 이후 모델이 고른 도구는 실제로 실행했다.

| 변형 (모두 developer 역할) | 점검 |
|---|---|
| 알림 없음 | 0/5 |
| 원래 알림, `input[0]` 안 원래 자리 | 3/5 |
| 원래 알림을 `input[0]` 맨 끝으로 옮김 | 1/5 |
| 원래 알림 + 호출 식별 정보, `input[0]` 안 | 2/5 |
| 원래 알림 + 원래 결과 복사, `input[0]` 안 | 0/5 |
| 원래 알림을 별도 developer 메시지로, 사용자 메시지 **앞** | 5/5, 4/5 |
| 원래 알림을 별도 developer 메시지로, tool 결과 뒤 | 5/5 |
| 원래 알림 + "Before your final response, inspect the reported rewrite and determine whether it was intended by the user.", `input[0]` 안 원래 자리 | 5/5 |
| 위 문장에서 "Before your final response, "를 뺌 | 5/5 |
| native, 위 문장(앞부분 포함) | 3/3 점검. 보존을 요청한 경우 해당 파일만 복구하고 다시 읽어 확인했다. 중립 요청에서는 점검 후 스크립트의 변경을 의도된 것으로 보고 유지했다 |

### 실험 3: 실험 1의 조건에서 점검 문장 확인

실험 1과 같은 과제와 규칙을 썼다. exit 2 분기를 끄고, 알림 끝에 실험 2의 문장("Before your final response, inspect the reported rewrite …")을 붙였다. 전달은 `additionalContext`이다. proxy 없이 성공·실패 각 3회 실행했다. 모든 회차에서 hook은 알림을 냈다.

| 회차 | `jj op log` | 최종 응답에서 알림을 어떻게 다뤘나 |
|---|---|---|
| 성공 1 | `reset2.sh` 바로 다음 | rewrite를 보고. 시점은 언급하지 않음 |
| 성공 2 | 바로 다음 | "pre-existing", "happened before this session"이라며 이번 작업과 무관하다고 판단 |
| 성공 3 | jj skill을 읽은 뒤, 작업을 이어가기 전 | "pre-task notice", "predates this task" |
| 실패 1 | 실행하지 않음 | "No git-change notice appeared" |
| 실패 2 | 실행하지 않음 | "Pre-session note … unrelated to the current reset" |
| 실패 3 | 바로 다음 | 실행은 했지만 "pre-existing", "not from my ./reset2.sh run" |

- 성공한 명령에서는 반응이 0/2(실험 1)에서 3/3으로 올랐다. 실험 2와 맞는다.
- 실패한 명령에서는 1/3이다. 실패 경로는 이 문장만으로 해결되지 않는다.
- 새로 드러난 문제가 있다. 6회 중 4회에서 모델이 알림을 보고도 **세션 전에 일어난 일**로 해석했다. 알림이 사용자 메시지보다 앞(`input[0]`)에 있어서 "the last command"를 세션 이전 명령으로 읽은 것으로 보인다. 지시상 복구는 하지 않게 했으므로 피해는 없었다. 하지만 실제 상황이라면 "이번 작업과 무관하다"며 복구를 건너뛸 수 있다.
- 따라서 위치는 "알림을 보는가"보다 "알림이 언제 일어난 일인가"의 해석에 영향을 주는 것으로 보인다. 실험 2는 점검 여부만 판정했으므로 이 차이를 볼 수 없었다.

### 실험 4: 알림에 명령을 넣음

실험 3의 변형에서 "during the last command in …"을 "during the command `./reset2.sh` that you just ran in …"으로 바꿨다. 명령은 hook 입력의 `tool_input.command`에서 가져왔다. 조건은 실험 3과 같다.

결과를 실험 3과 함께 회차별로 분류했다.
- 이번 명령 일로 처리: 알림을 이번 명령의 결과로 받아들이고 점검했다.
- 세션 전 일로 해석: 알림은 봤지만 세션 전에 일어난 일로 판단했다.
- 못 봤다고 함: 알림이 없었다고 답했다.

| 변형 | 명령 | 이번 명령 일로 처리 | 세션 전 일로 해석 | 못 봤다고 함 |
|---|---|---|---|---|
| 점검 문장 (실험 3) | 성공 | 1 | 2 | 0 |
| | 실패 | 0 | 2 | 1 |
| 점검 문장 + 명령 (실험 4) | 성공 | 2 (1회는 `log.txt` 추가 뒤 점검) | 0 | 1 |
| | 실패 | 0 | 1 | 2 |

- 명령을 넣자 성공한 명령에서 시점 오해는 사라졌다(2/3 → 0/3). 다만 1회는 알림을 못 봤다고 했다.
- 실패한 명령은 두 변형 모두 0/3이다. 실험 4의 실패 2회차는 "내 실행 결과에는 rewrite 보고가 없었다"며 알림을 세션 전 일로 판단했다. 모델은 자기 명령에 대해서는 tool 결과를 믿고, developer 메시지에 있는 알림은 배경 정보로 다루는 것으로 보인다.
- 실험 1의 `additionalContext` 4회(일반 지시 변형 포함, UserPromptSubmit 변형 제외)와 실험 3·4를 합치면, Muse에서 `additionalContext`로 보낸 알림이 올바르게 처리된 경우는 성공 명령에서 3/8, 실패 명령에서 0/8이다. tool 결과 안에 넣은 경우(실험 1의 exit 2 + 원래 결과)는 1/1이었다.

### 실험 5: 다른 세션의 구현 검증

다른 세션이 별도 코드 line(hook을 Python으로 다시 쓴 버전)에서 tool 결과 자리에 알림을 넣는 방식을 구현하고 검증했다. 그 line은 이 저장소에 합치지 않는다. 여기서는 Muse 동작에 대한 관찰만 가져온다. 조건은 실험 1과 같은 fixture와 과제다.

- **성공한 명령:** exit 2 + 원래 결과 + 알림. 다음 요청에서 그 명령의 `function_call_output` 안, 원래 결과 뒤에 들어갔다.
- **실패한 명령:** 다음 tool의 PreToolUse가 `permissionDecision: deny`로 막고, `permissionDecisionReason`에 알림을 넣었다. 막힌 호출의 `function_call_output`으로 들어갔다. 원래 실패 결과는 그대로 남았다.
- **순서 문제:** 처음 구현은 성공 경로에 알림만 붙였다. 실제 성공 3회 중 1회에서 모델이 `./reset2.sh`와 `echo done >> log.txt`를 한 응답에 요청했다. 알림은 제자리에 있었지만 append가 점검보다 먼저 실행됐다. 그래서 성공 경로에도 다음 tool 보류를 걸었다.
- **최종 구현:** 알림이 남아 있으면 정해진 점검 명령이 정상 완료될 때까지 skill 읽기 외의 tool을 모두 막는다. 이 상태로 실제 모델 성공·실패 각 3회에서 6/6 모두 점검 → 발견 내용 설명 → 원래 작업 완료 순서를 지켰다.
- **Stop hook:** `decision: block`의 reason도 `input[0]` developer 메시지에 합쳐졌다. 3회 모두 점검하지 않았고 모델 요청만 1회 늘었다.
- **크기 한도:** Muse는 hook 출력 stream마다 16 KiB까지만 받는다. 256 KiB를 넘는 hook 입력은 hook에 전달하지 않는다(문서 확인). 큰 결과에 알림을 붙이면 한도를 넘을 수 있다.

### 실험 6: Decision C 구현 확인

아래 Decision을 구현한 plugin(hook 출력 기록만 더한 사본)으로 실험 1과 같은 과제와 규칙을 성공·실패 각 3회 실행했다. 실험 3·4와 같은 kit, 같은 모델(`muse-spark-1.3-contributor`)이다.

| 회차 | 알림이 들어간 자리 | 이후 순서 | 최종 응답의 시점 해석 |
|---|---|---|---|
| 성공 1 | `reset2.sh` 결과 안 | jj skill 읽기 → `jj op log` → 규칙대로 멈추고 보고(append 안 함) | "during it, git rewrote notes.txt" |
| 성공 2 | 같음 | `jj op log` → append | "during `./reset2.sh`" |
| 성공 3 | 같음 | jj skill 읽기 → `jj op log` → append | "during `./reset2.sh`" |
| 실패 1 | append가 보류되고 그 결과로 | `jj op log` → jj skill 읽기 → append | "during `./reset2.sh`" |
| 실패 2 | 같음 | `jj op log` → jj skill 읽기 → `jj op log` → append | 같음 |
| 실패 3 | 같음 | `jj op log` → jj skill 읽기 → append | 같음 |

- 6회 모두 append보다 먼저 `jj op log`로 점검했고, 알림을 이번 `./reset2.sh`의 일로 받아들였다. 실험 1·3·4의 `additionalContext`(성공 3/8, 실패 0/8)와 대비된다.
- 6회 모두 `reset2.sh`는 한 번, append는 많아야 한 번 실행됐다. 복구는 하지 않았다(지시대로). 성공 1회차는 "보고하고 멈추라"는 규칙대로 append 전에 멈췄다.
- 성공 회차에서는 모델의 다음 상태 변경 호출이 `jj op log`여서 보류가 일어나지 않았다. 한 응답에 script와 append가 함께 묶이는 경우는 이번 6회에서 나오지 않았다. 그 경우의 보류는 `tests/hooks-test.sh`로만 확인했다.
- `tests/hooks-test.sh` 76개가 통과했다. 지연은 `BENCHMARK.md`의 "0.3.1 이후" 절에 적었다. Bash 경로는 0.3.1과 같았다.

### 해석

- 알림이 `input[0]` developer 메시지에 합쳐졌을 때는 반응이 낮고 들쭉날쭉했다(실험 1에서 0/4, 실험 2에서 0~3/5).
- 처음에는 "사용자 메시지보다 앞에 놓이는 위치"가 원인이라고 봤다. 하지만 사용자 메시지 앞이라도 별도 메시지면 반응했다(5/5). 그래서 순서만의 문제로 볼 수 없다. 모델 내부의 원인은 측정하지 않았다. developer 역할 자체의 버그라는 근거도 없다.
- 원래 알림에도 이미 "Check with ..."라는 지시가 있다. 지시가 없어서 무시됐다고 볼 수는 없다.
- 효과가 있던 것은 알림 바로 뒤에 붙은, 이번 사건을 가리키는 구체적인 점검 문장이다. 실험 1의 일반 지시("developer context를 확인하라")는 알림과 떨어진 SessionStart 안내에 있었고 효과가 없었다. 두 실험은 지시문, 과제(여러 단계 대 한 단계), 판정 기준(즉시 `jj op log` 대 첫 응답의 점검), 표본 수가 모두 달라서 바로 비교할 수는 없다.
- hook이 알림을 별도 메시지로 만들 방법은 없다. Muse가 `additionalContext`를 `input[0]`에 합치기 때문이다.
- PostToolUse의 exit 2와 `block`은 tool 결과를 대체한다(문서에 없는 관찰된 동작).

## Options

| | C. 결과 대체 + 다음 상태 변경 tool 1회 보류 (제안) | D. C + 점검 명령이 확인될 때까지 보류 (실험 5의 구현) |
|---|---|---|
| 성공한 명령 | exit 2 + 원래 결과 + 알림 | 같음 |
| 실패한 명령 | 다음 상태 변경 tool을 막고 그 결과로 알림 전달 | 같음 |
| 보류 범위 | 알림 뒤 처음 오는 상태 변경 tool 1회. 알림을 이미 받은 뒤의 `jj` 명령은 통과시킨다 | 정해진 점검 명령이 정상 완료될 때까지 skill 읽기 외 모든 tool |
| 점검 방식 | 모델이 고른다(`jj op log`, `jj diff` 등) | plugin이 제공하는 점검 명령만 인정한다 |
| 구현 | 기존 bash hook에 상태 파일 하나와 분기 몇 개 | 상태 기계, file lock, receipt, 점검 helper (약 16 KB의 Python) |
| 근거 | 부분적으로만 검증됨(결과 대체, deny 전달은 실험 1·5에서 확인) | 실제 모델 6/6 |

## Decision

C를 택한다. D의 근거는 강하지만, 점검을 plugin이 정한 명령으로 강제하는 부분은 순서를 지키는 데 필요한 것보다 크다. C로 같은 조건의 실험에서 점검을 건너뛰는 일이 나오면 D의 요소를 그때 더한다.

1. **알림에 명령을 넣는다(모든 agent).** "during the last command in …"을 "during the command `<command>` that you just ran in …"으로 바꾼다. 명령은 hook 입력의 `tool_input.command` 첫 줄을 쓰고 200자에서 자른다. 나중에 전달할 때는 "during the command `<command>` that you ran earlier in …"으로 쓴다. 실험 4에서 시점 오해가 줄었고, 미뤄서 전달할 때는 "the last command"가 틀린 말이 된다.
2. **Muse, 성공한 명령:** 지금처럼 stderr에 "원래 `tool_response` + 빈 줄 + 메시지"를 쓰고 exit 2로 끝낸다. 그리고 알림을 "전달됨" 상태로 저장한다. stderr가 16 KiB를 넘게 되면 결과를 바꾸지 않고 "미전달"로 저장한다.
3. **Muse, 실패한 명령:** PostToolUseFailure는 알림을 "미전달"로 저장하고 아무것도 출력하지 않는다.
4. **PreToolUse matcher를 `Bash|Edit|Write|MultiEdit|NotebookEdit`로 넓힌다.** Muse에서는 기본 도구가 `Bash`, `Edit`, `Write` 이름에 매칭되고, Codex는 `apply_patch`를 `Edit|Write`로 매칭한다. Read와 Grep 같은 읽기 도구는 막지 않는다. Muse에서 저장된 알림이 있으면 다음처럼 한다.
   - 알림이 "전달됨"이고 이번 호출이 `jj`로 시작하는 Bash 명령이면 통과시키고 알림을 지운다. 모델이 알림을 보고 jj로 점검하거나 복구하는 경우다.
   - 그 밖에는 `permissionDecision: deny`로 막고 알림을 지운다. reason에는 "미전달"이면 알림 전체를, "전달됨"이면 앞선 결과의 알림을 가리키는 짧은 문장을 넣는다. 둘 다 "점검한 뒤 필요하면 이 호출을 다시 실행하라"를 덧붙인다.
   - 저장된 알림은 turn이 끝나도 남는다. 다음 turn의 첫 상태 변경 tool에서 전달된다. 하루가 지나면 SessionStart가 지운다(기존 baseline 정리 규칙과 같다).
5. **Stop hook은 쓰지 않는다.** 실험 5에서 Stop reason도 `input[0]`에 합쳐졌고 점검으로 이어지지 않았다.
6. **Claude Code와 Codex:** 알림 저장과 보류는 `MUSE_PLUGIN_ID`가 있을 때만 한다. 두 agent에서는 알림 문구(1번)만 바뀐다. Edit·Write 호출마다 PreToolUse hook이 한 번 더 뜨지만, Bash가 아니면 입력만 읽고 바로 끝낸다.
7. **확인한 것(실험 6).**
   - `tests/hooks-test.sh`: 상태 전이(전달됨/미전달, `jj` 통과, 1회 보류 후 해제, turn을 넘긴 전달), 16 KiB fallback, 두 agent에서 동작이 그대로인지.
   - 지연: Bash 경로가 그대로인지, Edit·Write의 PreToolUse 비용.
   - 실제 Muse: 실험 1의 과제로 성공·실패 각 3회. 판정 기준은 점검이 append보다 먼저인지, append와 script가 한 번씩만 실행됐는지, 알림을 이번 명령의 일로 받아들였는지다.

## Consequences

- Muse에서 알림은 항상 tool 결과 자리에 들어간다. 성공하면 그 명령의 결과 안에, 실패하면 다음에 막힌 호출의 결과로 들어간다.
- 보류는 1회뿐이다. 모델이 점검 없이 같은 호출을 다시 실행하면 막지 않는다. D와 달리 점검을 확인하지 않는다.
- 이미 한 응답에 묶인 호출이 셋 이상이면, 두 번째 호출이 막힌 뒤 세 번째 호출은 통과한다.
- 실패 직후 모델이 tool 없이 답을 끝내면, 알림은 다음 상태 변경 tool이 올 때까지 기다린다.
- 문서에 없는 동작 두 가지에 기댄다. PostToolUse exit 2가 결과를 대체한다는 것과, deny reason이 막힌 호출의 tool 결과 자리에 들어간다는 것이다. Muse를 올릴 때 `tests/hooks-test.sh`와 실제 실행으로 다시 확인한다.
- 원래 결과는 Muse가 만든 JSON 문자열을 다시 쓴 것이라 `\u` 같은 escape가 남을 수 있다.
- Muse에는 git 차단(shim)이 없다. 사후 감지와 다음 tool 보류만 된다.

## 설치 (Muse Code)

```bash
muse plugins marketplace add yejun-jj hyperthreading/jj-agent-plugins
muse plugins install jj-agent@yejun-jj
muse plugins approve jj-agent
```

GitHub marketplace로 설치하는 위 명령이 동작하는 것을 확인했다. 외부 plugin이라 hook은 승인 전까지 동작하지 않는다. skill은 plugin이 켜져 있으면 승인 없이 쓸 수 있다. `--scope project`를 줘도 사용자 영역(`~/.local/share/muse/plugins/`)에 user-local로 설치된다.
