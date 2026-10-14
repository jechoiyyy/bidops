# codex-exec 모델 identity 전환 (gpt-6-luna / high) — spec

- 기능 ID: `HP-00-luna-model-identity`
- 근거: [intent.md](./intent.md), [HP 공통 계약](../../../../hp-contract.md) §0
- 작성일: 2026-10-14 (같은 날 독립 검사 1·2차 지적 반영)

## 큰 틀 문서와의 관계

- 인용하는 절: HP 공통 계약 §0, DEMO 계약 §9(정책 선택·preview·승인·오류 code), contracts.md ADR-0069 절, AGENTS "policy·binding·generation config 파일은 버전+sha256으로 고정".
- 이 문서에서 새로 확정하는 항목: identity 모듈의 이름·값, 새 정책 파일 2종(회사용 hp-v1, NULL 계보용 v5)의 내용 차이, 회사 정책 identity 집합, 모델 일치 강제 위치와 오류 code, 표식을 정책 row에서 읽는 규칙, CLI 버전, 격리 스택 runner 이미지 overlay.
- 큰 틀 문서 수정이 필요한 항목(STEP-005): contracts.md ADR-0069 절의 `model=gpt-5.6-luna`·`reasoning_effort=xhigh` 문장과 "실행 metadata의 CLI version은 0.155.1" 문장을 "고정 정책 row의 값(현재 HP: gpt-6-luna/high, CLI 0.162.1); 정책 모델이 runner identity와 다르면 503 `model_binding_invalid`"로 고친다. contracts.md의 DEMO-03 정책 줄(`analysis-policy-luna-demo-v1`을 `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID`로 선택)에 hp-v1을 더한다. DEMO 계약 §9에 "2026-10-14 HP-00: 심층 identity는 HP 공통 계약 §0, 회사 정책 identity 집합은 demo-v1·hp-v1. NULL 계보 경로의 기능 off는 `service_unavailable` 유지, 정책 모델 불일치는 `model_binding_invalid`" 한 줄.

## 입력·출력 계약

### identity 모듈 `app/deep_review/services/luna_identity.py`(신규)

```
PROVIDER = "codex-exec"
MODEL = "gpt-6-luna"
REASONING_EFFORT = "high"
CLI_VERSION = "0.162.1"
HP_POLICY_IDENTITY = "analysis-policy-luna-hp-v1"
COMPANY_POLICY_IDENTITIES = frozenset({"analysis-policy-luna-demo-v1", HP_POLICY_IDENTITY})   # 회사 계보 전용
LEGACY_MODELS = frozenset({"gpt-5.6-luna"})
LEGACY_EFFORTS = frozenset({"xhigh"})
ALLOWED_MODELS = frozenset({MODEL}) | LEGACY_MODELS        # 저장된 row의 조회·schema 검증
ALLOWED_EFFORTS = frozenset({REASONING_EFFORT}) | LEGACY_EFFORTS
def matches_runtime(model_name, reasoning_effort) -> bool  # model_name == MODEL and reasoning_effort == REASONING_EFFORT
```

- runner는 별도 컨테이너라 상수를 따로 가진다(`MODEL`, `REASONING_EFFORT`, `CLI_VERSION`). 테스트가 두 모듈의 값을 대조한다(T1).

### 정책 파일 2종 (canonical bytes, 신규)

| 파일 | 기반 | 다른 키 | 용도 |
|---|---|---|---|
| `analysis-policy-luna-hp-v1.json` | demo-v1 | `policy_identity=analysis-policy-luna-hp-v1`, `model_name=gpt-6-luna`, `generation.reasoning_effort=high`, `execution.cli_version=0.162.1` | 회사 계보(HP). `COMPANY_POLICY_IDENTITIES`에 속하고 전역 active로는 거부 |
| `analysis-policy-luna-v5.json` | v4 | `model_name=gpt-6-luna`, `generation.reasoning_effort=high`, `execution.cli_version=0.162.1`(그 외 v4와 동일) | NULL 계보(일반 Luna preview·가정 분석·기존 end-to-end 테스트). 전역 active 후보 |

- `input_versions.py`: `_approved_policy_path`의 codex-exec 분기에서 identity가 없는 파일의 버전 판정(`v1|v2|v3`)에 `v5`를 더한다(판정 키: `execution.cli_version == CLI_VERSION`이면 v5). `_LUNA_POLICY_FILES_BY_IDENTITY`에 hp-v1 파일을 더한다. `_require_path_limit`·전역 active 거부는 `COMPANY_POLICY_IDENTITIES` 전체에 적용. `_validate_model_binding`의 codex-exec 참조 모드 허용 조건은 `policy.model_name in ALLOWED_MODELS`(저장 row 검증용; 실행 허용은 아래 표가 정한다).
- 나머지 키·값·순서는 기반 파일과 같다. `pipeline_version == "narrative-v2"` 검사는 유지(HP-03이 바꾼다). 두 파일의 sha256은 발행 뒤 plan `## 결과`와 validation-runs README에 적는다.

### 모델 일치 강제 (runner는 하나이므로 정책이 다른 모델을 적으면 실행하지 않는다)

| 위치 | 규칙 | 실패 |
|---|---|---|
| 회사 preview·생성·재시도 (`company_deep_review.resolve_company_deep_policy`) | `matches_runtime(row.model_name, generation.reasoning_effort)`를 **먼저** 검사하고, 그 다음 `policy_identity in COMPANY_POLICY_IDENTITIES`·chunking·generation 구조를 검사한다 | 모델/effort 불일치 503 `model_binding_invalid`; identity·구조 불일치 503 `analysis_policy_unavailable` |
| NULL 계보 preview (`luna_inputs.snapshot` **안**, 기능 off·참조 모드 검사 바로 뒤) | 선택된 정책(전역 active 또는 재시도의 고정 정책)이 `is_luna`이고 `matches_runtime`이 아니면 거부. `snapshot`을 부르는 일반 preview와 가정 분석 preview(`assumption_analysis._snapshot`)가 모두 이 검사를 지난다 | 503 `model_binding_invalid`(기능 off는 기존 `service_unavailable` 유지) |
| NULL 계보 `create_review`·`create_attempt` (`deep_reviews.py`) | 고정 정책이 `is_luna`이고 `matches_runtime`이 아니면 거부 | 503 `model_binding_invalid` |
| worker claim (`deep_reviews.py` Luna 분기, client 생성 전) | 고정 정책이 `matches_runtime`이 아니면 호출 없이 attempt를 실패로 종결 | attempt `failed`, `last_error_code=model_binding_invalid`, runner 호출 0 |
| 가정 분석 worker (`assumption_analysis._execute`, client 생성 전) | 저장된 `scenario.settings`가 identity와 다르면 기존 `execution_config_changed`로 종결(이미 있는 검사를 identity 상수로 평가), 추가로 고정 정책 `matches_runtime` 검사 | run `failed`, `execution_config_changed` 또는 `model_binding_invalid`, 호출 0 |
| worker 회사 분기·slice 검증 (`deep_reviews.py` `company != demo_policy`, `company_slices.py`) | `policy_identity in COMPANY_POLICY_IDENTITIES`로 일반화. 회사 계보는 집합 안 identity여야 하고 NULL 계보는 집합 밖이어야 한다 | 기존 `company_policy_invalid` 유지 |
| 전역 active 해석 (`input_versions.resolve_active_versions`) | `COMPANY_POLICY_IDENTITIES`의 정책을 전역 active로 거부(현재 demo-v1만 거부하던 규칙의 일반화) | 기존 code 유지 |

v1~v4 정책 row로는 새 preview·attempt를 만들 수 없고 이미 승인된 legacy attempt는 호출 없이 실패한다. NULL 계보가 필요한 테스트와 운영은 v5를 쓴다.

### runner

- argv: `--model gpt-6-luna`, `-c model_reasoning_effort="high"`. 그 외 플래그·sandbox·ephemeral·schema 처리는 불변.
- 완료 응답 `cli_version`은 `0.162.1`. 시작 시 `codex --version != "codex-cli 0.162.1"`이면 `cli_version_mismatch`로 종료(기존 규칙).
- Dockerfile: `@openai/codex@0.162.1`. 모델·schema를 요청에서 받지 않는다.

### client (`luna_client.py`)

- `provider_name=PROVIDER`, `model=MODEL`. 응답 `cli_version != CLI_VERSION`이면 `runner_identity_mismatch`(기존 규칙, 값만 교체).
- `InvocationResult.attempts` metadata `{'status','provider','model','cli_version','reasoning_effort'}`는 identity에서 채운다.

### 표식의 출처

- preview 응답(일반 `luna_inputs.snapshot` 호출부, 회사 `CompanyDeepReviewPreviewView`): `provider=PROVIDER`, `model=policy.model_name`, `reasoning_effort=정책 payload generation.reasoning_effort`. 강제 규칙 때문에 성공한 preview의 값은 항상 identity와 같다.
- 승인 감사 `safe_metadata`(일반·회사·가정 분석): 같은 규칙.
- attempt view(`deep_reviews._attempt_view`): attempt → review → `policy_version_id`로 `AnalysisPolicyVersion`을 읽어 `model=row.model_name`, `reasoning_effort=row.validation_rules["generation"]["reasoning_effort"]`(import가 기록하는 위치)를 돌려준다(승인이 있는 attempt만; 없으면 기존 null). legacy row는 저장된 값(gpt-5.6-luna/xhigh) 그대로 보인다.
- invocation metadata(worker Luna 분기): `cli_version=CLI_VERSION`, `reasoning_effort=정책 generation.reasoning_effort`, `model=result.model`.
- 가정 분석: `assumption_inputs.MODEL/EFFORT`를 identity 값으로 바꾼다(VERSION `1489-assumptions-v1` 유지). 모델·effort는 preview 응답 `input.scenario.settings`에만 있고 별도 settings REST는 없다. 화면 `assumption-analysis/Request.tsx`의 고정 문구에서 모델명을 빼고, preview가 돌아온 뒤 `input.scenario.settings.model · reasoning_effort`를 표시한다.

### pydantic·TypeScript 타입

- `DeepReviewPreviewView.model: Literal["gpt-6-luna"]`, `reasoning_effort: Literal["high"]`(preview는 강제 규칙을 지난 새 실행만 만든다). 회사 preview DTO도 같다.
- attempt/report view의 `model`·`reasoning_effort`는 `str | None` 유지(legacy 값 조회).
- `companyApi.ts`: `model: "gpt-6-luna"`, `reasoning_effort: "high"`. `LunaRequest.tsx`는 이미 응답 필드를 표시한다.

### 격리 스택 runner overlay (STEP-006)

- 새 compose overlay `docker-compose.hp-local.yml`(저장소, 계약 파일): `codex-runner` 서비스의 `image: ${BIDOPS_DEMO_CODEX_RUNNER_IMAGE:?codex runner image tag required}`만 선언한다(그 외 설정은 `docker-compose.luna.yml` 그대로). `env/demo.env`의 `BIDOPS_DEMO_CODEX_RUNNER_IMAGE`가 이 overlay의 유일한 소비처가 된다.
- 이미지는 `docker-compose.luna.yml` build로 만들고 `bidops-local:codex-runner-<YYYYMMDD>`로 태그한다. 교체는 실행 중 스택의 compose 파일 집합(`docker inspect` `com.docker.compose.project.config_files`)에서 시점 증거 overlay(`docs/validation-runs/2026-10-10-company-demo/.../demo03-stack.yml`)를 이 overlay로 바꾼 집합으로 한다. 집합·태그·sha256을 README에 적는다.
- `env/demo.env`의 `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID`를 hp-v1 row id로 바꾼다. 실제 호출 전 사용자 확인.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID` | UUID | 비움 | import된 hp-v1 row id | 격리 스택 env |
| `BIDOPS_DEMO_CODEX_RUNNER_IMAGE` | str | 없음(필수) | `bidops-local:codex-runner-<YYYYMMDD>` | hp-local overlay |
| CLI 버전 상수 | str | `0.162.1` | 호스트 검증 버전 | `tunable`(코드 상수, 정책 파일에 복제) |

## 상태 값과 실패 처리

- 기존 code 유지: `runner_identity_mismatch`, `analysis_policy_unavailable`(503), `company_policy_invalid`, `cli_version_mismatch`(runner 종료), `execution_config_changed`(가정 분석), `service_unavailable`(기능 off).
- `model_binding_invalid`(503)는 회사 REST뿐 아니라 NULL 계보 preview/create/attempt에도 쓴다. worker에서는 attempt `failed`의 `last_error_code`로 쓴다(새 안전 code, 외부 전송 없음).

## 저장

- `AnalysisPolicyVersion` 새 row 2개(hp-v1·v5 import). 테이블·열·권한·migration 변경 없음.

## 인터페이스(CLI·UI·API)

- 정책 import: `python -m app.deep_review.cli import-profile-policy --policy <파일> --actor <name> --label <identity 또는 v5> --expected-policy-sha256 <발행 sha256>`(DEMO-00 runbook과 같은 절차)를 두 파일에 각각.
- REST 경로·DTO 키 변경 없음(값·오류 code만). 프런트 경로 변경 없음.
- 새 compose overlay `docker-compose.hp-local.yml`.

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| identity 모듈 한 곳 + runner 상수 대조 테스트 | 26개 파일 복제가 전환을 막았다(2026-10-14 조사·독립 검사) | 각 파일 문자열 치환만 |
| 표식은 정책 row에서 읽고 상수는 검증에만 쓴다 | 공통 계약 §0; 기록과 실제 호출이 갈리지 않게(`_validate_model_binding` docstring과 같은 이유) | 상수를 응답에 그대로 복사 |
| 정책 모델이 runner identity와 다르면 실행하지 않는다 | runner가 하나라 legacy 정책 attempt가 새 모델로 실행되면 승인 감사·정책 row·실행 기록이 갈린다(독립 검사 1차) | `model: str` 유지(표식 약화) |
| NULL 계보용 v5를 함께 발행한다 | v1~v4를 막으면 일반 Luna 경로의 end-to-end 테스트(`test_luna_deep_review.py` 21곳·가정 분석 9건)가 전부 거부 기대로 바뀌어 실행 커버리지가 사라진다(독립 검사 2차). v5는 v4에 identity 키 3개만 바꾼 파일이다 | hp-v1 전역 허용(회사 전용 불변식 위반) / 일반 경로 영구 fail-closed(커버리지 상실) |
| CLI 0.162.1 | 호스트 `codex --version`이 `codex-cli 0.162.1`이고 그 호스트의 SDLC 도구(`runtime.codex.json`)가 gpt-6-luna를 쓴다 | 0.155.1 유지(gpt-6 계열 미검증) |
| legacy 값 조회 허용 | 기존 row·fixture·감사 기록 불변 | legacy row 조회 거부 |
| 회사 정책 identity 집합 | worker·slice 검증이 demo-v1 문자열에 묶여 hp-v1 실행이 `company_policy_invalid`로 막힌다(독립 검사 1차) | demo-v1 문자열 치환 |
| 강제 지점을 `snapshot` 안에 둔다 | 일반 preview와 가정 분석 preview가 같은 함수를 지난다(독립 검사 2차) | 호출자마다 검사 |
| runner 이미지 태그를 저장소 overlay로 고정 | 지금 태그는 validation-runs 밑 시점 증거 파일에만 있고 env 변수는 소비처가 없다(독립 검사 2차) | 증거 overlay 수정 |
| 가정 분석 상수·화면 문구 변경 | 같은 runner를 쓰므로 기록이 실제와 같아야 한다; 별도 settings REST는 없다 | 범위 밖으로 남김 |
| Terra 미지원 | 2026-10-14 사용자 취소 | 두 번째 model identity |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | runner argv·상수와 identity 모듈 대조, `codex exec --help` 플래그 대조 | `--model gpt-6-luna`, `model_reasoning_effort="high"`, `runner.CLI_VERSION == luna_identity.CLI_VERSION == "0.162.1"`, `runner.MODEL == luna_identity.MODEL` | 단위 |
| T2 | client MockTransport: cli_version 0.162.1 / 0.155.1 | 성공·metadata model/effort/cli_version 일치 / `runner_identity_mismatch` | 단위 |
| T3 | hp-v1·v5 파일 canonical·import; demo-v1·v4 import; 전역 active 해석 | 네 import 성공, row model_name 각각; `_require_path_limit`는 회사 identity 둘에만; demo-v1·hp-v1 전역 active 거부, v5 허용 | 단위+PG |
| T4 | 회사 preview: hp-v1 row / demo-v1 row / identity가 집합 밖인 codex 정책(v5) | 200 `model=gpt-6-luna, reasoning_effort=high` / 503 `model_binding_invalid` / 503 `analysis_policy_unavailable`(검사 순서 고정) | PG 통합 |
| T5 | NULL 계보 preview·create·attempt: v4 활성 / v5 활성 / 기능 off | 503 `model_binding_invalid` / 200(기존 end-to-end 유지, fixture를 v5로) / 기존 `service_unavailable` | PG 통합 |
| T6 | worker claim: legacy 정책에 고정된 승인 attempt / v5 attempt / hp-v1 attempt | legacy는 runner 호출 0·attempt failed `model_binding_invalid` / v5·hp-v1은 실행, hp-v1은 회사 분기·slice 검증 통과, invocation metadata cli_version 0.162.1·reasoning high | PG 통합 |
| T7 | attempt view·승인 감사 safe_metadata | 정책 row 값; legacy attempt는 저장 값(gpt-5.6-luna/xhigh) 그대로 | PG 통합 |
| T8 | 가정 분석: preview `input.scenario.settings`·감사·worker `execution_config_changed`/`model_binding_invalid` | gpt-6-luna/high; legacy settings가 저장된 run은 호출 0으로 종결 | PG 통합 |
| T9 | 회사 e2e·binding 테스트의 가짜 runner | `cli_version` 0.162.1로 갱신, 순서 고정 code 목록 재도출 | PG 통합 |
| T10 | 프런트 build + `luna-deep-review.spec.ts`·`company-review.spec.ts`·가정 분석 spec | `gpt-6-luna · high · codex-exec` 표시, Request 문구에 모델명 없음→preview 뒤 settings 표시, fixture 갱신 | frontend |
| T11 | 격리 스택 smoke(수동·건별 승인) | 컨테이너 `codex --version`=0.162.1, hp-local overlay로 교체, hp-v1 row로 승인된 1건 attempt metadata `model=gpt-6-luna` | 외부 의존 |

## 컨벤션 반영 항목

`luna_identity` 상수 이름, `COMPANY_POLICY_IDENTITIES`, "정책 모델 ≠ runner identity → `model_binding_invalid`" 규칙, v5·hp-v1 파일, `docker-compose.hp-local.yml`·`BIDOPS_DEMO_CODEX_RUNNER_IMAGE` → contracts.md ADR-0069 절·DEMO-03 정책 줄, operations.md 격리 스택 절(HP-03에서 정리해도 된다).
