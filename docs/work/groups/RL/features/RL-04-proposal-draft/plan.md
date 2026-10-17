# 제안서 초안 — plan

- 기능 ID: `RL-04-proposal-draft`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-16 (2026-10-17 배치 B 인터뷰 D2·D3·D4·D9·D10·D11·D12 반영 — [batch-b-interview.md](../../batch-b-interview.md))

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/deep_review/policies/proposal-policy-luna-v1.json, contracts/bidops.proposal-section.v1.json, bidops.proposal-input.v1.json | 신규 | 정책·schema |
| web/codex-runner/runner.py(contract 집합·schema 분기), web/codex-runner/Dockerfile(COPY), web/backend/app/deep_review/services/luna_client.py(집합·120k 상한), contracts/__init__.py(SCHEMA_FILES), services/input_versions.py(identity map), luna_identity.py | 수정 | contract `proposal-section-v1` 5곳 + 정책 identity |
| web/backend/app/deep_review/models.py, alembic/versions/<head 다음>_proposal.py, scripts/runtime-privileges.sql | 수정/신규 | 테이블 4 |
| web/backend/app/deep_review/services/proposal_input.py, proposal_draft.py, proposal_validation.py, proposal_render.py | 신규 | 입력·생성·검증·PDF |
| web/backend/app/deep_review/services/proposal_worker.py, app/workers/proposal.py(또는 analysis worker에 job_type 추가), transfer_policy.py | 신규/수정 | WorkJob `proposal_section` 전용 run_once·승인 scope purposes(RL-03 `deep_reviews.py`는 손대지 않음) |
| web/backend/app/deep_review/routers/proposals.py, schemas/proposal.py, main.py | 신규/수정 | REST 8 |
| web/backend/requirements.txt, requirements.lock(reportlab·pillow·chardet hash), pyproject.toml | 수정 | `reportlab`, wheel hash는 PyPI에서 받아 고정(개발 의존성 취득용 네트워크만, 데이터 전송 아님). 폰트는 web/Dockerfile의 기존 fonts-nanum NanumGothic 사용, Dockerfile 변경·저장소 폰트 파일 추가 없음(D9) |
| web/backend/app/deep_review/__init__.py(`register_lifecycle_extensions`) | 수정 | 활동 hook `draft_prepared` 제공 |
| web/backend/tests/deep_review/test_proposal_validation.py, test_proposal_render.py, tests/app/test_proposal_api.py(+postgres), test_proposal_payload_guard.py, test_codex_runner.py | 신규/수정 | T1~T9 |
| web/frontend/src/pages/OpportunityProposalTab.tsx, components/proposal/{SectionTabs,SectionBody,SentenceEditor,RequirementLinks,ProposalStepper}.tsx, lib/api.ts, apiErrors.ts, tests/proposal.spec.ts, tests/api-mock.ts | 신규/수정 | T8 |
| docs/contracts.md, business-rules.md, operations.md, work/constitution/tech-stack.md("DOCX 중간 형식" 삭제·reportlab 추가·폰트 = 이미지의 NanumGothic, 폰트 파일 추가 없음), 1016_rootlab-redefinition/ui-spec.md, ADR.md, validation-runs README | 수정 | STEP-009 |

## 작업 순서

1. STEP-001 정책·schema·runner contract·의존 [complex]
   - 목표: 정책 identity(loader 필수 키·canonical bytes·행 import·선택 env)·문장 schema·contract 5곳·`reportlab` lock.
   - 작업 대상: 정책·contracts·runner·luna_client·input_versions·luna_identity·requirements(lock).
   - 검증: `test_codex_runner.py`, `test_requirements_lock.py`, `test_company_luna_policy.py`.
2. STEP-002 저장 테이블·권한 [standard]
   - 목표: 테이블 4·UNIQUE·권한 행렬(열 단위 GRANT·trigger, DELETE 없음)·`boundary_map`·`NEW_TABLES` 등록.
   - 작업 대상: models·migration·privileges.
   - 검증: `test_db_migrations.py`·`test_runtime_database_privileges.py`(PG).
3. STEP-003 입력 조립·payload 검사 [complex]
   - 목표: 절별 입력, confirmed만, missing_facts, 허용 키, 감사 purpose.
   - 작업 대상: proposal_input.py, transfer_policy.py scope.
   - 검증: T1, T9.
4. STEP-004 문장 검증·커버리지 [complex]
   - 목표: 출처·quote·placeholder·금지 내용·커버리지 검증기.
   - 작업 대상: proposal_validation.py.
   - 검증: T2, T3.
5. STEP-005 생성 service·전용 worker·gate [complex]
   - 목표: draft/section 상태 기계(stage 전이 포함), WorkJob `proposal_section` 6개·전용 run_once·슬롯 규칙·timeout 5400, cap(1/6), 재생성, superseded, 입력 예산 초과.
   - 작업 대상: proposal_draft.py, proposal_worker.py, workers/proposal.py, transfer_policy.py.
   - 검증: T4, T5(PG).
6. STEP-006 REST·overlay·review [complex]
   - 목표: REST 8개(exports POST/GET 분리·stage PATCH), edit overlay 적용, review 전이.
   - 작업 대상: routers/proposals.py, schemas.
   - 검증: T6(PG).
7. STEP-007 PDF 렌더 [complex]
   - 목표: 결정적 PDF(`invariant=1`·렌더러 버전·폰트 sha), 표식·부록, 객체 저장(`proposal-pdf`), UNIQUE(overlay).
   - 작업 대상: proposal_render.py, exports 라우트.
   - 검증: T7.
8. STEP-008 화면 [standard]
   - 목표: ui-spec §4.5 전부.
   - 작업 대상: 프런트 파일.
   - 검증: T8.
9. STEP-009 문서·mock·실제 1건 [complex]
   - 목표: 문서 7종, mock 전 경로, 사람 직전 확인 뒤 실제 1건.
   - 작업 대상: docs, bidops-local, README.
   - 검증: T10, T11, `doctor _`.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | identity·allowlist·의존 lock |
| STEP-002 | S | 낮음 | standard | 패턴 |
| STEP-003 | M | 높음 | complex | 허용 키·confirmed 필터 |
| STEP-004 | M | 높음 | complex | 정규식 경계·원문 인용 예외 |
| STEP-005 | L | 높음 | complex | 상태 기계·cap 분수·부분 보존 |
| STEP-006 | M | 높음 | complex | overlay·전이 |
| STEP-007 | M | 높음 | complex | 결정적 바이트·폰트 |
| STEP-008 | L | 중간 | standard | ui-spec 닫힘 |
| STEP-009 | M | 높음 | complex | 외부 호출·사람 확인 |

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 모델이 출처 없이 그럴듯한 문장 생성 | T2 거부율 높음 | 검증 실패는 failed·사람 검토, repair 1회만 |
| 가격·인력 숫자 유입 | T2 금지 패턴 매칭 | 코드 검증 + 원문 인용 예외만 |
| PDF 비결정성(시각·폰트·렌더러 버전) | 같은 overlay sha 다른 바이트 | `invariant=1`·subset 고정·overlay에 버전/폰트 sha 포함, T7 |
| `proposed` 실적을 confirmed처럼 서술 | 실적 절에 신용등급 등 | 입력 필터 T1 |
| 폰트 부재·변경 | 로컬·이미지에 `/usr/share/fonts/truetype/nanum` 없음, 이미지 갱신으로 `font_sha256` 변화 | 저장소에 폰트 파일을 넣지 않고 이미지의 NanumGothic만 사용(D9), 없으면 503 `pdf_unavailable`(T7), `font_sha256`이 overlay에 들어가 바뀌면 새 export |
| 실제 호출 상한 초과·RL-03 실패 판정으로 진행 | T11 호출 12회 초과, T12 미통과 상태에서 T11 시작 | T11은 RL-03 T12 통과 뒤에만, 승인 `--daily-cap 1`, 재시도·절 다시 쓰기 없음(D3·D4·D10) |
| `proposed`/`unknown` 값·운영 정보 전송 | T1·T9 실패 | `missing_facts`는 `{fact_key, status}`만, 전송 payload는 spec의 8키만(D2) |
| HWP 요구 재등장 | 사용자 요청 | 범위 밖 명시, 후속 결정 |

## 증명

- docs: `doctor _`, 문서 7종 diff.
- tests: `pytest tests/deep_review/test_proposal_validation.py tests/deep_review/test_proposal_render.py tests/app/test_proposal_api.py tests/app/test_proposal_payload_guard.py tests/deep_review/test_codex_runner.py tests/app/test_requirements_lock.py`.
- postgres: `test_proposal_api_postgres.py test_db_migrations.py test_runtime_database_privileges.py`.
- frontend: `npm run build && npx playwright test --project=app proposal.spec.ts`.
- api_guard: T4·T9.
- real_data_run: T11 실제 1건 — RL-03 T12가 통과한 그 판정(폴리텍 사전규격)으로 초안 1건, 최대 12회(절 6 + repair ≤ 6). 2026-10-17 배치 B 인터뷰가 범위 승인이며 실제 호출·정책 승인 CLI(`approve-transfer-policy --policy proposal-policy-luna-v1 --actor jechoi --daily-cap 1`) 직전에 짧게 알리고 진행. RL-03 T12가 1회 재시도 뒤에도 실패면 T11은 보류하고 보고(D3·D4·D10). spec의 호출당 repair(≤1) 외 자동 재시도·자동 보정·절 다시 쓰기 없음, 실패 절은 사람 검토로 남긴다. bidops-local 격리 스택에서만, runner egress·인증은 RL-03 T12와 같은 조건(`luna-egress`, `~/.codex/auth.json` 읽기 전용 secret — D6·D7), actor `jechoi`(D11). PDF는 격리 스택에서만 만들고 보관 값(365일·암호화 없음)은 spec 그대로(D12). 결과는 `unmeasured_reference`로만 기록하고 품질 근거로 쓰지 않는다.

## 결과

구현 후 작성한다.
