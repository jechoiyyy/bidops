# 온톨로지와 가상회사 지식그래프 — intent

- 기능 ID: `DEMO-02-company-knowledge`
- 작성일: 2026-10-06
- 상위: [DEMO 로드맵](../../../../constitution/roadmap.md)
- 크기: L — 새 계약·모듈/저장소 경계와 통합 인수 포함.

## 문제

기존 프로필 사실 목록에는 역량·실적·인력 사이의 관계와 가상 출처를 함께 표현하는 계약이 없다.

## 기대 결과

온톨로지와 가상회사 지식그래프를 [공통 계약](../../../../demo-contract.md) §3·4·8 및 §7의 합성회사 작성 기준과 아래 실제 조작으로 확인한다.
문서화와 제품 구현·검증 완료를 구분한다.

## 유즈케이스

| 유즈케이스 | 실행 방법 | 확인 기준 |
|---|---|---|
| 원본 승인 | Claude 초안 3사·온톨로지 → 사용자 검토 | 승인자·시각·source_sha256 기록 전에는 등록하지 않음 |
| 등록 전 검사 | import-company-knowledge --dry-run | 유효 결과 또는 오류; DB/객체/모델 쓰기 0 |
| 회사 등록/활성화 | import 및 activate CLI | 3사별 동일 원본의 profile/graph 생성·재등록 멱등 |
| 근거 탐색 | graph/profile/evidence GET | 관계 끝점·근거가 해당 회사/버전에 소속 |
| 과거 버전 재현 | graph_version_id 지정 조회 | 활성화 후에도 과거 값/hash/인용 동일 |

## 선행·후속 기능

- 선행: DEMO-01-company-context
- 후속: DEMO-03-grounded-analysis
- 위 직접 의존을 queue.json에 같은 순서로 등록한다. 선행은 제품 검증 완료 후 충족한다.

## 영향 범위

- 모듈·경로는 plan 변경 파일 표, 데이터/API는 spec 및 공통 계약 §3·4·8 및 §7의 합성회사 작성 기준.
- ARCHITECTURE 모듈 경계, business-rules 판단 분리, contracts 기존/DEMO 계약,
  standards 검증 범위, operations 승인 경계를 따른다. 상세 링크는 공통 계약에서 연결한다.
- 문서 작성 중 외부 호출 없음. 제품 실행 단계는 건별 승인·참조 표식을 유지한다.

## 제약

- 원문·프로필·정책·모델 입력과 결과·사람 리뷰는 불변/append-only로 보존한다.
- unknown/null·적합성·참여 준비·추적·Go/No-Go를 서로 대신하지 않는다.
- 외부 모델은 승인 payload만 건별 전송하며 전역 fallback과 자동 추적 결정을 금지한다.
- PostgreSQL 17·versioned MinIO·합성 analysis worker의 슬롯 1개와 모듈 의존 방향을 유지한다.
- 문서 변경은 diff/문서 검사만, 제품 변경은 직접 영향 검사만 실행하고 성공 후 반복하지 않는다.
- 운영 변경·실제 모델 호출은 직전 확인 대상이며 문서화 승인을 실행 승인으로 사용하지 않는다.
- 사용자 요청 없이 commit·merge·push·브랜치 삭제하지 않는다.
- DEMO-01~05는 DEMO-00이 통합된 main에서 분기한 데모 브랜치와 `bidops-local`에서만 구현·검증한다. main 병합·운영 전환은 별도다(ADR-0070 2026-10-09 개정).
- LiteLLM 개요·핏과 Luna 심층검토의 transport·정책·승인·품질 증거를 분리한다.
- 새 DB 테이블·열 권한은 scripts/runtime-privileges.sql에 등록하고 migration에 GRANT를 쓰지 않는다.

- 기준 출처/hash: [source-baseline](../../../../source-baseline.json).
- 실행용 복사: [feature.json](../../../../feature.json)의 constraints/constraint_sources.

## 범위 밖

공통 mission의 후속 범위. 후속 기능의 구현/실제 인수를 현재 기능 완료로 적지 않는다.

## 출처 간 차이

| 차이 | 기존 | 사용자 확정 | 반영 |
|---|---|---|---|
| 회사 기준 | 전역 단일 프로필·추적 | 3사 전환·비교 | ADR-0070·공통 계약으로 확장 |
| 회사 근거 | 실제 자료의 확인/미확인 | 가상회사 설정 | origin과 확실성 분리 |
| 관리 구조 | 기존 분야별 문서 | SDLC 기능 5개 | 과거 보존·신규 그룹만 등록 |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| 실제 전송·운영 변경 승인 | 각 작업 직전 | 문서화 승인으로 대체하지 않음; DEMO-05 증거에 연결 |

제품 범위·회사 구성·표본 수·모델·온톨로지 수준은 사용자 선택으로 확정되었다.
2026-10-06 재계획: 원본은 Claude 초안·사용자 승인 후 공고 선정 전에 동결하고, 별칭만 공고 선정 뒤 1회 보강한다(DEMO-05에서 수행).
