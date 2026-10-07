# Luna v4 정책 선검증 — plan

- 기능 ID: `DEMO-00-luna-preflight`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-06

기준 브랜치는 main이다(DEMO-01~05의 데모 브랜치가 아니다). commit·merge·배포는 수동이며 각 운영 단계 직전에 사람 확인을 받는다.

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/deep_review/policies/analysis-policy-luna-v4.json | 신규 | v2 기반 불변 정책, 원인 분류에 따른 프롬프트 차이 |
| web/backend/app/deep_review/services/input_versions.py | 수정 | `_approved_policy_path` v4 명시 매핑 |
| web/backend/app/deep_review/services/deep_reviews.py | 수정 | 정책 `review_timeout_seconds`로 마감, slice 1회 교정 재요청과 기록 |
| web/backend/app/deep_review/services/narrative_inputs.py, services/verification.py | 조건부 수정 | STEP-001이 입력·검증기 결함으로 분류한 경우만 |
| web/backend/tests/app/test_luna_deep_review.py | 수정 | v4 매핑·import·fake 실패 응답 회귀 |
| web/backend/tests/app/test_narrative_review.py | 수정 | 필수 검증 유지 회귀 |
| docs/validation-runs/<실행일>-luna-v4-preflight/README.md | 신규 | 원인 분류·적용·실행·판정 기록 |
| docs/validation-runs/<실행일>-luna-v4-preflight/runbook.md | 신규 | 운영 호스트에서 사용자가 실행할 단계별 명령·확인 항목 |
| docs/tracking/status.md, docs/0922_luna-deep-review/apply.md | 수정 | 실행 결과와 v4 적용 절차 |

## 작업 순서

1. STEP-001 이전 실패 원인 분류 [complex]
   - 목표: v1~v3의 claim_relation_out_of_slice, considered_claim_out_of_slice, dangling_evidence를 프롬프트/입력 계약/검증기 결함으로 분류한다.
   - 작업 대상: `docs/validation-runs/20260922-luna-deep-review`, `20260923-luna-related-claims`, `20260923-luna-validation-off`, 운영 DB 원응답(읽기 전용)
   - 검증: 분류마다 근거 위치(파일·행 또는 attempt ID)를 README에 기록
2. STEP-002 v4 정책과 회귀 테스트 [complex]
   - 목표: 분류 결과만 반영한 v4 정책·고유 식별 필드·매핑, 정책 마감 읽기, slice 1회 교정 재요청을 만들고 필수 검증을 유지한다.
   - 작업 대상: 정책 파일, `input_versions.py`, 조건부 narrative/verification 코드, 두 테스트 파일
   - 검증: spec T1,T2,T3,T6,T7; 아래 명령
3. STEP-003 운영 적용 [complex]
   - 목표: 백업·롤백 태그 → 이미지 빌드 → web·analysis-worker 교체 → v4 import → env 적용 → Luna 토글 true를 각각 직전 확인 후 수행한다.
     운영 스택은 이 작업 장비에 없으므로 Claude가 단계별 명령·확인 항목(runbook)을 준비하고 사용자가 운영 호스트에서 실행해 출력을 돌려준다.
   - 작업 대상: 운영 Compose(파일 5개+luna, env 4개+luna.env), `import-profile-policy`, `env/luna.env`
   - 검증: spec T4; `docker compose config`·컨테이너 env 확인, 기존 v1~v3 행 불변 조회
4. STEP-004 실제 1489 1건과 판정 [standard]
   - 목표: 사용자가 운영 호스트에서 미리보기를 읽고 승인한 1건(약 3.5시간 이상)을 관측하고, 돌려받은 결과로 판정과 사용자 결정을 기록한 뒤 Luna 토글을 false로 되돌린다.
   - 작업 대상: 사전규격 1489 상세 화면, report/attempt GET, 판정 README
   - 검증: spec T5; 종료 상태·slice별 시간·실패 code 기록, 자동 재호출 0

## 위임

| 단계 | 작업량(S/M/L) | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | 실패를 프롬프트·계약·검증기로 가르는 판단 |
| STEP-002 | M | 높음 | complex | 승인 매핑·검증 불변식 |
| STEP-003 | S | 높음 | complex | 운영 변경·단계별 사람 확인 |
| STEP-004 | S | 중간 | standard | 정해진 관측·기록. 승인은 사용자가 한다 |

## 검사 명령과 증거

```sh
cd web/backend
BIDOPS_PRESPEC_OVERVIEW_ENABLED=false python3 -m pytest tests/app/test_luna_deep_review.py tests/app/test_narrative_review.py -q
```

응답 shape는 바뀌지 않으므로 PostgreSQL 변형은 N/A다(정책 행 import는 기존 테이블·기존 CLI). 바뀌면 일회용 postgres:17.11로 해당 파일을 돌린다.
실제 실행은 10분을 넘을 수 있으므로 관측은 분리 실행 로그로 하며 진행·실패·종료 코드를 모두 잡는다.

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 원인이 Luna 출력 변동이라 정책으로 못 고침 | 같은 입력에서 다른 위반 code | 실패 보존, DEMO 범위(최소 3건 기준 포함) 사용자 재결정 |
| 마감 초과 | 39회 이상 × 호출당 5~6분 | v4 마감 18000초, 초과 시 기록하고 재결정 |
| 교정 재요청이 검증 완화로 변질 | 재요청 뒤 검사 생략·경고 강등 | 재요청 응답도 같은 검증, T3·T6 |
| 운영 배포 회귀 | 기존 Luna·개요 경로 오류 | 롤백 태그로 이미지 복원, v1~v3 행은 불변 |
| 검증 완화로 통과 유도 | 필수 검사 off·경고 강등 | T3로 차단, 리뷰에서 diff 확인 |

## 증명

- docs: 원인 분류·판정 README, status·apply 갱신, 지정 모델 독립 리뷰.
- tests: 위 명령의 T1~T3 결과·skip 기록.
- postgres: N/A — 응답 shape·스키마 변경 없음(바뀌면 실행).
- frontend: N/A — 화면 변경 없음.
- api_guard: 승인 hash·사람 승인 1회·자동 재호출 0을 실행 기록으로 확인.
- real_data_run: 1489 실제 1건 판정 기록(통과·실패 모두 증거로 남김).

## 결과

미구현. 실행 후 원인 분류, v4 차이, 실제 결과, 사용자 결정, 커밋 여부를 기록한다.
