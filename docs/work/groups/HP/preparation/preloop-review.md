# HP loop 전 명세 검토 — 2026-10-15

범위: HP02~06 intent/spec/plan 15문서, 공통 계약·승인 입력·실행 검증 설정. 제품 구현 리뷰나 실제 실험 결과가 아니다. 독립 리뷰: `/root/hp_preloop_spec_review`, `gpt-5.6-sol/high`, 새 컨텍스트·읽기 전용. 원본 입력은 [source-baseline.preloop.json](source-baseline.preloop.json).

## 1차 리뷰와 반영

| 지적 | 반영 |
|---|---|
| HP02 delivered_scope 배열→strict project.scope 문자열 불명확 | 승인 순서 `; ` join, self pointer/전체quote 고정 |
| HP03 기존 승인 입력과 신규 입력/preview 관계 불명확 | CompanyAnalysisInput v2 + hp_analysis 중첩, 전체 키/preview union/전체hash/provenance 고정 |
| HP03 권한·정책·runner·권위문서 경로 누락 | plan에 runtime-privileges·identity/loader·runner·DTO·DB/REST/운영문서와 관련검사 추가 |
| HP05 실험파일·요구concept·자원경계/완료 게이트 불명확 | exact wire·동일10건 concept·기대/필수경로·두엔진/사람평가·secret/internalnetwork/cleanup, real_data_run 필수 적용 |
| HP06 gold 조건ID/모델 unitID 혼합 및 actual/provenance 부족 | raw actual·사람 alignment·scorer prediction·receipt 분리, 상태/품질/정책/source검증·Git 밖 저장 |
| plan 복사 잔재 | 기능별 proof 범위 교정, HP04 구현 REST 문서 경로 추가 |

1차 지적은 전부 수용했다. 사람 정답·기대경로·최종인수는 실제 해당 단계 전 입력이며 문서 작성 단계에서 대행하지 않는다. 수정 부분 재검토 1회만 요청했다.

## 리더 문서 검사

- doctor: 13 features, schema2, tool0.6.0. 5개 check-plan 통과,18 STEP 연결.
- v2 scenario/basis/ontology/selection/worksheet bytes SHA와 동결 manifest 일치. 10문서 정답 null 보존, written_before_model_output=false 유지.
- JSON 파싱,15개 intent/spec/plan 상대 링크, source-baseline 입력 hash, git diff --check 통과.
- 이번 작업은 문서/워크플로 준비다. 제품 테스트·앱 빌드·배포·실제 모델·Neo4j 실행 없음. 기존23개 준비 도구 검사와 실제 제품 검증을 새로 실행했다고 기록하지 않는다.

## HP00·01 기존 증거의 적용 범위

완료 기준 commit `95d361d` 이후 current working tree의 tracked diff 및 untracked 파일은 docs/와 CHANGELOG에만 있다. `git diff --exit-code 95d361d -- web scripts docker-compose.yml docker-compose.edge.yml docker-compose.model-egress.yml run-tests.sh` exit0. HP00·01 intent/spec/plan과 제품 코드는 그대로다.

[기존 최종 독립 리뷰](../../../_runs/hp0001-20261014/final-batch-review.md)·[최종 검증](../../../_runs/hp0001-20261014/hp0001-final-validation.md)은 해당 최종 제품 소스의 증거다. 333 backend·31 browser·build 통과, MinIO fixture1 skip, 실제 모델 근거검증 실패, 쪽 unavailable/미처리 backfill 한계를 그대로 유지한다.

공통 constitution/feature.json과 ADR/findings 문서 변경이 전체 snapshot hash를 바꾸어 CLI에 stale로 보였다. 독립 리뷰는 제품 소스 동일성과 범위 대조에 따라 기존 증거 재사용·현재 hash 재결속 가능, 제품 검사 추가 불필요로 판단했다. 문서 수정 완료 후 proof CLI로 이 대조 기록과 원본 증거를 연결한다. 이것은 새 제품 테스트 통과나 실제 모델 성공 선언이 아니다. 기존 proof는 tool의 proof_history에 보존하고 과거 integration 기록은 변경하지 않는다.

## 재검토 결과

**PASS / 차단0**. 동일 독립 reviewer가 수정 차이1회를 대조해 기존6개 지적 모두 해소·새 구현 차단 없음으로 판정했다. 추가 검사 요구 없음. 사람 gold/기대경로/실제비교/최종인수는 수동 게이트로 유지한다. 읽기 전용 검토이며 파일 변경·제품 테스트·외부 호출을 하지 않았다.

## 최종 워크플로 확인

HP00·01 proof는 CLI로 원본 증거/범위 대조를 현재 hash에 재결속했고 check 통과, 큐 done으로 확인했다. HP02~06은 CLI로 review/18개 pending STEP·의존 순서에 등록했다. doctor13features 통과, active run 없음(`{}`). 새 제품 proof는 pending이며 문서 검토를 제품 검증으로 기록하지 않았다. 수동 commit 정책에 따라 변경은 미커밋이고 loop는 시작하지 않았다.
