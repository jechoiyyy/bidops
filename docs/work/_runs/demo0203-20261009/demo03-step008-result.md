# DEMO-03 STEP-008 회사 핏 원문 unit 연결 (2026-10-11)

- 계기: Codex 배치 리뷰 2회차(`batch-codex-review-r2.md`) FAIL 차단 1건. 회사 핏 `prepare_company_fit`이 `requirements_from_overview`를 원문 unit 없이 호출해 모든 핏 Requirement의 `source_units`·`document_requirement_ids`가 빈 배열이었다. 리더가 소스에서 사실로 확인했다. STEP-002 때 "핏은 bundle이 없어 비움"으로 받아들인 결정이 계약(§5 Requirement·SourceUnit, 개요 페이지·인용의 원문 unit 연결)과 CLAUDE.md 강제 게이트에 어긋났다.
- 사용자 결정: "코드 수정, bundle 필수". 공통 계약 §9·spec T2/T4·plan STEP-008을 먼저 개정하고 `run _ accept-spec`으로 기록했다.
- 구현: sdlc:implementer-opus. 리더는 diff를 읽고 일회용 PostgreSQL 17.11에서 영향 검사를 직접 재실행했다.

## 변경

| 파일 | 내용 |
|---|---|
| `policies/company-fit-demo-v3.json` (신규) | v2와 같고 `schema_version=bidops.company-fit-policy.v3`, `chunking.source_characters=6000`만 다름(리더가 키 차이 확인). sha256 `1ecf5cbf10cc43a0bf6b1d2d5f87e1172332854e94d868326d5c82e45a9e2e0d` |
| `services/company_fit_policy.py` | schema별 chunking 키 검증, v2·v3 모두 승인 import 파일, 새 enqueue 전용 resolver는 v3만(v2 행은 `analysis_policy_unavailable`), 실행·현재성은 v2·v3 모두 허용 |
| `services/company_source_units.py` (신규) | 심층 `company_source_units` 본문을 그대로 옮긴 공용 `bundle_source_units`(순환 import 회피, 분할기 lazy import) |
| `services/company_deep_review.py` | 공용 helper를 감싸 기존 409 오류로 매핑. unit 동작 불변 |
| `services/company_fit.py` | gate에 최신 ready bundle(`bundle_not_ready`), 문서 집합=bundle 문서, 분할기 unit을 개요 문서·evidence page로 연결. 입력 `bundle_id=null` 유지(0036 guard 불변). 현재성은 선택 정책 schema별 문서 집합 |
| `company_analysis_input.py`·`company_projection.py`·`models.py`·`cli/enqueue_company_fit.py` | docstring |
| 문서 | 공통 계약 §9 개정, spec T2/T4, plan STEP-008, contracts·ARCHITECTURE DEMO-03 단락, operations 데모 절(v3 import 운영 후속) |
| 테스트 | enqueue·analysis·e2e·deep binding fixture가 실제 structure payload를 저장. 실제 조립 경로의 unit 연결, `bundle_not_ready`, inventory 불일치, v2 선택 거부, v3 import, v2 고정 attempt 실행, 핏·심층 unit 동일성 검사 추가 |

migration·권한·frontend 변경 없음. 운영 스택·모델 호출 없음.

## 계약 침묵 구간의 구현 결정 (리더 수용)

- 정책 해석을 둘로 나눴다. 새 enqueue만 v3를 요구하고, 이미 동결된 v2 attempt는 저장된 정책 행으로 실행·현재성 판정을 한다.
- v3 attempt의 현재성은 최신 ready bundle 문서 집합과만 비교한다. v2 attempt는 기존 `notice_document_sets`를 유지한다.
- bundle의 pinned 구조를 읽지 못하면 심층 `_ready_bundle`과 같이 `bundle_not_ready`다.
- v3의 `prompt_version`은 v2와 같은 값을 유지했다(지시 범위가 schema와 source_characters뿐).
- runner는 claim 때 unit을 다시 분할하지 않는다(동결 입력 사용, 계약 요구 없음).

## 변경된 기존 기대값

- e2e b2: bundle 없는 enqueue가 is_current 문서를 동결하던 기대를, 개정 §9에 따라 `bundle_not_ready`·무쓰기 뒤 bundle 기반 집합으로 바꿨다.
- 정책 파일·import 검사는 v3 파일 기준으로 바꾸고 v2는 별도 검사로 보존했다.
- 심층 fixture는 가짜 structure 대신 같은 payload를 실제 저장한다. 심층 단언 변경 없음.

## 검증

| 실행 | 결과 | 로그 |
|---|---|---|
| 구현자 red 1 (정책·모듈 부재) | 76 failed, 79 errors, exit 1 | `demo03-step008-before.log` |
| 구현자 red 2 (정책 층만 존재) | 12 failed, 실제 동작 결함(빈 unit, gate 없음, v2 수용) | `demo03-step008-before-units.log` |
| 구현자 green | 477 passed, 0 skipped, exit 0 | `demo03-step008-tests.log` |
| 리더 재실행: 회사 테스트 전부 + DEMO-02 검사 9파일 + DEMO-03 plan 검사 + STEP-008 영향 검사, 23파일 | 764 passed, 0 skipped, exit 0 | `demo03-step008-leader.log` |

## 남은 위험 (DEMO-05로 넘김)

- `bidops-local`에는 v2 핏 정책만 있다. 실제 핏은 이미지 재빌드·v3 import·env 재지정 뒤에만 가능하며 각각 직전 확인 대상이다.
- 핏 CLI가 structure 객체를 읽으므로 실행 역할의 object store 읽기 권한을 실제 스택에서 확인해야 한다.
- 공고 179는 inventory 불일치로 핏도 호출 전 `company_input_invalid`가 된다(완화하지 않음).
- 실제 문서에서 prompt 크기(`max_characters`=120000)를 넘을 수 있다. 넘으면 `company_input_invalid`다.
- 개요 evidence page와 structure block page의 번호 체계가 다르면 연결이 비거나 다른 page에 붙을 수 있다. 빈 연결은 coverage에 드러나지만 잘못된 page는 결정적으로 잡지 못한다. 실제 자료에서 확인한다.
- 같은 문서 집합에 구조만 다시 추출된 새 bundle이면 옛 핏이 현재로 남는 기존 한계는 그대로다.
