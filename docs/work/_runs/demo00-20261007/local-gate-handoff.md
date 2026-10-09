# DEMO-00 STEP-004 Luna 게이트 이관

- 판정일: 2026-10-09
- 범위: 문서 계약 대조와 진행 판정. 제품 검사·모델 호출·상태 변경은 수행하지 않았다.

## 근거와 이관

- [로컬 준비 증거](./local-readiness-evidence.md)는 2026-10-06~08 수집 자료와 notice 179의 준비를 기록한다. LiteLLM 개요는 물리 4쪽, 2 calls, 8개 claim의 인용·offset 검증 성공이며 `unmeasured_reference`와 경고 4종을 유지한다. 이는 Luna 심층 품질 증거가 아니다. PDF 물리 5쪽의 text/display 불일치와 80쪽 전체 시각 검증 미수행도 미해결이다. 기존 source hash가 일치해 모델 검사 231건·문서 검사 155건을 재사용한 기록이며, 이번 문서 작업에서 재실행한 결과가 아니다.
- 운영 notice 1489는 미실행으로 남긴다. 기존 실패도 완료나 성공으로 바꾸지 않는다: v1 `narrative:claim_relation_out_of_slice`, v2 `narrative:considered_claim_out_of_slice`, 검증을 끈 v3 `validation:dangling_evidence`(19 slice 중 10번째, 53분 41초). 근거는 [DEMO-00 intent](../../groups/DEMO/features/DEMO-00-luna-preflight/intent.md)와 [spec](../../groups/DEMO/features/DEMO-00-luna-preflight/spec.md)이다.
- 실제 Luna 대표 1건은 [DEMO-03 T9](../../groups/DEMO/features/DEMO-03-grounded-analysis/spec.md)와 [STEP-007](../../groups/DEMO/features/DEMO-03-grounded-analysis/plan.md)에 필수 게이트로 남는다. 동결 provenance, 별도 미리보기, 건별 승인, Luna `codex-exec`, 3단계 completed 보고서와 결정적 검증, 원문 근거 확인이 필요하다. LiteLLM 개요·핏 결과를 여기에 합산하지 않는다.
- [DEMO-05 spec/plan](../../groups/DEMO/features/DEMO-05-demo-acceptance/spec.md)은 6건을 동결한 뒤 LiteLLM 핏 18건을 요구한다. 최소 `demo_ready`는 첫 대표 공고 3사 Luna 보고서 완료·인수(핏 18건 포함), 목표는 Luna 보고서 9건과 9건 모두 `accepted=true`인 전체 인수다. 최소 달성을 9건 완료로 표시하지 않는다.
- 자동 개요·회사 핏·심층 시작은 false를 유지하고, 이 문서는 새 모델 전송이나 재요청을 승인하지 않는다. 실제 전송은 각 단계 직전에 건별 사람 승인을 받아야 한다([DEMO 공통 계약 §10](../../demo-contract.md)).

## 진행 판정

로컬 준비는 DEMO-01 착수 근거로 충분하며 운영 1489 실행을 선행조건으로 두지 않는다. 큐는 DEMO-01 → 02 → 03 → 04 → 05의 직접 의존을 유지하고 DEMO-01은 DEMO-00에 의존한다([queue.json](../../queue.json)). DEMO-00 수동 main 통합 후 DEMO-01~05는 그 main에서 분기한 별도 데모 브랜치와 `bidops-local` 격리 자원에서 진행한다. 각 기능을 main에 반영하기 전 기존 ID 직접 조회·수정·재시도 경로의 회사 경계 격리 점검을 끝내야 하며, 운영 전환은 별도 승인 작업이다([feature.json](../../feature.json), [공통 계약 §1](../../demo-contract.md)).

요청된 문서들 사이에서 Luna 게이트, 18/3/9 인수 기준, 자동 실행 경계, 큐 순서의 불일치는 발견하지 못했다. 문서 대조상 진행 가능 판정이며 기능 상태 완료를 뜻하지 않는다. 독립 리뷰와 리더의 통합 판정은 남아 있다.
