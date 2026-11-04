# ADR 0005: 예산 제한 검증을 보존 조건에서 중단

- Status: Accepted for the recorded campaign; runtime acceptance incomplete
- Date: 2026-11-05

실제 client 설치·전달과 최소 행동을 격리 환경에서 검사한 뒤 OpenCode의 다섯 전달 방식을 비교하기로 했다. 사용자 승인은 총 $30/90분, run별 $1/3분/모델 요청 30회였으며, 사용자 작업 보존 조건 위반 시 즉시 중단한다. 구독 연결은 실제 달러 청구액을 제공하지 않으므로, 사용자가 승인한 API 환산 사용량을 요청 전 예약하고 사용량 누락 시 예약을 유지하며 중단하는 방식을 택했다.

## 결과와 결정

OpenCode·Codex의 `basic`, `dirty-wc`, `multi-turn-external`과 Claude의 `basic`, `dirty-wc`가 통과했다. Claude의 외부 변경 case에서 `jj new main` 뒤 현재 workspace의 `user.txt`가 baseline과 달라져 중단했다. `user-wip` change의 tree·설명·부모·bookmark와 사용자 파일 내용은 보존돼 있다. 최신 상태도 요청에 전달됐으므로 L1 전달 누락으로 설명할 수 없다.

원래 판정은 **중단된 실행의 `unknown`과 관측된 보존 조건 실패**로 남긴다. 역사에 사용자 change가 남아 있다는 이유로 기존 workspace-content 계약을 사후 변경하거나 통과로 재분류하지 않는다. 사용자가 보존 범위를 결정하고 재실행을 지시하기 전에는 ledger를 초기화하거나 모델 호출을 추가하지 않는다.

최초의 환경·관측 문제를 포함한 비용은 **12회 유료 시도, 전달 요청 69개, API 환산 $2.182575, 미정산 예약 $0**이다. 세 client의 Git `control`과 30-run pilot은 실행하지 않았다. 따라서 비교 결론은 **판단 보류**, C1–C7 전체 수용은 **미완료**다. 이 결과는 배포나 실사용 채택을 승인하지 않는다.

## 다음 검증의 전제

1. 같은 workspace에 사용자 파일 내용이 남아야 하는지, 보호된 change/bookmark를 보존한 채 다른 기반으로 이동해도 되는지 결정한다. 계약을 바꾸면 기존 결과와 새 판정을 구별한다.
2. Claude packaged skill의 독립 설정을 해결하고, 실제 workspace 전환·clear·turn 도중 compaction과 남은 skill 본문 선택을 확인한다.
3. 새 실행 승인을 받은 뒤 중단 case와 세 Git control을 검증한다. 필수 기준 충족 후에만 고정한 다섯 arm 비교로 진행한다.

설치 경로, 설정 capture, 시도별 결과·토큰·시간·비용, 원시 증거 hash는 [캠페인 기록](../../evals/results/2026-11-05/README.md)에 있다. 검사 방법과 관측 한계는 [evals/README.md](../../evals/README.md), 기준별 미완료 항목은 [VERIFICATION.md](../VERIFICATION.md)에 기록했다.
