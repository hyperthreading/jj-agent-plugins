# jj-agent hook latency benchmark

agent의 tool call 하나에 jj-agent hook이 더하는 시간을 기록한다. 측정 대상 코드는 jj-agent 0.3.1(commit `fe333b576bd3`)이고, 측정일은 2026-10-10이다.

## 측정 환경

| 항목 | 값 |
|---|---|
| 기기 | Apple M3 Max, 16 core, 48 GB |
| OS | macOS 26.6.2 (25G83), arm64 |
| filesystem | APFS. 측정용 repo는 `$TMPDIR`(`/var/folders/...`) 아래에 만든다 |
| jj | 0.46.0 (Homebrew, `/opt/homebrew/bin/jj`) |
| git | 2.47.1 (MacPorts, `/opt/local/bin/git`) |
| hook interpreter | `/bin/bash` 3.2.57. hooks.json이 `/bin/bash`를 먼저 쓴다 |
| PATH의 bash | MacPorts bash 5.2.37 (`/opt/local/bin/bash`). 비교용 |
| 시간 측정 | perl `Time::HiRes`. perl 시작 시간은 측정 구간 밖이다 |
| PATH | 설치된 jj-agent shim을 뺀 PATH. 스크립트가 직접 정리한다 |
| 부하 | load average 약 13(1분 평균), 7.5(15분 평균). Claude 데스크톱 앱과 headless Chromium이 함께 돌고 있었다 |

## 재현 방법

```bash
bash tests/hooks-bench.sh            # Bash 호출 1회의 hook 시간, repo 크기별 median (기본 15회)
bash tests/hooks-profile.sh          # 단계별 시간, median (기본 20회)
BENCH_SIZES="10 5000 30000" bash tests/hooks-bench.sh scripts-dir runs
```

- 두 스크립트 모두 임시 폴더에 repo를 만든다. 각 파일은 20줄이고 200개씩 하위 폴더에 나눠 둔다. `jj git init` 뒤 `jj commit`을 한 상태에서 측정한다.
- `tests/hooks-bench.sh`에 다른 버전의 `scripts` 폴더를 넘기면 그 버전을 측정한다.

## Bash 호출 1회 (0.3.1)

단위는 ms이고 median이다. 아래는 두 번째 실행 값이다. 첫 번째 실행은 부하가 튀어서 jj repo 밖의 pre가 11.6ms로 나왔는데, 이상치로 보고 맨 아래 "실행별 편차"에 따로 적었다.

| repo | pre | post | post+git | post(edit) | Bash 1회 합계 |
|---|---|---|---|---|---|
| jj repo 아님 | 3.1 | 3.2 | – | – | **6** |
| 10 files (index 0 KiB) | 23.0 | 28.1 | 45.6 | 53.5 | **51** |
| 5,000 files (index 351 KiB) | 22.5 | 36.0 | 51.4 | 61.7 | **59** |
| 30,000 files (index 2,265 KiB) | 22.9 | 68.0 | 73.7 | 99.0 | **91** |

열의 의미:
- **pre:** Bash 명령 전에 도는 PreToolUse. 마지막 op id 조회와 index 사본 만들기.
- **post:** 아무것도 바꾸지 않은 Bash 명령 뒤의 PostToolUse. 이 snapshot에서는 바뀐 파일이 없다.
- **post+git:** git이 파일 하나를 다시 쓴 명령 뒤의 PostToolUse. path 단위 비교가 돌고, 알림이 나간다.
- **post(edit):** Edit/Write 뒤의 PostToolUse. 파일이 실제로 바뀐 snapshot만 한다.
- **Bash 1회 합계:** pre + post. 파일을 바꾸는 명령이면 post가 post(edit) 수준으로 늘어난다.

## 단계별 시간 (0.3.1)

`tests/hooks-profile.sh`의 결과다. 단위는 ms이고 median이다. harness가 hook command를 `sh -c`로 띄우는 시간(3.8ms)은 빼고 적었다.

| 단계 | hook | 10 files | 30,000 files |
|---|---|---|---|
| `/bin/bash` 시작 | 둘 다 | 2.1 | 2.3 |
| lib.sh 로드, 입력 파싱, jj repo 탐색 | 둘 다 | 0.9 | 0.5 |
| `jj op log --ignore-working-copy -n1` | pre | 16.2 | 16.3 |
| index 사본 (`cp -c`) | pre | 2.3 | 2.2 |
| `cmp` index | post | 2.2 | 5.7 |
| `jj op log -n50` (snapshot 포함) | post | 18.5 | 54.1 |
| baseline 파일 삭제 | post | 2.4 | 2.4 |
| `jj util snapshot` (Edit/Write 뒤) | post | 12.2 | 44.7 |
| index가 바뀌었을 때: index 사본 | post | 2.5 | 2.6 |
| index가 바뀌었을 때: `jj diff --name-only` | post | 16.6 | 16.4 |
| 내용이 바뀐 파일도 있을 때: `git ls-files --debug` ×2 | post | 12.2 | 13.4 |

- 고정 비용은 jj 프로세스 시작(약 15ms)이 대부분이다. hook마다 하나씩 들어서 Bash 호출 1회에 두 번이다.
- 파일 수에 비례하는 건 post의 snapshot이다. 30,000 파일에서 약 35ms가 더 든다. jj는 모든 파일의 stat을 확인하고 `tree_state`(이 repo에서 777 KB)를 읽고 쓴다.

## 버전별 변화

Bash 호출 1회의 pre와 post를 ms로 적었다. 0.2.0에는 PreToolUse가 없다. 0.2.0과 첫 0.3.0은 PATH의 MacPorts bash로 측정했다. 당시에는 hooks.json이 `bash`를 썼기 때문이다.

| 버전 | jj repo 아님 | 10 files | 30,000 files | 주요 변화 |
|---|---|---|---|---|
| 0.2.0 | – / 84 | – / 68 | – / 105 | post에서 snapshot만 |
| 0.3.0 (`oknkkzzq`) | 46 / 96 | 91 / 110 | 131 / 150 | pre snapshot과 git 감지 추가. jq를 필드마다 호출, `dirname` 루프, hook마다 jj 2회 |
| 0.3.0 (`rxntylmr`, perf) | 3 / 3 | 26 / 29 | 64 / 72 | bash 내장 기능으로 파싱, hook마다 jj 1회, `/bin/bash` |
| 0.3.1 (`lullxlwy`, perf) | 3 / 3 | 23 / 28 | 23 / 68 | pre의 snapshot 제거(`--ignore-working-copy`) |

### 0.3.1 이후: Muse 보류와 감지 보완 (ADR 0002, 0003)

0.3.1과 새 버전을 번갈아 `tests/hooks-bench.sh`(파일 10개, 5,000개, 각 15회)로 두 번씩 쟀다. 측정 중 host load가 7~8로 높아서 위 표보다 값이 크다. 두 버전의 차이는 회차 간 흔들림(±3ms) 안이었다.

| repo | 0.3.1 pre / post | 새 버전 pre / post |
|---|---|---|
| 10 files | 25.9 / 31.7, 24.1 / 30.5 | 25.1 / 30.8, 27.1 / 33.7 |
| 5,000 files | 25.7 / 39.3, 26.6 / 39.4 | 24.8 / 38.2, 27.2 / 40.5 |

새로 생긴 경로는 따로 쟀다(파일 10개, median). 아래 값에는 측정용 wrapper가 프로세스를 띄우는 시간(빈 bash 스크립트 6.2ms)이 들어 있다.

| 경로 | 시간 |
|---|---|
| Claude Code·Codex의 Edit/Write PreToolUse (새로 hook이 걸림, 바로 끝남) | 7.2ms |
| Muse에서 보류 응답을 내는 PreToolUse | 13.4ms |
| stdout 30 KiB인 Bash 뒤의 PostToolUse (0.3.1 → 새 버전) | 33.5 → 32.5ms |

## 설계 판단에 쓴 측정

### 셸 시작

20회 평균이다. 아래 두 표는 측정 방식이 달라서 같은 항목도 값이 다르다.

| command | ms |
|---|---|
| `bash -c true` (PATH의 MacPorts bash 5) | 11.6 |
| `/usr/bin/env bash -c true` | 13.2 |
| `/bin/bash -c true` (bash 3.2) | 2.7 |
| `/bin/sh -c true` | 4.4 |

hook command를 실행하는 방식별 시간이다. harness의 `sh -c`(4.3ms)를 포함한 값이다.

| hook command | ms |
|---|---|
| `/bin/bash script.sh` | 6.4 |
| `bash script.sh` | 15.4 |
| `./script.sh` (`#!/bin/bash`) | 12.9 |
| `./script.sh` (`#!/usr/bin/env bash`) | 26.8 |

macOS에서는 스크립트를 직접 실행하면 interpreter로 읽힐 때보다 약 6ms가 더 든다. 출처 xattr이 붙은 파일을 실행할 때 하는 검사 때문으로 보인다(추정). 그래서 hooks.json은 `if [ -x /bin/bash ]; then /bin/bash X; else bash X; fi` 형태를 쓴다.

### 입력 파싱과 디렉터리 탐색

| 방식 | ms |
|---|---|
| 필드 하나를 `jq`로 읽기 (bash 안에서) | 약 10 |
| bash 정규식(`[[ =~ ]]`)으로 읽기 | 1 미만 |
| `dirname` 루프로 깊은 경로 탐색 | 약 22 |
| `${d%/*}` 루프 | 1 미만 |

### snapshot과 watchman (30,000 files)

| 경우 | 끔 | watchman 켬 (`fsmonitor.backend = "watchman"`) |
|---|---|---|
| snapshot 안 함 (`jj op log --ignore-working-copy`) | 22.1 | – |
| snapshot, 바뀐 파일 없음 | 57.0 | 158.3 |
| snapshot, 1개 파일 바뀜 | 106.2 | 217.1 |

watchman을 켜니 오히려 느렸다. 측정 repo가 `/private/tmp` 아래였고, 원인은 확인하지 못했다. jj 0.46에서 `core.fsmonitor` 키는 동작하지 않는다.

### `git ls-files` (30,000 files)

| 방식 | ms |
|---|---|
| `git ls-files --debug` 전체 | 32.9 |
| 전체 출력을 awk로 처리 | 102.5 |
| path 2개로 한정 | 17.3 |
| `git --version` (프로세스 시작만) | 15.7 |

이 결과로 git이 다시 쓴 파일을 찾을 때 `jj diff`로 내용이 바뀐 path를 먼저 구하고, 그 path에만 `ls-files`를 실행하게 바꿨다. 처음에는 index 전체를 비교했는데, `jj commit`처럼 평범한 명령에도 30,000 파일에서 약 430ms가 들었다.

## 실행별 편차

같은 코드(0.3.1)를 서로 다른 시점에 측정한 값이다. 단위는 ms이고, 칸마다 pre / post다.

| 실행 | 부하 (1분) | jj repo 아님 | 10 files | 5,000 files | 30,000 files |
|---|---|---|---|---|---|
| 개발 중 (10/10 00:50경) | 기록 안 함 | 2.7 / 2.9 | 20.4 / 25.4 | 20.6 / 34.6 | 21.4 / 69.8 |
| 1회차 (02:03) | 15.5 | 11.6 / 8.5 | 34.6 / 45.1 | 28.7 / 45.2 | 23.2 / 68.0 |
| 2회차 (위 표) | 13.0 | 3.1 / 3.2 | 23.0 / 28.1 | 22.5 / 36.0 | 22.9 / 68.0 |

부하가 높으면 짧은 구간(jj repo 밖, 작은 repo)이 크게 흔들린다. 30,000 files처럼 jj 작업이 대부분인 구간은 안정적이다.
