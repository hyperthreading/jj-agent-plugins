# ADR 0006: 작업 의도로 기반을 고르고 보존을 별도 판정

- Status: Accepted
- Date: 2026-11-06

사용자가 작업 보존의 의미를 명확히 했다. 독립 작업은 main/trunk 같은 의도한 기반에서 새로 시작하고, 이어 하라는 요청은 기존 작업에서 계속한다. 현재 workspace의 파일 내용이 바뀌었다는 이유만으로 보존 실패로 판정하면 정상적인 `jj new <base>`도 실패하므로, 작업 보존과 작업 배치를 따로 판정한다.

## 지침과 판정

공통 task flow와 standalone skill에 다음 기준을 적용한다. 용어는 [GLOSSARY.md](../../GLOSSARY.md)에 정리했다.

- 이어 하기는 기존 change에서 완료한다. 새 메시지가 왔다는 이유만으로 change를 나누지 않는다.
- 독립 작업은 요청한 기반이나 저장소의 main/trunk에서 시작한다. 기존 작업에 의존하는 새 작업만 그 위에 쌓는다.
- 빈 `@`는 의도한 기반 위에 있고 자식이 없을 때 재사용한다. 다른 초안 위의 빈 `@`도 그 초안에 의존한다.
- 요청 범위 밖의 change 내용·설명·부모 관계와 bookmark를 보존한다. 사용자가 작업 폴더 유지까지 요청했으면 그 workspace를 이동하지 않는다.

새로 준비하는 run은 `grading_contract: 2`를 저장한다. fixture의 `task.mode`와 기반 또는 대상 change를 baseline에 고정해, 새 작업의 부모와 이어 할 change의 동일성을 검사한다. 요청 외 파일 변경도 검사한다. `branch-alone`은 `keep_workspace: true`로 원래 workspace 유지 조건을 명시한다.

실행 중 monitor는 snapshot에 기록된 보호 change와 bookmark를 검사한다. checkout 도중의 파일 view를 비교하면 정상 이동도 유실로 오인할 수 있으므로, 아직 snapshot되지 않은 손상은 client turn 종료 뒤 `eval turn validation` snapshot으로 확인한다. 따라서 기록 전 손상을 실행 중 즉시 검출한다고 주장하지 않는다. 이 검증용 snapshot은 평가기의 동작이며 배포 runtime의 L3 기본값과 별개다.

## 중단된 캠페인의 해석

원래 turn 3 요청은 "finish this unrelated task in its own described version-control change"였다. 이 요청에 `jj new main`으로 응한 선택은 적절했다. 앞서 assistant가 기존 draft 위에서 이어 갔어야 한다고 설명한 것은 프롬프트를 잘못 해석한 것이다. `user-wip`의 tree·설명·부모·bookmark·파일 내용은 보존됐고, 중단은 현재 workspace의 파일 내용까지 같아야 한다던 종전 조건 때문에 발생했다.

2026-11-05 실행에는 버전 필드가 없으므로 판정기는 계약 1을 적용한다. 원래 `unknown`, 관측된 실패, 원시 증거와 ledger의 중단 기록을 유지한다. 새 기준의 회귀 검사가 통과해도 중단된 모델 실행을 통과로 바꾸지는 않는다. [ADR 0005](0005-budgeted-guidance-validation.md)의 보존 범위 질문은 이 결정으로 해결됐으며, 캠페인 재개에는 여전히 새 사용자 지시가 필요하다.

계약 2의 독립 작업 프롬프트에는 main을 명시했다. 새 `continue-task` fixture는 모델 없는 판정기 검증에 사용하며, 승인된 여섯 case × 다섯 arm 일정에는 추가하지 않았다. 이 지침·판정기 revision의 실제 client 행동 증거는 아직 없다.
