# 그래프 근거 기반 회사 핏과 Luna 심층검토 — intent

- 기능 ID: `DEMO-03-grounded-analysis`
- 작성일: 2026-10-06
- 상위: [DEMO 로드맵](../../../../constitution/roadmap.md)
- 크기: L — 새 계약·모듈/저장소 경계와 통합 인수 포함.

## 문제

기존 회사 핏과 Luna preview는 전역 프로필을 사용한다. 그래프 경로를 실제 모델 입력과 보고서의 근거에 연결해야 한다.

## 기대 결과

그래프 근거 기반 회사 핏과 Luna 심층검토를 [공통 계약](../../../../demo-contract.md) §5·6·9 및 §10의 “조회용 동결 계보”와 아래 실제 조작으로 확인한다.
문서화와 제품 구현·검증 완료를 구분한다.

## 유즈케이스

| 유즈케이스 | 실행 방법 | 확인 기준 |
|---|---|---|
| 회사 핏 실행 | `enqueue-company-fit` CLI(회사·공고별) | 독립 실행·사유와 graph 경로 연결·승인 화면 없음(사설 vLLM) |
| 부합하지 않는 회사 비교 | 준비된 SW 사전규격의 수동 심층 승인 | mismatch/unknown 결과를 바꾸지 않고 분석 |
| 보고서 근거 확인 | 회사 report/evidence GET | 문서/가상회사/graph 버전 일치 |
| 변경 입력 구분 | binding 변경 뒤 옛 결과/preview 조회·제출 | stale/409·이미 승인된 실행 입력 불변 |
| 자격 분리 | C-1 등급이 우선 검토가 아닌 SW=Y 공고 | 회사 핏·심층이 SW사업대상=Y만으로 허용됨 |
| 실제 격리 스택 게이트 (2026-10-11 재정의) | 승인 단계별 `bidops-local` 준비→대표 공고 회사 미리보기 | 모델 호출 없이 fail-closed 또는 동결 입력 생성. 대표 1건 실제 Luna 심층(completed 3단계·필수 검증·원문 근거)은 DEMO-05가 인수하며 LiteLLM 개요 완료로 대신하지 않음 |

## 선행·후속 기능

- 선행: DEMO-02-company-knowledge
- 후속: DEMO-04-review-workspace
- 위 직접 의존을 queue.json에 같은 순서로 등록한다. 선행은 제품 검증 완료 후 충족한다.

## 영향 범위

- 모듈·경로는 plan 변경 파일 표, 데이터/API는 spec 및 공통 계약 §5·6·9 및 §10의 “조회용 동결 계보”.
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
2026-10-09 재계획: 핏은 LiteLLM `local-agent-main`과 승인 없는 CLI, 심층은 별도 Luna preview/approval을 재사용한다. 당시 대표 1건의 실제 Luna 심층 완료를 DEMO-04 선행 게이트로 두었다.
2026-10-11 재계획: 대표 1건 실제 Luna 심층은 DEMO-05로 이관했다(공고 179가 기존 inventory 불일치 findings로 호출 전 fail-closed). DEMO-03 게이트는 실제 격리 스택 준비와 호출 전 fail-closed 확인이며, DEMO-04는 fake 종단·실제 스택 준비 증거를 입력으로 진행한다.
