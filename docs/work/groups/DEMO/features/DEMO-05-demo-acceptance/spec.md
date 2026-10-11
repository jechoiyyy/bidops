# 격리 데모와 실제 예제 인수 — spec

- 기능 ID: `DEMO-05-demo-acceptance`
- 작성일: 2026-10-06 (같은 날 재계획 개정)
- 근거: [intent](intent.md), [공통 계약](../../../../demo-contract.md) §7·10
- 상태: 구현 목표. 현재 제품 계약과 구별한다. 별도 데모 브랜치와 `bidops-local` 격리 스택에서 검증하며 main 병합·운영 전환은 별도다.

## 큰 틀 문서와의 관계

ADR-0070 및 기존 정본의 DEMO 목표 절을 구체화한다.
공통 계약 §7·10의 필드·필수/nullable·enum 전체·식별/유일성·실패 규칙은 이 spec의 일부다.
기존 단일회사 wire·불변성은 유지한다. 계약 변경은 관련 기능/정본에 함께 반영한다.

## 입력·출력 계약 및 저장

Compose project는 `bidops-local`이다. 운영과 다른 DB/MinIO/volume/host publish 주소를 쓴다.
기반+edge+model-egress+prespec-attachment+luna+demo overlay, prespec/luna profile을 공통 §10 순서로 사용한다.
codex_auth는 승인된 계정 파일이며 데모 Luna는 다른 Luna 실행과 겹치지 않게 순차로 돌린다.
로컬 개요·핏 모델은 LiteLLM 별칭 `local-agent-main`이다. `/models`와 `/model/info`의 별칭·입력 상한을 호출 전에 검사하며 upstream 모델명·revision을 추정하지 않는다.
자동 개요·회사 핏·심층 시작은 false로 유지하고, manifest target마다 문서 준비와 모델 실행을 one-shot으로 요청한다.
C-2 overlay/cron/scheduler를 연결하지 않는다. secret은 로컬 env에만 주입하고 운영 .env를 자동 복사하지 않는다.
prepare 스크립트는 default dry-run이며 --apply는 승인된 초기화 단계에만 사용한다.
모델 전송·정책 활성화·재배포는 각각 사람 확인 후 별도 CLI/UI로 수행하고 prepare가 연달아 하지 않는다.
2026-10-06~08 실제 수집 범위의 정규 run ID·source hash를 먼저 동결한다. 그 범위에서 분야별 2건, 총 6건을 고르고 첨부를 받지 못한 공고는 같은 동결 범위의 다음 후보로 바꾼다.
원문 단위 수가 적은 공고를 우선한다(심층 3건은 8개 이하 목표, 공통 §7). 6건 manifest는 전체 3일 corpus를 덮어쓰지 않는 파생 선택이다.
운영 회사 프로필/리뷰/승인/전체 DB dump를 데모로 복사하지 않는다. 정규 run ID·hash·적재 경고를 확인한다.
실제 fixture/원문/manifest는 `data/demo/`(이 기능이 .gitignore에 추가), 공개 schema와 순수 합성회사 예제만 Git 대상이다.
공고 선정 뒤 온톨로지 별칭을 1회 보강하고(개념 불변) 3사를 재등록·활성화한 뒤 manifest를 동결한다. 보강 diff와 사유를 증거로 남긴다.
첫 대표 1건×3사 인수 뒤 나머지로 확대한다. 결과를 맞추기 위해 profile/모델 출력을 수정하지 않는다.
2026-10-11 DEMO-03 T9(대표 1건 실제 Luna 심층: 별도 미리보기·건별 승인 뒤 completed 3단계·필수 검증·원문 근거 확인, LiteLLM 개요 결과 비합산)를 이 기능의 첫 대표 1건×3사 인수로 이관했다. DEMO-03은 실제 `bidops-local`에 0036·3사·demo 정책 2건·demo flag·codex-runner를 적용했고(2026-10-11, `docs/validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/`), 공고 179는 회사 미리보기 단계에서 inventory 불일치로 fail-closed됐다.
후보 공고 선정은 모델 호출 전에 문서 segment manifest `expected_ids`와 분할 단위 본문 관측 ID의 일치를 검사해 불일치 공고를 다음 후보로 바꾼다(`docs/tracking/findings.md` "요구사항 표의 행별 셀 위치 차이"). 검사 완화·SQL 보정으로 통과시키지 않는다.
최소 시연 기준(demo_ready)은 핏 18건과 first_deep_review_notice_id의 3사 보고서 인수다. 목표는 9건이며, demo_ready만 충족하면 나머지는 실패·미실행 기록과 함께 시연한다.
verify-company-demo는 GET만 사용해 manifest의 동일 회사/문서/graph로 정확히 18개 completed 핏·9개 completed report를 검사한다.
담당자(사용자 본인)는 보고서마다 과업·회사 근거·격차·미확인·후속 행동을 원문과 대조한다.
사람 인수 기록의 strict 필드·Check 구조·append-only revision 경로·CLI·검증 종료 코드는 공통 §10을 따른다. 보고서 9건의 최신 인수가 모두 accepted=true여야 완료다.
기대와 다른 fit도 보존하며 근거가 없으면 해당 사례 인수를 유보한다. 과거/mock 결과를 합산하지 않는다.
장시간 실행은 분리 실행하고 진행/실패/종료 코드를 관측한다. 정책이 허용한 v4 slice 교정 외 자동 재호출 없이 실패를 보존한다.
2026-10-09 notice 179 물리 4쪽 개요는 `unmeasured_reference` 준비 증거로만 재사용한다. 물리 5쪽 text/display 불일치는 미해결로 보존하고 선택 payload에서 제외한다.

## 인터페이스·상태·실패

공통 계약 §7·10의 endpoint/CLI/DTO를 사용한다.
unknown/null·준비 전·stale·실패·참조 표식을 성공/부적합으로 변환하지 않는다.
쓰기/전송 전에 회사·version·hash를 검사한다. 원문 경로·secret·모델 본문을 일반 응답/로그에 노출하지 않는다.

## 설정 키와 기본값

| 키 | 기본값 | 허용/적용 | 근거 |
|---|---|---|---|
| BIDOPS_DEMO_ENABLED | false | bool; 격리 데모에서 명시 활성 | 운영 경계 |
| BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED | false | 기존 bool | 사람 요청 분석 |
| BIDOPS_VLLM_OVERVIEW_API_DIALECT | litellm | 개요용 `local-agent-main`; Luna 심층과 분리 | 로컬 모델 경계 |
| graph depth/limit | 2/200 | 공통 §4, tunable | bounded 조회 |
| 가상 수치 | 원본에 명시 | DEMO-02에서 창작·분석 전 동결, tunable | 실제 사실로 오인 금지 |

## 결정과 이유

| 결정 | 근거 | 적용하지 않는 대안 |
|---|---|---|
| 회사/입력 버전 명시 | 사용자 전환·비교 선택 | 전역 프로필 교체 |
| 단일 원본에서 근거 생성 | 불변성·그래프 분석 활용 요구 | 프로필/그래프 별도 편집 |
| 실제 인수 분리 | 실제 결과 선택·기존 Luna 실패 이력 | mock을 실제 성공으로 집계 |
| 외부 그래프 서비스 | N/A — 업무 온톨로지·기존 PostgreSQL 사용 | RDF/OWL·별도 DB |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | Compose dry-run/격리/기동 | `bidops-local` 설정/자원·startup 무호출·운영 변화 없음 | 환경 통합 |
| T2 | 스크립트 fake API 계약 | 실제 shape/정규 ID/경고/실패 응답 준수 | 도구 단위 |
| T3 | corpus/회사 고정 | 2026-10-06~08 정규 run ID/source hash·분야별2·대표1·first_deep_review_notice_id·18/9 조합 유일·별칭 보강 diff 기록 | 계약/통합 |
| T4 | 첫 1건×3사 | 건별 승인·3단계·보고서/근거 확인 | 실제 모델 |
| T5 | 전체 6/18/9 | LiteLLM 핏 18과 Luna 심층 9의 완료 ID·동일 기준·참조 표식·검증 미실시 없음·demo_ready와 overall 구분 | 실제 모델 |
| T6 | 담당자 두 폭 종단 | 회사 차이/근거/세 상태 독립 결정/재조회 | 실제 UI/수동 |
| T7 | 실패/복구/로그 | 실패 보존·명시 재요청·secret/원문 미노출 | 환경/수동 |

## 컨벤션 반영 항목

새 회사 경로·origin·graph/version identity는 공통 계약, 상태 분리는 business-rules,
DB·외부 호출은 해당 정본의 DEMO 절에 반영한다. 구현 목표를 현재 동작으로 표시하지 않는다.
