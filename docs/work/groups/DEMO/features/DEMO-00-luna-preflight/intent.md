# Luna v4 정책 선검증 — intent

- 기능 ID: `DEMO-00-luna-preflight`
- 상위 항목: [DEMO 로드맵](../../../../constitution/roadmap.md) — 2026-10-06 재계획으로 큐 맨 앞에 추가
- 크기: M — 새 불변 정책 1개와 승인 경로 매핑, 운영 배포 1회, 실제 Luna 1건. 새 공개 계약 없음.
- 작성일: 2026-10-06

## 문제

실제 Luna 심층검토는 지금까지 완성 보고서를 한 번도 만들지 못했다([status](../../../../../tracking/status.md)).
운영 1489번에서 v1은 `narrative:claim_relation_out_of_slice`, v2는 `narrative:considered_claim_out_of_slice`,
검증을 끈 v3도 19 slice 중 10번째에서 `validation:dangling_evidence`로 멈췄다(53분 41초).
DEMO 목표인 보고서 9건(최소 3건)은 v2 수준의 엄격 검증에 그래프 입력까지 더하므로, 실현 가능성을 DEMO-01 착수 전에 확인해야 한다.

## 기대 결과

기존 단일회사(company_id NULL) Luna 경로에서 새 `analysis-policy-luna-v4`로 1489번 실제 1건을 실행하고,
완성 보고서 여부·실패 코드·slice별 소요 시간을 기록한다. 그 결과로 DEMO-01~05를 그대로 진행할지 사용자가 결정한다.
그래프·회사 입력은 넣지 않는다. 검증을 끄거나 낮춰서 통과시키지 않는다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| 실패 원인 분류 | v1~v3 원응답·검증 기록 읽기 | 각 실패가 프롬프트/입력 계약/검증기 결함 중 무엇인지 근거 위치와 함께 기록 |
| v4 정책 등록 | `python -m app.deep_review.cli import-profile-policy --policy … --expected-policy-sha256 …`(0922 apply 관례) | 승인본 매핑과 sha256 일치, 기존 v1~v3 행 불변 |
| 실제 1건 실행 | 사전규격 1489 상세 → 전송 미리보기 → 사용자 승인 | attempt 종료 상태·검증 결과·slice 수·소요 시간 기록, 자동 재호출 없음 |
| 진행 판정 | 결과 기록 후 사용자 결정 | 통과/실패와 다음 행동(DEMO-01 착수 또는 범위 재결정)이 기록됨 |

## 선행·후속 기능

- 선행: 없음
- 후속: DEMO-01-company-context (queue.json depends_on과 같다)

## 영향 범위

- 모듈·컴포넌트: deep_review 정책 파일·승인 경로 매핑(`services/input_versions.py`), 원인에 따라 narrative 입력·검증 코드
- 큰 틀 문서의 절: [ADR-0069](../../../../../tracking/decisions/0069-user-requested-luna-deep-review.md)·[0922 Luna 계획](../../../../../0922_luna-deep-review/plan.md), [operations](../../../../../operations.md) 배포 절차, [ADR-0070 개정](../../../../../tracking/decisions/0070-multi-company-knowledge-demo.md)
- 데이터·저장소: 운영 DB의 AnalysisPolicyVersion 새 행 1개(append-only), 1489 DeepReview attempt 1개
- 외부 서비스·호출: codex-exec Luna/xhigh 1회(실제 회사 프로필 포함, ADR-0069 승인 경로). 실행 직전 사람 확인

## 제약

- (공통) [feature.json](../../../../feature.json) constraints와 [source-baseline](../../../../source-baseline.json)을 따른다.
- (기능별) 이 기능만 main 브랜치·운영 배포 대상이다. DEMO-01~05 코드를 포함하지 않는다.
- 운영 배포·정책 import·활성 정책 env 교체·Luna 신규 요청 토글·실제 전송은 각 단계 직전 사람 확인을 받는다. 앞 단계 승인은 다음 단계로 이어지지 않는다.
- 배포 전 전체 백업과 `before-luna-v4-<날짜>` 롤백 태그를 남긴다. migration은 없다.
- 실패하면 원응답과 상태를 보존하고 자동 재호출하지 않는다. 같은 정책으로 다시 돌릴지는 사용자가 정한다.

## 범위 밖

회사 문맥·그래프 입력·demo 정책(DEMO-03), 격리 데모 환경(DEMO-05), runner·호출당 timeout(900초) 변경.
2026-10-07 결정으로 검토 전체 마감은 정책 값(v4 5시간)을 읽게 바꾸고 slice 1회 교정 재요청을 추가한다(spec).

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 선검증 위치 | 공통 계약: DEMO-01~05 데모 브랜치 전용 | 운영 1489 선검증은 새 정책 이미지 배포 필요 | 2026-10-06 사용자: Luna v4로 main 소규모 반영·운영 배포 |
| 실행 순서 | 기존 계획: 첫 실제 실행은 DEMO-05 | 재계획: DEMO-01 착수 전 | 사용자: 먼저 확인 |
