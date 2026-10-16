# ADR 0004: snapshot에 task와 step 이름 남기기

- Status: Accepted
- Date: 2026-10-16

## Context

hook이 매 단계 snapshot을 남기지만, `jj op log`에는 모두 `snapshot working copy`로만 보인다. 어떤 작업(task) 중에 어떤 단계(step)가 만든 snapshot인지 알 수 없다.

jj 0.46에서 확인한 것:
- jj는 operation마다 그 op를 만든 명령의 인자를 `args` 속성으로 남긴다. `jj op log`가 기본으로 `args: ...` 줄을 보여 준다. 명령 실행 중에 생긴 snapshot op도 그 명령의 인자를 갖는다.
- `--config <key>=<value>`로 넘긴 값도 인자이므로 그대로 남는다. 모르는 key는 읽고 무시한다. value가 TOML로 읽히지 않으면 문자열로 받는다. 따옴표, 백슬래시, 한글이 들어가도 snapshot이 실패하지 않았다.
- op에 속성을 붙이는 다른 CLI는 없다. 0.46에서 template의 `operation.tags()`가 `attributes()`로 이름이 바뀌었다.
- 인자에 UTF-8이 아닌 바이트가 있으면 jj는 `Non-UTF-8 argument`로 바로 끝난다. snapshot도 남지 않는다.
- `jj evolog -r <id>`는 change 하나의 기록을 snapshot마다 보여 준다. 기본 출력에는 op 설명만 있고, template의 `operation.attributes()`로 `args`를 볼 수 있다.

## Decision

### 1. task는 agent가 `@`의 description으로 남긴다 (skill)

skill의 task loop를 바꾼다. 일을 시작할 때 `@`에 task 이름을 붙이고, 끝낼 때 `jj commit -m`으로 최종 메시지를 쓴다.

```bash
jj st
jj describe -m "<task>"     # @가 (empty)
jj new -m "<task>"          # @에 변경이 있음 (앞 task의 것이거나 남의 것)
# ... 작업 ...
jj commit -m "<최종 메시지>"
```

- 비어 있는지로 고르고, description이 있는지로 고르지 않는다. 편집 없이 끝난 task가 남긴 빈 `@`에 `jj new`를 하면 빈 커밋이 남는다(실험으로 확인).
- task가 진행되며 범위가 바뀔 수 있으므로 끝은 `jj new`가 아니라 `jj commit -m`이다.
- 방금 끝낸 task를 고치는 요청은 새 task가 아니다. 빈 `@`에서 고치고 `jj squash -u`로 합친다.
- 같은 working copy에서 동시에 도는 task는 이 방법으로 나눌 수 없다. skill은 `jj workspace add`를 안내한다.

task 이름은 change에 붙어 있어서 rebase나 squash를 따라가고, push하면 커밋 메시지가 된다. agent는 task마다 명령을 한 번 더 쓸 뿐이다(원래 끝에 하던 `jj commit -m`을 앞으로 당긴 것). skill에 있으므로 hook 없는 `jj-skill`에도 적용된다.

### 2. step은 hook이 snapshot의 인자로 남긴다

hook은 snapshot하는 jj 명령의 끝에 `--config 'jj-agent.step=<step>'`을 붙인다. `jj util snapshot`과, Bash 명령 뒤 `git_report`가 부르는 `jj op log`(snapshot을 겸함) 모두에 붙인다. jj 프로세스는 늘지 않는다.

| 호출 | step |
|---|---|
| shell 명령 (Claude Code) | `Bash: <Bash 도구의 description>` |
| shell 명령 (description 없음: Codex, Muse, 또는 생략) | `<tool_name>: <명령 첫 줄>` |
| Codex `apply_patch` (`command`가 `*** Begin Patch`로 시작) | `apply_patch: <patch가 건드린 파일, 쉼표로>` |
| 파일 도구 | `<tool_name> <repo 기준 상대 경로>` |
| UserPromptSubmit | `changes made between turns` |

- **길이:** 첫 줄만, 최대 100바이트. 잘린 곳에는 `...`을 붙인다. 긴 `sed` 패치나 here-doc이 op log를 덮지 않게 한다.
- **문자 경계:** 바이트로 자른 뒤, 잘린 multi-byte 문자를 버린다(`LC_ALL=C`에서 마지막 3바이트를 보고 lead byte를 찾는다). bash 3.2와 5에서 확인했다.
- **안전망:** 그래도 jj가 인자를 거부하면 태그 없이 한 번 더 snapshot한다. step을 남기는 것 때문에 snapshot을 잃지 않는다.
- **위치:** 인자의 맨 끝에 둔다. `args:` 줄을 읽을 때 step이 마지막에 보이고, 테스트에서 값을 꺼내기도 쉽다.
- **입력 key:** 새로 `tool_name`, `description`을 `json_get`으로 읽는다. 둘 다 `tool_input`이나 그 앞의 top-level key다. `tool_response`의 내용은 JSON 문자열 안에서 따옴표가 escape되어 있으므로 첫 일치가 되지 않는다(ADR 0003의 판단과 같다).

결과. `jj op log`는 `args:` 줄을 기본으로 보여 준다. `jj evolog`의 기본 출력에는 없으므로 template을 쓴다.

```
$ jj evolog -r @- --no-graph -T 'operation.description() ++ "  " ++ operation.attributes() ++ "\n"'
commit 9d5cbc17d176fb41c48038ddda284cb0e2d72715  args: jj commit -m 'fix: login redirect loop'
snapshot working copy  args: jj util snapshot --config 'jj-agent.step=Bash: Run unit tests'
snapshot working copy  args: jj util snapshot --config 'jj-agent.step=Edit src/login.js'
describe commit 9e582e28e00759e173c28b5155abfafb4d6f8b3f  args: jj describe -m 'fix: login redirect loop'
```

## 검토했지만 하지 않은 것

### agent가 부르는 snapshot 도구 (MCP)

- 매 단계 도구를 부르라는 것은 규칙이다. hook이 있는 이유가 agent가 규칙을 빠뜨린다는 것이다.
- MCP server가 생기면 bash와 jj 외의 runtime이 필요하다. agent마다 등록과 검증도 해야 한다.
- task 이름은 이미 `jj describe`가 맡는다.

### Codex에서 명령 앞에 이유를 붙이기 (`echo "<reason>";` 또는 `# <reason>`)

Codex shell 도구(`exec_command`)에는 Claude Code의 `description` 같은 인자가 없다. `justification`은 sandbox 밖 실행(`require_escalated`)을 요청할 때만 쓰라고 정해져 있다. 그래서 명령 문자열에 이유를 넣는 방법을 codex-cli 0.163.0으로 실험했다.

**방법:** 정해 둔 명령을 그대로 부르는 가짜 Responses API 서버를 model provider로 붙였다. `codex app-server`로 turn을 돌리며 승인 요청과 tool 결과를 기록했다(`approvalPolicy: on-request`, `sandbox: workspace-write`). `codex exec`는 승인 정책을 항상 Never로 두므로 승인 경로 실험에는 쓸 수 없었다. `codex execpolicy check`는 `bash -lc` 안의 스크립트를 풀지 않으므로 이것도 쓸 수 없었다. 규칙은 다음 두 개다.

```
prefix_rule(pattern = ["true", "allowed"], decision = "allow")
prefix_rule(pattern = ["true", "banned"],  decision = "forbidden")
```

**sandbox 안 실행 (escalation 없음):**

| 명령 | 승인 요청 | `forbidden` |
|---|---|---|
| `true banned` | 없음 | 막힘 |
| `# Step reason⏎true banned` | 없음 | **적용 안 됨, 실행됨** |
| `true banned # Step reason` | 없음 | **적용 안 됨, 실행됨** |
| `echo 'Step reason'; true banned` | 없음 | 막힘 |

**sandbox 밖 실행 요청 (`require_escalated`):**

| 명령 | 승인 요청 | 제안되는 "앞으로 허용" 규칙 |
|---|---|---|
| `true allowed` | 없음 (allow 규칙) | - |
| `# Step reason⏎true allowed` | **있음** | 스크립트 전체 |
| `echo 'Step reason'; true allowed` | **있음** | `["echo", "Step reason"]` |
| `echo 'Step reason' && true allowed` | **있음** | `["echo", "Step reason"]` |

- Codex는 스크립트를 단순 명령의 나열로 파싱할 수 있을 때만 규칙을 적용한다. 주석이 있으면 파싱에 실패하고, `forbidden` 규칙이 아무 경고 없이 꺼진다.
- `echo`는 파싱되지만, sandbox 밖 실행은 하위 명령마다 규칙이 맞아야 한다. 그래서 허용해 둔 명령도 매번 묻고, 엉뚱한 허용 규칙을 제안한다. sandbox 안에서는 `echo` 출력이 명령 결과 앞에 찍힌다.
- `echo "..."` 안의 `$VAR`, `` `...` ``, `$(...)`는 shell이 실행한다. agent가 쓴 설명이 명령이 된다.

그래서 Codex와 Muse에서는 명령 첫 줄을 step으로 쓰고, "왜"는 task 단위로 description이 맡는다.

## Consequences

- `jj op log`와 `jj evolog`에서 snapshot마다 step이 보이고, change description으로 task가 보인다.
- hook 비용은 bash 문자열 처리만 늘었다. jj 프로세스 수는 같다.
- prompt는 남기지 않는다. 명령 첫 줄과 Bash description은 로컬 op log에 남는다. op log는 git remote로 push되지 않는다.
- jj가 명령 인자를 `args`로 남기는 동작은 공개 문서에 약속된 것이 아니다. 바뀌면 step 이름만 사라지고 snapshot은 그대로 남는다. `tests/hooks-test.sh`의 step 시나리오가 이를 잡는다.
