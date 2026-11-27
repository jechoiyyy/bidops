# 실행 계획

## 작업 순서

1. STEP-001 대조 규칙 v2와 회사 값 경로 [complex]
   - 지명 표 파일, 상주 장소·제외 분야 규칙, 계약 순서, reason code 2개, `requirement_terms` 노드 키, 허용 읽기 경로. 검사: `tests/deep_review/test_card_compare_blockers.py`(v1 결과 병기), 기존 대조·회사 근거 테스트.
2. STEP-002 정책 v12와 규칙 선택 [complex]
   - v11 바이트 + identity, 식별 집합·resume 계보·기본 경로. 검사: `tests/app/test_company_luna_policy.py`, `tests/app/test_card_analysis_postgres.py`(PostgreSQL), 영향 파일 묶음 SQLite·PostgreSQL.
3. STEP-003 D-2 탐침 재생과 과잉 차단 스캔 [complex]
   - 놓친 차단 7개를 v1/v2 × 회사 근거 v4/테스트 fixture로 재생, 10건 전 블록 스캔. 모델 호출 0. 증거: `docs/validation-runs/20261119-rl10-compare-blockers/` (git 이력).
4. STEP-004 문서 [complex]
   - business-rules·contracts·operations 기본 경로·findings·ADR 색인·현황.

## 검증 항목

| 요구 | 입력 | 기대 | 검사 | 증거 |
|---|---|---|---|---|
| 상주 장소 gap | 대구 밖 상주 절 + 확인된 `onsite_regions="대구"` | v2 `gap`, v1 그대로 | 단위 테스트 | pytest 출력 |
| 지명 불명 | 지정 장소·기관명·모호 이름·동사 | `place_unresolved` | 단위 테스트 | pytest 출력 |
| 미확인 사실 | proposed/unknown 4조합 | `unknown`, gap 없음 | 단위 테스트 | pytest 출력 |
| 제외 분야 | 용어로만 이루어진 요구/일부/인용 축소 | `gap`/`exclusion_partial` | 단위 테스트, 스캔 | pytest·probes.json |
| v11 재현 | 저장 v11 attempt의 v12 resume | `resume_source_invalid` | PostgreSQL 테스트 | pytest 출력 |
| 회사 근거 v4 그대로 | 놓친 차단 7개 탐침 | gap 0(정직한 결과) | 재생 스크립트 | probes.json |

## 실행 제약

- 모델 호출·운영 DB·`bidops-local` 기동 없음. 정책·회사 근거를 DB에 import하지 않았다. PostgreSQL은 일회용 컨테이너만 썼다.
- 회사 근거 fixture(`fixture_f1`·`f2`)는 테스트용이며 회사 사실이 아니다.

## 결과

검증 기록(`docs/validation-runs/20261119-rl10-compare-blockers/README.md`, git 이력) 참조. 종단 품질은 미측정이며 같은 gold 재측정은 사용자 승인 뒤에만 한다.
