# 로컬 개발 준비와 Luna 게이트 이관 — intent

- 기능 ID: `DEMO-00-luna-preflight`
- 상위 항목: [DEMO 로드맵](../../../../constitution/roadmap.md) — 2026-10-06 재계획으로 큐 맨 앞에 추가
- 크기: M — 완료한 Luna v4 구현 이력 보존, LiteLLM transport·불변 개요 정책·target 문서 worker 변경, 로컬 실제 증거 판정, 후속 Luna 인수 게이트 이관. REST/DB schema 변경 없음.
- 작성일: 2026-10-06

## 문제

실제 Luna 심층검토는 지금까지 완성 보고서를 한 번도 만들지 못했다([status](../../../../../tracking/status.md)).
운영 1489번에서 v1은 `narrative:claim_relation_out_of_slice`, v2는 `narrative:considered_claim_out_of_slice`,
검증을 끈 v3도 19 slice 중 10번째에서 `validation:dangling_evidence`로 멈췄다(53분 41초).
DEMO 목표인 보고서 9건(최소 3건)은 v2 수준의 엄격 검증에 그래프 입력까지 더하므로 실제 Luna 심층 성공은 여전히 검증해야 한다.
다만 2026-10-09 현재 `bidops-local`에 실제 3일 수집 자료, 문서 준비 경로와 LiteLLM 개요 실행 증거가 생겨 운영 1489 적용을 DEMO-01 착수의 선행조건으로 둘 필요는 없다.

## 기대 결과

기존 STEP-001/002의 Luna v4 원인 분류·구현·회귀 이력을 보존한다.
2026-10-06~08 실제 수집, notice 179 문서 준비와 승인된 물리 4쪽 LiteLLM 개요 결과를 로컬 개발 준비 증거로 판정하고 DEMO-01 착수 여부를 기록한다.
운영 1489와 실제 Luna 심층 성공은 완료로 바꾸지 않고 DEMO-03/05의 실제 모델 인수 게이트로 넘긴다. 검증 기준은 낮추지 않는다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| 실패 원인 분류 | v1~v3 원응답·검증 기록 읽기 | 각 실패가 프롬프트/입력 계약/검증기 결함 중 무엇인지 근거 위치와 함께 기록 |
| v4 정책 등록 | `python -m app.deep_review.cli import-profile-policy --policy … --expected-policy-sha256 …`(0922 apply 관례) | 승인본 매핑과 sha256 일치, 기존 v1~v3 행 불변 |
| 로컬 준비 대조 | 3일 수집·문서·LiteLLM 실행 증거와 현재 source hash 확인 | 실제 corpus·notice 179 물리 4쪽·2 calls·8개 인용·두 viewport·자동화 off 확인 |
| 게이트 이관 | DEMO-03/05 spec·plan 대조 | 실제 Luna 대표 1건과 3사/목표 9건 인수가 후속 필수 게이트로 남음 |
| 진행 판정 | 로컬 준비와 남은 한계를 기록 | DEMO-01 착수 가능, `unmeasured_reference`·PDF 5쪽 불일치·운영 1489 미실행 보존 |

## 선행·후속 기능

- 선행: 없음
- 후속: DEMO-01-company-context (queue.json depends_on과 같다)

## 영향 범위

- 모듈·컴포넌트: 기존 Luna v4 정책·검증 코드, `core/model_client.py` LiteLLM dialect, 별도 개요 정책, attachment worker의 bounded `--notice-id`
- 큰 틀 문서의 절: [ADR-0069](../../../../../tracking/decisions/0069-user-requested-luna-deep-review.md), [ADR-0070 2026-10-09 개정](../../../../../tracking/decisions/0070-multi-company-knowledge-demo.md), [DEMO 공통 계약](../../../../demo-contract.md)
- 데이터·저장소: 기존 v4 제품 변경과 `bidops-local` 실제 수집·문서·개요 증거. 이번 재계획에서 DB를 변경하지 않음
- 외부 서비스·호출: 이번 재계획에는 새 호출 없음. 이후 Luna 심층은 DEMO-03/05에서 별도 미리보기·건별 승인

## 제약

- (공통) [feature.json](../../../../feature.json) constraints와 [source-baseline](../../../../source-baseline.json)을 따른다.
- (기능별) 이 run은 main 통합 대상이지만 운영 배포·정책 import·활성화·실제 Luna 전송은 하지 않는다. DEMO-01~05 코드를 포함하지 않는다.
- LiteLLM 개요 참조 결과를 Luna 심층 품질 증거나 운영 활성화 근거로 쓰지 않는다.
- 실패하면 원응답과 상태를 보존하고 자동 재호출하지 않는다. 같은 정책으로 다시 돌릴지는 사용자가 정한다.

## 범위 밖

회사 문맥·그래프 입력·demo 정책(DEMO-03), 다회사 인수(DEMO-05), 운영 배포·1489 실행.
실제 Luna 대표 보고서는 DEMO-03, 3사·전체 인수는 DEMO-05가 소유한다.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 선행 준비 | 2026-10-06: 운영 1489 선검증 | 2026-10-09: 로컬 corpus·문서·LiteLLM 개요 준비 완료 | DEMO-01은 로컬 준비를 선행조건으로 착수 |
| Luna 실제 검증 | DEMO-00 운영 1489 | 회사·graph 경로 완성 전 단일회사 증거 | DEMO-03 대표 1건과 DEMO-05 인수로 이관, 삭제하거나 완료 처리하지 않음 |
