# HP-04 — plan

- 기능 ID: `HP-04-practitioner-verdict`
- 근거: intent.md, spec.md. 작성일2026-10-15. 구현 시작 전 문서다.

## 변경 파일

| 경로 | 구분 | 내용 |
|---|---|---|
| `web/backend/app/deep_review/routers/company_reads.py` | 수정/재사용 | spec 요구사항 구현·검증 |
| `web/backend/app/deep_review/services/hp_verdict_view.py` | 신규 | spec 요구사항 구현·검증 |
| `web/backend/app/deep_review/schemas/hp_verdict_view.py` | 신규 | spec 요구사항 구현·검증 |
| `web/frontend/src/lib/companyApi.ts` | 수정/재사용 | spec 요구사항 구현·검증 |
| `web/frontend/src/pages/CompanyPreSpecsPage.tsx` | 수정/재사용 | spec 요구사항 구현·검증 |
| `web/frontend/src/components/HpVerdict.tsx` | 신규 | spec 요구사항 구현·검증 |
| `web/backend/tests/app/test_hp_verdict.py` | 신규 | spec 요구사항 구현·검증 |
| `web/frontend/tests/hp-verdict.spec.ts` | 신규 | spec 요구사항 구현·검증 |

| `docs/contracts.md` | 수정 | 구현된 verdict REST shape·상태·오류 계약 |

## 작업 순서

1. STEP-001 읽기 API·현재성 투영 [complex]
   - 목표: 정확 응답 shape와 회사 fence.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T1,T2; 결과/명령/종료코드는 실행 run 폴더에 저장.

2. STEP-002 판정 다섯 블록 연결 [complex]
   - 목표: 타입·테마·정보 구조·근거/쪽.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T3,T4; 결과/명령/종료코드는 실행 run 폴더에 저장.

3. STEP-003 상태·오류·실제 조회 검증 [complex]
   - 목표: mock 실패표현과 실제 API 연결 분리.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T5,T6; 결과/명령/종료코드는 실행 run 폴더에 저장.

## 위임

모든 단계 complex(gpt-5.6-sol/high): 불변 입력·상태·근거·사람 판단 경계를 검사한다. 구현자는 단계 하나만, 리더가 관련 검사를 실행하며 독립 리뷰는 같은 소스·결과를 읽는다. 테스트 ID는 spec 표이며 위 단계가 전부 배정한다.

## 증명

- docs: `python3 scripts/feature_status.py doctor _`, `check-plan HP-04-practitioner-verdict`와 intent 유즈케이스별 실제 증거 대조.
- tests: `cd web/backend && python -m pytest tests/app/test_hp_verdict.py -q`. 새 검사 파일은 loop에서 구현하며 현재 존재/통과한다고 주장하지 않는다.
- postgres: 임시 PostgreSQL17.11 및 BIDOPS_TEST_POSTGRES_URL로 위 관련 backend 파일의 PostgreSQL 변형 실행.
- frontend: `cd web/frontend && npm run build`; 관련 hp-verdict.spec.ts 의미·1280/1440 구조 검사. 실제 결과 조회 T6는 별도.
- api_guard: 위 backend 관련 API/CLI 검사에서 타회사·404/409/422/503·비밀비노출·입력fence. HP02는 기존 shape 재사용도 확인.
- real_data_run: 설정상 N/A. HP02 실제 격리등록, HP04 실제조회, HP05 실제비교는 해당 T 사례와 tests 증거에서 별도 충족해야 한다.

## 위험과 종료 경계

| 위험 | 징후 | 대응 |
|---|---|---|
| 확정 설정을 실제 기능/품질로 오인 | 준비파일만 있고 실제 증거 없음 | 필수검증을 pending 유지 |
| 원문/회사/정책 기준 혼합 | hash·ID·버전 불일치 | fail closed, 새 버전·새 attempt |
| 미확인을 false/충족으로 변경 | 조건 일부만 맞는데 met | spec 경계 검사, unknown 보존 |
| 사용자 참여 대기 | 사람 경로/gold/인수 없음 | 독립 가능한 단계만 진행, 답 대행 금지 |

실행 전에 필요한 검사 범위를 한 번 정하고 통과 후 동일검사를 반복하지 않는다. 실제환경 적용은 사용자 승인 범위 내 demo/local-20261009·bidops-local만. 전체스위트/전수재빌드는 공통 회귀 근거 없으면 실행하지 않는다. 수동 commit/merge 정책을 유지하며 origin push·브랜치 삭제 없음.

## 결과

아직 구현·실제 기능 검증하지 않았다. loop가 실행 결과를 이 절에 기록한다.
