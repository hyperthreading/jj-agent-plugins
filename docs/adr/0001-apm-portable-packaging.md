# ADR 0001: APM으로 jj-agent를 Claude Code와 Codex에 배포

- Status: Accepted
- Date: 2026-10-09

## Context

jj-agent(v0.2.0)는 Claude Code plugin이다. 목표는 두 가지다.
- 같은 plugin을 APM(`apm install`)으로도 설치할 수 있게 한다.
- Claude Code 외에 **Codex**를 지원한다.

기존 `claude plugin install` 경로도 계속 지원한다.

### APM 0.30.0의 동작

[hooks 문서](https://microsoft.github.io/apm/producer/author-primitives/hooks-and-commands/), `apm_cli/integration/hook_integrator.py`, scratchpad 실험으로 확인했다.

1. **번역 범위:** `apm install`은 hook의 event 이름과 `${PLUGIN_ROOT}`/`${CLAUDE_PLUGIN_ROOT}` 경로를 target에 맞게 바꾸고, 스크립트를 복사한다. matcher와 스크립트의 의미는 번역하지 않는다.
2. **target 제한:** package `apm.yml`의 `target:`/`targets:`로 그 package가 설치될 target을 제한할 수 있다. `targets: [claude, codex]`로 두고 claude, codex, gemini, copilot이 켜진 project에 설치하면, hook은 `.claude/settings.json`과 `.codex/hooks.json`에만 들어간다. skill은 `.agents/skills/`와 `.claude/skills/`에 들어간다.
3. **함께 복사되는 파일:** hook 스크립트 옆의 하위 디렉터리도 같이 배포되고, 실행 권한도 유지된다. `scripts/shim/git`이 `.claude/hooks/<pkg>/scripts/shim/git`, `.codex/hooks/<pkg>/scripts/shim/git`에 그대로 들어간다. 반면 지금처럼 `shim/`이 `scripts/` 밖에 있으면 복사되지 않는다.
4. **pack의 제약:** `apm pack`은 local path dependency(`../pkg`)를 거부한다. 같은 repo 안의 package끼리 dependency로 묶으면, 원격으로 publish하기 전에는 bundle을 만들 수 없다.
5. **Agent Plugins v1의 제약:** `apm pack --format agent-plugin`은 hooks를 담지 못한다. 이 결정에서는 쓰지 않는다.

### Codex hooks ([문서](https://learn.chatgpt.com/docs/hooks))

- event 이름이 Claude와 같다: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse` 등.
- 입출력이 Claude 방식과 호환된다. stdin에 `session_id`, `cwd`, `tool_name`, `tool_input`이 들어오고, stdout으로 `hookSpecificOutput.additionalContext`를 낼 수 있다. 차단은 exit 2 + stderr로 한다.
- matcher는 `tool_name`에 대해 동작한다. `Bash`가 있고, `apply_patch`는 `Edit`이나 `Write`로도 matching된다. 그래서 지금의 `Edit|Write|MultiEdit|NotebookEdit|Bash`가 Codex에서도 그대로 동작한다.
- **`CLAUDE_ENV_FILE` 같은 장치가 없다.** hook이 이후 shell 명령의 환경변수나 PATH를 바꿀 방법이 없으므로, Codex에서는 SessionStart에서 shim을 주입할 수 없다.
- `apply_patch`의 `tool_input`에는 `file_path`가 없다. `post-tool.sh`는 이 경우 `cwd`로 fallback한다(지금 코드 그대로).

## Decision (제안)

**plugin 하나(`plugins/jj-agent`)를 그대로 유지하고, `apm.yml`을 추가해 Claude Code와 Codex에서 함께 쓴다.** meta package나 harness별 adapter package는 만들지 않는다. Codex hook이 Claude 형식과 호환되므로 나눌 이유가 없고, 나누면 4번의 pack 제약에 걸린다.

### 1. 구조 변경

```
jj-agent-marketplace/
├── apm.yml                          # marketplace: block → .claude-plugin/marketplace.json 생성
├── .claude-plugin/marketplace.json  # 생성물, commit 함
└── plugins/jj-agent/
    ├── apm.yml                      # name, version, license, targets: [claude, codex]
    ├── .claude-plugin/plugin.json   # version은 apm.yml과 맞춤 (apm pack --check-versions)
    ├── skills/jj/SKILL.md
    ├── hooks/hooks.json             # PreToolUse(Bash) 추가: snapshot만 하고 차단하지 않음
    └── scripts/
        ├── lib.sh
        ├── session-start.sh         # shim 경로: scripts/shim
        ├── user-prompt.sh
        ├── pre-tool.sh              # 새로 추가: snapshot + 기준점 기록
        ├── post-tool.sh             # git 개입 감지 추가
        └── shim/git                 # shim/ → scripts/shim/ 으로 이동
```

- `targets: [claude, codex]`로 제한한다. Gemini, Copilot, Cursor에는 matcher와 입출력이 맞지 않는 hook이 조용히 설치되기 때문이다.
- `.gitignore`에 `apm_modules/`, `build/`를 추가한다.

### 2. git guard: Claude는 shim으로 예방하고, 두 harness 모두 PostToolUse에서 감지한다

| Harness | 예방 | 감지·복구 |
|---|---|---|
| Claude | SessionStart에서 `CLAUDE_ENV_FILE`로 shim을 PATH에 넣는다(지금과 같음) | PostToolUse 감지(backstop) |
| Codex | 없음. PATH 주입 수단이 없고, 명령을 고쳐 쓰면 승인 규칙이나 화면 표시와 충돌할 수 있다 | PostToolUse 감지 |

**감지는 Bash 명령 앞뒤에서 기준점을 비교하는 방식으로 한다.**

1. **PreToolUse(`Bash`), `pre-tool.sh`:** jj repo 안에서만 동작한다.
   - `jj util snapshot`을 실행한다.
   - 그 직후의 op id와 `.git/index` 내용 hash를 repo별·session별 state에 기록한다.
   - 차단하거나 명령을 고쳐 쓰지는 않는다.
2. **PostToolUse(`Bash`), `post-tool.sh`:** 자기 snapshot을 하기 **전에** `.git/index` hash를 먼저 읽는다. 그다음 snapshot하고, 기록해 둔 op 이후의 operation을 본다.
   - **강한 신호 1:** op에 `import git head` 또는 `import git refs`가 있다. git이 HEAD나 ref를 바꾼 것이다.
   - **강한 신호 2:** `.git/index` 내용이 바뀌었고, 그 사이에 snapshot 외의 jj op가 없다. git이 working copy를 바꾼 것이다. 스크립트 안에서 호출된 git도 잡는다.
   - **약한 신호:** 명령 문자열에 상태를 바꾸는 `git` subcommand가 있고, 그 사이에 파일이 바뀌었다(snapshot op가 있다).[^mixed]
3. 신호가 하나라도 있으면 `additionalContext`로 알린다.
   - pre 시점의 op id(복구 지점)를 알려준다.
   - 복구 순서: `jj op show <id>`로 확인한 뒤 `jj op restore <id>`, 또는 파일 단위로 `jj restore --from`.
   - 앞으로는 jj를 쓰라고 안내한다.
4. Edit/Write 계열에 대한 PostToolUse는 지금처럼 snapshot만 한다.

**실험(jj 0.46, colocated repo)으로 확인한 것:**
- `git commit`, `git reset --hard HEAD~1`은 다음 jj 명령에서 `import git head` op를 남긴다.
- `git checkout -- f`, `git stash`는 op 설명으로는 평소 편집(`snapshot working copy`)과 구분되지 않는다.
- `.git/index` **내용**의 변화:

  | 바뀐다 | 바뀌지 않는다 |
  |---|---|
  | `git checkout -- f`, `git restore`, `git stash`, `git reset --hard HEAD`, `jj commit`(parent가 바뀌므로) | `jj util snapshot`, `jj new`, `jj st`(이 셋은 mtime만 바뀜), `git status`/`diff`/`log`/`describe`(파일 편집 직후 포함), 일반 파일 편집 |

  그래서 mtime이 아니라 내용 hash로 비교한다.

**pre snapshot을 추가해서 얻는 것:**
- 복구 지점이 정확히 "이 명령 직전"이 된다.
- 사용자가 turn 사이에 직접 편집한 내용도 복구 지점에 포함된다.
- 그 사이의 op가 모두 이 명령 때문에 생긴 것이 되므로, 어떤 명령이 원인인지 정확히 특정할 수 있다.

**보호 범위:** 보호 대상은 명령이 시작되기 전의 상태다. 이 상태는 pre snapshot이 보장한다. 같은 명령 안에서 만든 변경을 그 명령이 다시 버리는 경우(예: `sed -i … f && git checkout -- f`)는 보호 대상이 아니다. 그건 명령 자체의 의도다. git은 커밋되지 않은 변경을 명시적인 폐기 명령(`checkout --`, `restore`, `reset --hard`, `stash`, `clean`)으로만 덮어쓰고, jj로 같은 명령을 짜도 결과는 같다.

**남는 한계:**
- `git clean`: jj가 snapshot한 파일은 git index에 내용 없는 entry로 올라가 있다. 그래서 `git clean -fd`는 이 파일들을 지우지 않는다(구현 중 실험으로 확인했다). 지워지는 것은 snapshot 뒤 같은 명령 안에서 새로 만든 파일, 그리고 `-x`로 지정한 ignored 파일뿐이다. 앞의 것은 명령의 의도이고, 뒤의 것은 jj도 추적하지 않는다.
- `jj op restore`는 그 명령이 한 정상적인 변경도 함께 되돌린다. 그래서 agent에게 먼저 확인하라고 안내한다.
- Bash 호출마다 jj snapshot이 한 번 더 돈다. 큰 repo라면 watchman을 권장한다(README에 이미 있음).

**이 방식을 고른 이유:** PreToolUse 차단은 명령 문자열을 heuristic으로 파싱해야 하고, 그래도 스크립트 안의 git은 놓친다. 명령을 고쳐 쓰는 방식은 승인 규칙과 화면 표시에 영향을 준다. 감지는 실제 상태 변화를 근거로 삼는다. 그래서 스크립트가 HEAD를 바꾼 경우까지 잡고, 명령에는 손대지 않는다. 손실 범위는 jj의 per-step snapshot이 이미 좁혀 두었다.

### 3. 설치 경로

| 소비자 | 명령 | 동작 |
|---|---|---|
| Claude Code (plugin) | `claude plugin marketplace add <repo>` → `claude plugin install jj-agent@yejun-jj` | 지금과 같다. `${CLAUDE_PLUGIN_ROOT}` 기준으로 동작한다 |
| Claude Code (APM) | `apm install <owner>/<repo>/plugins/jj-agent` | `.claude/settings.json`과 `.claude/hooks/jj-agent/`에 설치된다 |
| Codex (APM) | 위와 같은 명령 | `.codex/hooks.json`, `.codex/hooks/jj-agent/`, `.agents/skills/`에 설치된다. Codex의 `/hooks`에서 trust가 필요하다 |

`session-start.sh`의 shim 경로는 `CLAUDE_PLUGIN_ROOT`에 의존하지 않고 `$(dirname "$0")/shim`으로 찾는다. 그러면 plugin 설치와 APM 설치 모두에서 shim을 찾을 수 있다.

### 4. 지금 하지 않는 것

- Gemini, Copilot, Cursor adapter. 필요해지면 그때 별도 package(`target:` 지정)로 만든다.
- Codex plugin marketplace(`.agents/plugins/marketplace.json`) 출력. APM marketplace block에서 `codex: {}`를 켜기만 하면 되므로 Open question으로 둔다.

## Consequences

- Claude plugin 사용자 경험은 그대로다. 달라지는 점은 shim 위치와, git 개입 감지 알림이 추가되는 것뿐이다.
- Codex에서는 skill, snapshot, 알림, git 개입 감지·복구 안내가 동작한다. git을 미리 막지는 못한다.
- 소스는 plugin 하나다. version은 `apm.yml` 하나를 기준으로 삼는다.
- APM project scope로 설치하면 Codex hook command가 repo 기준 상대 경로가 된다(`.codex/hooks/...`). Codex를 하위 디렉터리에서 시작하면 hook을 찾지 못할 수 있다. APM의 동작이므로 README에 적어 둔다.

## Open questions

1. Codex marketplace 출력을 켤 것인가?
2. 원격 저장소에 publish할 계획: `tagPattern`과 jj bookmark/tag 운영 방식.

[^mixed]: 강한 신호 2는 그 사이에 parent를 바꾸는 jj op(예: `jj commit`)가 없을 때만 쓸 수 있다. 그런 jj op가 있으면 index 변화가 jj 때문인지 git 때문인지 구분할 수 없다. 그래서 `jj commit -m wip && ./script.sh`처럼 한 명령 안에 jj op와 "스크립트 안에서 working copy만 바꾸는 git"이 함께 있으면 감지하지 못한다. 이런 조합은 드물고, 감지하지 못해도 명령 시작 전 상태는 pre snapshot으로 복구할 수 있다. 그래서 한계로 다루지 않는다.
