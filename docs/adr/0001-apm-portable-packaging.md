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
   - `jj op log --ignore-working-copy -n1`로 마지막 op id만 읽는다. snapshot은 하지 않는다(아래 "명령 시작 상태" 참고).
   - op id와 `.git/index` 사본을 tool call별(`tool_use_id`) baseline으로 남긴다. 사본은 APFS에서 `cp -c`(clone), Linux에서 `cp --reflink=auto`로 만들어서 비용을 줄인다.
   - 차단하거나 명령을 고쳐 쓰지는 않는다.
2. **PostToolUse(`Bash`), `post-tool.sh`:** Claude Code는 exit code가 0이 아닌 명령에 PostToolUse 대신 PostToolUseFailure를 보내므로, 같은 스크립트를 두 이벤트에 건다. Codex는 실패한 명령에도 PostToolUse를 보내고, 모르는 이벤트 이름(`PostToolUseFailure`)은 무시한다(실험으로 확인). 어떤 jj 명령보다 **먼저** `.git/index`를 사본과 비교(`cmp`)한다. 다르면 현재 index도 복제해 둔다. jj가 HEAD 변경을 import하면서 index를 다시 쓰기 때문이다. 그다음 `jj op log -n50`으로 snapshot과 op 목록 읽기를 한 번에 하고 판정한다.
   - **신호 1, HEAD/ref 변경:** 기록해 둔 op 이후의 op에 `import git head` 또는 `import git refs`가 있다.
   - **신호 2, git이 다시 쓴 파일:** 아래 두 path 집합의 교집합이 비어 있지 않다. index가 바뀐 경우에만 계산한다.
     - **B, 내용이 바뀐 path:** `jj diff --from 'at_operation(<pre op>, @)' --to @ --name-only`. 명령 직전과 직후 working copy tree의 차이다. 먼저 구한다.
     - **A, git이 index 정보를 새로 채운 path:** B가 비어 있지 않을 때만 B의 path에 한정해 `git ls-files --debug`로 두 index 사본을 비교한다. stat 정보가 바뀌었고 새 값이 0이 아닌 entry다. `jj commit`처럼 index는 바뀌지만 파일 내용은 그대로인 명령에서는 실행되지 않는다.
3. 신호가 하나라도 있으면 `additionalContext`로 알린다.
   - 신호 2가 있으면 해당 path 목록을 함께 준다.
   - pre 시점의 op id(복구 지점)를 알려준다.
   - 복구 방법: `jj op show`로 확인한 뒤 파일 단위로 `jj restore --from 'at_operation(<op>, @)' <paths>`, 또는 `jj op restore <op>`.
   - 직접 되돌린 파일이면 무시하라고 덧붙인다.
4. Edit/Write 계열에 대한 PostToolUse는 지금처럼 snapshot만 한다.

**A∩B가 git의 쓰기를 가려내는 이유:**
- **jj가 index를 쓰는 방식:** jj는 parent를 바꿀 때 index를 다시 쓰고, 바뀐 entry의 stat 정보를 0으로 비워 둔다.
- **git이 stat을 채우는 조건:** git은 파일 내용이 index와 같은 entry에만 stat을 채운다. `git status`/`describe`가 갱신할 때도, `checkout -- <path>`/`restore`/`stash`/`reset`으로 파일을 다시 쓸 때도 마찬가지다.

| 같은 명령 안에서 | A | B | 결과 |
|---|---|---|---|
| `git checkout -- f`, `restore`, `stash`, `reset --hard` | f | f | 감지 |
| `sed`로 f 편집 (+ `git status`) | – | f | 알림 없음. f 내용이 index와 달라 stat이 채워지지 않음 |
| `git status`/`describe`의 stat 갱신 | g, h | – | 알림 없음 |
| `jj commit`, `jj new <rev>` | –(0으로 비움) | 바뀐 파일 | 알림 없음 |
| `jj commit && ./script.sh`(안에서 `git checkout -- f`) | f | f(내용이 사라졌다면) | 감지 |

**실험(jj 0.46, colocated repo)으로 확인한 것:**
- `git commit`, `git reset --hard HEAD~1`은 다음 jj 명령에서 `import git head` op를 남긴다.
- `git checkout -- f`, `git stash`는 op 설명으로는 평소 편집(`snapshot working copy`)과 구분되지 않는다.
- jj가 쓴 index entry는 stat이 0이다(`git ls-files --debug`의 `mtime: 0:0`). `git status`/`diff`는 그런 entry 가운데 내용이 같은 것의 stat을 채워 index 내용을 바꾼다. 처음 구현은 "index 내용 hash가 바뀌었고 그 사이에 jj op가 없으면 git"으로 판정했는데, `jj commit` 직후 `echo z >> f; git status`에서 오탐이 났다. 그래서 path 단위 교집합으로 바꿨다.

**명령 시작 상태:** pre에서는 snapshot을 하지 않는다. 직전 tool call의 PostToolUse가 이미 snapshot했으므로, 마지막 op가 곧 명령이 시작되는 상태다. 사용자가 turn 사이에 편집기나 자기 터미널에서 바꾼 것은 UserPromptSubmit hook이 snapshot한다. 그래서 그 변경은 복구 지점에 들어가고, 이번 명령이 한 일로 잘못 알리지도 않는다. 처음에는 pre에서도 snapshot했지만, 30,000 파일 repo에서 hook 하나에 약 36ms가 더 들어서 뺐다.

빈틈은 turn이 진행되는 도중에 다른 사람이나 프로세스가 같은 repo를 바꾸는 경우다. 그 변경은 명령 시작 상태에 없으므로, git이 그것을 덮어써도 알리지 못하고 복구할 수도 없다. 그 사이에 사용자가 터미널에서 git으로 HEAD를 옮겼다면 이번 명령이 한 것으로 알린다.

**보호 범위:** 보호 대상은 명령이 시작되기 전의 상태다. 같은 명령 안에서 만든 변경을 그 명령이 다시 버리는 경우(예: `sed -i … f && git checkout -- f`)는 보호 대상이 아니다. 그건 명령 자체의 의도다. git은 커밋되지 않은 변경을 명시적인 폐기 명령(`checkout --`, `restore`, `reset --hard`, `stash`, `clean`)으로만 덮어쓰고, jj로 같은 명령을 짜도 결과는 같다.

**남는 한계:**
- **오탐:** 같은 명령 안에서 파일을 git이 아닌 방법(`sed`, `jj restore`, `jj abandon` 등)으로 index 내용(`@-`)으로 되돌리고, 그 뒤에 git이 그 파일을 읽으면 A∩B에 들어간다. 이 경우 알림만 나가고 아무것도 되돌리지 않는다. 알림에 path 목록과 "직접 되돌렸다면 무시하라"는 안내가 있어서 agent가 판단할 수 있다.
- **비용:** jj repo 안의 Bash 호출 1회에 jj 프로세스 2개(pre는 snapshot 없는 op 조회, post는 snapshot 포함)와 index 사본이 든다. clone을 지원하지 않는 filesystem에서는 실제로 복사한다. hook은 `/bin/bash`가 있으면 그것으로 실행한다(없으면 PATH의 `bash`). 입력 파싱과 jj repo 탐색은 bash 내장 기능만 써서 jq나 `dirname` 프로세스를 띄우지 않는다.
- **측정** (`tests/hooks-bench.sh`, `tests/hooks-profile.sh`, macOS, jj 0.46, median ms, git shim 없는 PATH). Bash 호출 1회 기준이고, 괄호 안은 최적화 전 값이다.

  | repo | pre | post | post+git | post(edit) |
  |---|---|---|---|---|
  | jj repo 아님 | 3 (46) | 3 (96) | – | – |
  | 10 files | 20 (91) | 25 (110) | 42 | 51 |
  | 5,000 files | 21 (99) | 35 (118) | 49 | 62 |
  | 30,000 files | 21 (131) | 70 (150) | 72 | 98 |

  단계별 비용(10 files / 30,000 files):

  | 단계 | hook | ms |
  |---|---|---|
  | `/bin/bash` 시작 | 둘 다 | 2 / 3 |
  | lib.sh 로드, 입력 파싱, jj repo 탐색 | 둘 다 | 1 / 1 이하 |
  | `jj op log --ignore-working-copy -n1` | pre | 16 / 15 |
  | index 사본 (`cp -c`) | pre | 2 / 2 |
  | `cmp` index | post | 2 / 5 |
  | `jj op log -n50` (snapshot 포함) | post | 16 / 52 |
  | baseline 파일 삭제 | post | 2 / 2 |
  | index가 바뀌었을 때: 사본 + `jj diff` | post | 17 / 16 |
  | 내용이 바뀐 파일도 있을 때: `ls-files` ×2 | post | 11 / 12 |

  - Bash 호출 1회에 작은 repo는 약 45ms, 30,000 파일 repo는 약 90ms가 든다. 남은 비용은 대부분 jj 프로세스 2개와, 파일 수에 비례하는 post snapshot이다.
  - snapshot 비용은 history나 용량이 아니라 working copy의 파일 수에 따라 달라진다. jj는 모든 파일의 stat을 확인하고 `tree_state`(30,000 파일에서 777KB)를 읽고 쓴다. 파일이 실제로 바뀐 snapshot은 약 50ms가 더 든다.
  - watchman(jj 0.46의 키는 `fsmonitor.backend = "watchman"`)을 켜면 30,000 파일 repo에서 snapshot이 57ms에서 158ms로 오히려 느려졌다. 그래서 권장하지 않는다. 원인은 확인하지 못했다(테스트 repo가 `/private/tmp` 아래였다).
  - 최적화 전에는 고정 비용이 컸다. PATH의 MacPorts bash가 시작에만 15ms(`/bin/bash`는 3ms), jq를 필드마다 띄우는 데 약 10ms씩, `dirname` 루프, hook마다 jj 프로세스 2개가 들었다.
- `git clean`: jj가 snapshot한 파일은 git index에 내용 없는 entry로 올라가 있다. 그래서 `git clean -fd`는 이 파일들을 지우지 않는다(구현 중 실험으로 확인했다). 지워지는 것은 snapshot 뒤 같은 명령 안에서 새로 만든 파일, 그리고 `-x`로 지정한 ignored 파일뿐이다. 앞의 것은 명령의 의도이고, 뒤의 것은 jj도 추적하지 않는다.
- `jj op restore`는 그 명령이 한 정상적인 변경도 함께 되돌린다. 그래서 agent에게 먼저 확인하라고 안내한다.

**이 방식을 고른 이유:** PreToolUse 차단은 명령 문자열을 heuristic으로 파싱해야 하고, 그래도 스크립트 안의 git은 놓친다. 명령을 고쳐 쓰는 방식은 승인 규칙과 화면 표시에 영향을 준다. 감지는 실제 상태 변화를 근거로 삼는다. 그래서 스크립트가 HEAD를 바꾼 경우까지 잡고, 명령에는 손대지 않는다. 손실 범위는 jj의 per-step snapshot이 이미 좁혀 두었다.

### 3. 설치 경로

| 소비자 | 명령 | 동작 |
|---|---|---|
| Claude Code (plugin) | `claude plugin marketplace add <repo>` → `claude plugin install jj-agent@yejun-jj` | 지금과 같다. `${CLAUDE_PLUGIN_ROOT}` 기준으로 동작한다 |
| Claude Code (APM) | `apm install <owner>/<repo>/plugins/jj-agent` | `.claude/settings.json`과 `.claude/hooks/jj-agent/`에 설치된다 |
| Codex (APM) | 위와 같은 명령 | `.codex/hooks.json`, `.codex/hooks/jj-agent/`, `.agents/skills/`에 설치된다. Codex의 `/hooks`에서 trust가 필요하다 |
| Codex (plugin) | `codex plugin marketplace add hyperthreading/jj-agent-plugins` → `codex plugin add jj-agent@yejun-jj` | Codex가 `.claude-plugin/marketplace.json`과 plugin 폴더를 그대로 읽는다. hooks와 skill이 모두 동작하고, 격리된 `CODEX_HOME`에서 `codex exec`로 확인했다. plugin hook도 `/hooks`에서 trust해야 한다 |

`session-start.sh`의 shim 경로는 `CLAUDE_PLUGIN_ROOT`에 의존하지 않고 `$(dirname "$0")/shim`으로 찾는다. 그러면 plugin 설치와 APM 설치 모두에서 shim을 찾을 수 있다.

### 4. 지금 하지 않는 것

- Gemini, Copilot, Cursor adapter. 필요해지면 그때 별도 package(`target:` 지정)로 만든다.
- Codex 전용 marketplace 출력(`.agents/plugins/marketplace.json`). Codex 0.159가 `.claude-plugin/marketplace.json`을 그대로 읽어서 필요 없다.

## Consequences

- Claude plugin 사용자 경험은 그대로다. 달라지는 점은 shim 위치와, git 개입 감지 알림이 추가되는 것뿐이다.
- Codex에서는 skill, snapshot, 알림, git 개입 감지·복구 안내가 동작한다. git을 미리 막지는 못한다.
- 소스는 plugin 하나다. version은 `apm.yml` 하나를 기준으로 삼는다.
- APM project scope로 설치하면 Codex hook command가 repo 기준 상대 경로가 된다(`.codex/hooks/...`). Codex를 하위 디렉터리에서 시작하면 hook을 찾지 못할 수 있다. APM의 동작이므로 README에 적어 둔다.

## Open questions

1. ~~Codex marketplace 출력을 켤 것인가?~~ 필요 없다. Codex가 Claude 형식의 marketplace와 plugin을 읽는다(위 설치 경로 표 참고).
2. 원격 저장소에 publish할 계획: `tagPattern`과 jj bookmark/tag 운영 방식.

