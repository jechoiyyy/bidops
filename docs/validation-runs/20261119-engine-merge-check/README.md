# 2026-11-19 bid-deep-agent 엔진 병합 확인

사용자 요청("bid-deep-agent가 제대로 병합되었는지 확인하고 수정이 필요한 부분까지")에 따른 읽기 전용 조사 기록이다.
대상은 [ADR-0074](../../tracking/decisions/0074-deep-engine-development-baseline.md)·RL-09로 들여온
`packages/bid-deep-engine/`와 그 통합 코드(`engine_runs` API·worker 슬롯·화면 패널)다. 모델 호출 0회, 두 저장소 무변경,
운영 쓰기 0회. 일회용 PostgreSQL은 제거했다. 시점별 증거이며 품질 근거가 아니다.

조사는 구현에 관여하지 않은 컨텍스트가 했고, 리더가 파일 대조 스크립트 재실행, 지적된 코드 줄, 운영 API 노출을 직접 확인했다.

## 1. 결론

- **병합 자체에는 결함이 없다.** 원본 `bid-deep-agent` commit `7ad9283`의 파일 40개 중 39개가 import 이름만 바꾼 것과 같고,
  나머지 1개(`analysis/llm.py`)는 선언된 대로 전송 부분을 뺀 것이다. 원본은 그 commit 이후 움직이지 않았다.
- **통합 코드에는 결함이 있다.** 가장 큰 것은 새 실행이 항상 "이전 기준 분석"으로 표시되는 것(D1)과, 회사의 확인된 사실이
  엔진에는 전부 미확인으로 들어가는 것(D2)이다.
- **실사용 전제는 하나도 없다.** 엔진의 모델 호출을 Luna로 보내는 어댑터, 프롬프트·스키마 계약, 정책 파일, 승인 경로가 없다.
  회사 지식(LLM wiki)은 BidOps 저장소에 없다. 지금 도는 것은 모델을 대신하는 mock이다.
- **엔진과 RL 카드 판정 중 어느 쪽이 나은지는 측정된 적이 없다.** 같은 정답 10건에서 둘 다 엄격 기준 차단 조건을 0/7로 놓쳤다
  (엔진 수치는 원본 환경에서 잰 것이라 통합 엔진의 성능이 아니다).

## 2. 병합 충실도

`fidelity.py`(이 디렉터리)가 `UPSTREAM.json`의 파일마다 원본 commit의 내용과 들여온 파일을 대조한다.

```bash
python3 docs/validation-runs/20261119-engine-merge-check/fidelity.py
```

| 결과 | 파일 수 |
|---|---:|
| 기록된 sha256 = 원본 commit의 파일 hash | 41개 항목 전부(고유 40) |
| import 이름 변경 뒤 원본과 동일 | 40개 항목(고유 39) |
| `analysis/llm.py` | 선언된 발췌. 오류·기록 클래스는 원본과 같고 전송 클래스·JSON 파싱 도우미·client factory는 뺐다 |

manifest의 문제:

- `src/bidops/analysis/spend.py`가 두 번 들어 있다.
- 대체한 파일(`config.py` stub, 오프라인 `tracing.py`, `__init__.py` 5개)과 새 파일(`adapter.py`, `runner.py`,
  `engine_tests/test_adapter.py`)의 hash가 없다. README는 "모든 들여온 파일의 sha256을 기록한다"고 적는다.

들여오지 않은 원본 모듈:

| 모듈 | 판단 |
|---|---|
| `claude_cli.py`, `gateway.py`, `llm.py`의 전송 부분, Langfuse tracing | 의도된 제외(ADR-0074) |
| `tasks/*`, `a2a/*`, `agent/*`, `service/*`, CLI | 의도된 제외(SQLite 큐·CLI·A2A·chat 미이식) |
| `ingest/{discover,hwp,hwpx,pdf,pipeline,writer}.py` | 사실상 의도된 제외(BidOps 문서 구조가 대신한다). 문서에 명시는 없다 |
| `analysis/regate.py`(모델 없이 게이트·점수·권고 재계산) | **공백.** ADR·manifest에 언급이 없다. 없으면 회사 자료가 바뀔 때마다 전체 재실행이 필요하다 |
| `analysis/reconcile.py`, `golden.py`, `report/*`, `company/knowledge_import.py` | 범위와 일치. `golden.py`는 추출 품질 측정 때 필요해진다 |

들여온 코드가 import하는 모듈은 모두 있다. 환경변수·SQLite·네트워크를 쓰는 코드는 없다.

원본에 있던 결함은 그대로 따라왔다(원본 기록 `docs/work/_runs/rl05-reeval-20261104/result.md`):

- 요구사항 ID는 숫자 3자리여야 인식한다(`QUR-01`은 인식 못 함).
- ID가 둘 이상인 상세 표는 목록으로 재분류되어 빠진다.
- 상주 게이트는 통과 또는 위험만 내고 실패를 내지 못한다.
- 회사의 제외 조건(`no_bid_if`)은 선언만 있고 읽는 게이트가 없다.

## 3. 실행 확인

| 묶음 | 결과 |
|---|---|
| 들여온 `engine_tests` | 512 통과(원본 509 + 어댑터 3) |
| 원본 테스트 17개 파일을 들여온 코드에 대해 실행(이름 변경) | 882 통과 |
| 원본 `test_normalize`·`test_models`(임시 `writer.py` 사본 사용) | 224 + 13 통과 |
| import할 수 없는 원본 테스트 | 11개 파일(뺀 전송 상수·`typer`·`golden`·`regate` 등에 의존) |
| 백엔드 엔진 테스트, SQLite | 6 통과·8 skip |
| 같은 테스트 + 권한 테스트, 일회용 PostgreSQL | 14 통과·1 skip, 실패 0 |

정규화기·매처·전체 파이프라인의 테스트는 BidOps 안에 없다(원본 테스트를 임시로 맞춰야만 돈다).

mock 실행 한 건의 경로: 요청 검증·idempotency·회사 binding·묶음 `ready` 확인·구조 hash 고정(실제) → `engine_run` 행 +
감사 + `work_job`(실제) → worker 슬롯(실제, 조건 없이 돈다) → 격리 subprocess 90초(실제) → 표·블록 투영, 원본 정규화,
인용 검증, 게이트, 점수, 권고(실제) / **모델이 내는 사실·적합·요약은 mock** → MinIO·행 저장(실제) → 조회.

## 4. 통합이 지금 주는 것

| 항목 | 원본 단독 | BidOps 통합 |
|---|---|---|
| 입력 | 원본 HWP/HWPX/PDF, 주 문서 하나 | 확정 묶음의 **모든 문서**를 하나로 이어 붙인 구조 JSON. 참조 PDF 없음 |
| 회사 지식 | 회사 YAML + 실적 + 근거 수준 sidecar + wiki(유형 6·역량 10·규칙 4·실적 38·용어집) | RL-00 프로필 사실의 투영. **wiki는 BidOps에 없다**(`knowledge=null`) |
| 투영되는 회사 사실(v4 기준) | — | 148개 중 63개, 전부 `project:*`(실적). 상주(`staff:onsite`), 제외 분야(`excl:*`), 자격(`qual:*`), 선호(`pref:*`)는 투영되지 않는다 |
| 회사 사실의 근거 수준 | 필드마다 `confirmed` 등 | 근거 수준을 넘기지 않아 **전부 `unknown`**. 확인된 실적도 엔진에서는 미확인이다 |
| 모델이 필요한 단계 | 추출·매칭·종합(공고당 3회) | 같은 이음매. 지금은 mock |
| 화면 | HTML 보고서 | 운영 화면에서 렌더되지 않는다(개발·mock 서버와 데모 회사 경로에서만) |

## 5. 결함과 위험

| # | 내용 | 근거 |
|---|---|---|
| D1 | **새 실행이 항상 stale로 표시된다.** 엔진의 회사 hash에 BidOps `profile_sha256`을 넣는데, 준비도 계산은 투영된 엔진 프로필의 hash를 다시 계산해 비교한다. 게이트·점수·적합·종합에 `stale_stage`가 붙고 "이전 기준 분석 — 분석 다시 실행" 조건이 생긴다 | 재현(같은 hash를 넣으면 `current`), `runner.py`의 `company_input_hash=payload["profile_sha256"]` |
| D2 | RL-00의 `confirmed`가 엔진에 전달되지 않아 모든 회사 필드가 미확인이다. 미확인을 사실로 올리지는 않지만(강제 게이트 위반 아님) 엔진이 어떤 결정도 내릴 수 없다 | 투영 결과 조회 |
| D3 | 검증된 인용 하나가 그 문장이 든 **모든 블록**에 연결되어 위치가 모호해진다 | 중복 인용 탐침, `adapter.py:65-85` |
| D4 | 오류 코드가 뭉개진다. runner는 모든 예외를 `engine_pipeline_failed`로, worker는 `engine_execution_failed`로 바꾸고 로그도 남기지 않는다(코드 변경 감지·timeout·잘못된 JSON 포함) | `runner.py:212-224`, `services/engine_runs.py:507-521` |
| D5 | mock에 테스트 fixture 문장이 박혀 있다("중소기업확인서를 제출해야 한다.") | `runner.py:57` |
| D6 | 신용등급 투영이 긴 서술을 등급 칸에 넣게 된다. 지금은 그 사실이 `proposed`라 동작하지 않는다 | 값 확인, 영향은 추정 |
| D7 | 묶음의 모든 문서를 하나로 합쳐 요구사항 ID가 문서 사이에 겹칠 수 있다 | 코드 확인, 영향은 추정 |
| D8 | 실행마다 회사 프로필 전체와 묶음 전문(최대 8MiB)을 `engine_run.input_payload`에 저장하고 삭제가 막혀 있어 사본이 계속 쌓인다. API·로그로 노출되지는 않는다 | 코드·migration 확인 |
| 노출 | **엔진 API가 운영에서 열려 있다.** 백엔드 플래그가 없고 데모 차단에서도 제외돼 있다. 운영 `openapi.json`에 두 경로가 있고 목록 GET이 200을 준다(회사 미등록이라 생성은 실패). worker 슬롯도 조건 없이 돈다 | 운영 GET, `main.py:296-299` |

## 6. 실사용을 막는 것 (순서대로)

1. **전송 없음.** 엔진의 `parse` 호출을 codex-exec Luna로 보내는 어댑터가 없다. 원본의 JSON 추출·스키마 검증·거절/잘림 처리가
   전송과 함께 빠져 다시 써야 한다. 엔진용 계약 스키마·정책 파일·승인 binding·전송 미리보기·건별 감사 경로도 없다.
2. **프롬프트 크기.** Luna 기본 상한은 100,000자다. 원본에서 정답 10건의 주 문서만 60k~111k자였고 5건이 상한을 넘는다.
   BidOps는 묶음의 모든 문서를 합치고 분할 전략 없이 한 번에 보낸다.
3. **실행 모델.** subprocess 90초·lease 120초(갱신 없음)에는 모델 호출 3회가 들어가지 않는다.
4. **fail-closed 세 곳.** live는 서비스 생성·runner·호출부에서 거부된다. 켜는 스위치가 없다.
5. **회사 등록.** 운영에 회사가 없다. 등록해도 D2와 투영 공백 때문에 상주·제외 입력은 미확인으로 남는다.
6. **코어의 품질 한계.** 상주는 위험까지만, `no_bid_if`는 읽지 않음, 파서 결함 둘. 원본이 실제 모델로 같은 정답을 잰 결과는
   reject였다(판정 5/10 = "항상 조건부" 기준선과 같음, 차단 조건 엄격 0/7·넓게 5/7).
7. **테스트 공백.** 정규화기·파이프라인·매처·전송 계약 테스트가 BidOps에 없다.

## 7. RL 카드 판정과의 관계 (근거만)

| RL이 실패한 지점 | RL 카드 판정(RL-03 + RL-10) | 통합된 엔진 |
|---|---|---|
| 요구사항 → 회사 근거 연결 | 모델이 제약을 뽑고, 결정적 대조가 허용된 사실 키·온톨로지·그래프 경로로 잇는다. 447개 중 228개가 회사 사실에 닿지 못했다 | 모델 매칭 프롬프트가 회사 프로필(실적 63건뿐, wiki 없음)을 받아 적합을 낸다. BidOps 경로에서는 측정된 적이 없다 |
| 상주 지역 | RL-10: 행정구역 표와 회사의 상주 지역 값으로 충돌 시 `gap`. 값이 v4에 없어 지금은 unknown | 통과 또는 위험만 낸다. BidOps에서는 상주 정보가 미확인이라 항상 위험 |
| 제외 분야 | RL-10: 확인된 업무 표현이 있으면 `gap`. 표현이 v4에 없다 | `no_bid_if`를 읽는 게이트가 없다. 투영도 안 된다 |
| 미확인 사실 | `proposed`·unknown은 절대 충족이 되지 않는다 | 확인된 사실만 투영하지만 근거 수준이 없어 전부 미확인 |
| 같은 정답의 기존 측정 | 판정 3/10, 차단 0/7, 카드 447개 전부 unknown | 원본 환경: 5/10, 엄격 0/7, 넓게 5/7, 요구사항 0건 문서 2개. **통합 엔진의 수치가 아니다** |

어느 쪽이 나은지 가리려면 같은 정답 10건·같은 BidOps 묶음·같은 회사 값(v4 + 상주 지역 목록 + 제외 업무 표현)으로 두 경로를
한 번씩 돌려 미리 고정한 기준으로 채점해야 한다. 엔진 쪽은 D1·D2와 상주·제외 투영, Luna 어댑터, 전송 승인이 먼저 필요하다.
정답 10건의 묶음은 종료된 `bidops-local` volume에만 있다.

## 8. 필요한 수정

| 구분 | 수정 | 크기 |
|---|---|---|
| 병합 | manifest: 중복 `spend.py` 제거, 대체·신규 파일의 hash 기록 | 아주 작음 |
| 통합 | D1: 투영된 엔진 프로필의 hash를 넘긴다(BidOps hash는 따로 기록) | 작음 |
| 통합 | D3: 인용 위치를 인용된 절·블록으로 좁힌다 | 작음 |
| 통합 | D4: 오류 코드를 보존하고 안전한 오류 종류를 로그에 남긴다 | 작음 |
| 통합 | D5: mock에서 fixture 문장 제거 | 아주 작음 |
| 통합 | 엔진 API·worker 슬롯에 백엔드 플래그(기본 off), 운영 번들의 패널 import 제거 | 작음 |
| 통합 | import 가능한 원본 테스트 17개 + normalize·models 테스트를 들여온다 | 작음 |
| 통합 | D2: RL-00 상태·인용에서 근거 수준을 만들어 확인된 사실이 `confirmed`로 들어가게 한다 | 중간 |
| 통합 | 상주·제외·자격·지역의 투영 표, 신용등급 파싱(D6) | 중간 |
| 통합 | 주 문서만 볼지 묶음 전체를 합칠지 정하고 구현(D7) | 작음~중간 |
| 통합 | `input_payload` 사본 보존 정책(D8) | 작음 + 결정 |
| 실사용 | Luna 어댑터, 엔진 계약·스키마, 프롬프트 크기 전략, 정책 파일·승인·미리보기·감사, 실행 모델 재설계, live 스위치와 품질 표식 | 각각 중간~큼 |
| 실사용 | 코어 결함(2자리 ID, 다중 ID 표, 상주 실패 의미, `no_bid_if` 사용) — 원본과 갈라지는 결정 필요 | 중간 |
| 실사용 | 운영 회사 등록, 상주 지역 목록과 제외 업무 표현(RL-10과 공유) | 사람이 주는 값 |

## 9. 사용자가 정할 것

1. 엔진의 역할. 설계고도화안 §4 E에는 2026-11-19 "RL 카드 판정 정본"으로 적혀 있다. 선택지는 제거, mock 참조로 유지,
   결정적 부분(정규화기·게이트)만 재사용, 또는 같은 정답 비교 측정 뒤 정본 확정이다.
2. 엔진에 Luna 전송을 승인하고 같은 정답으로 다시 잴지(비용·승인 범위).
3. RL-00 → 엔진 회사 프로필 대응과, wiki(대부분 추정 등급 문서)를 BidOps에 들일지. 회사 지식 정본은 하나여야 한다.
4. 상주 지역·제외 분야를 위험이 아니라 차단으로 볼지(원본 게이트 의미를 바꾼다).
5. 파서 결함을 들여온 사본에서 고칠지 원본에서 먼저 고칠지.
6. 엔진 API를 운영에 계속 열어 둘지, 입력 사본을 얼마나 보존할지.

## 10. 하지 않은 것

- 통합 엔진의 실제 모델 결과(전송이 없다).
- 운영이 HWPX 구조를 어느 추출기로 만드는지 확인.
- 종료된 `bidops-local` volume의 자료 열람.

## 11. 수정 결과 (2026-11-19, 브랜치 `fix/engine-integration-defects`)

엔진 역할 결정(§9-1)과 무관한 결함만 고쳤다. 모델 호출 0회, migration 없음, 운영 무변경. 엔진은 계속 `mock_reference`이며
이 수정은 실제 분석에 쓸 수 있다는 근거가 아니다. 미병합·미배포다.

| 항목 | 결과 | commit |
|---|---|---|
| manifest | 중복 `spend.py` 제거. `files`(원본 bytes의 sha256 + adaptation)는 의미 유지, `replaced_files`(config stub·오프라인 tracing·`__init__` 5개)와 `authored_files`(adapter·runner·그 테스트)는 들여온 bytes의 sha256. `engine_tests/test_manifest.py`가 모든 파일이 한 번씩 있는지와 hash를 원본 저장소 없이 검사한다. `fidelity.py`는 패키지 경로를 인자로 받는다 | `60e8ec0` |
| D1 | 엔진이 준비도에서 다시 계산하는 `CompanyEvidenceView(profile).company_input_hash`를 넘긴다. BidOps `profile_sha256`은 `analysis.company_projection.source_profile_sha256`에 따로 남는다 | `4187b0f` |
| facts `unknown` 원인 | **같은 종류의 통합 결함이었다.** facts 단계 stamp는 `rfp.json` 옆 `bundle.json`으로 입력 지문을 만드는데(`provenance.rfp_input_payload`) runner가 그 파일을 쓰지 않아 stamp가 버려지고 `legacy_metadata`(unknown)로 읽혔다. runner가 이미 만든 bundle을 같이 쓴다. 새 실행의 사유는 `missing_fits`(mock 적합 미측정)만 남는다 | `4187b0f` |
| D3 | 인용 위치를 엔진이 인용한 절의 블록에서 찾는다. 인용 절이 없거나 그 안에 없을 때만 전체를 찾고, 모든 위치에 `location_status=exact|ambiguous`·`basis=cited_section|whole_input`을 붙인다 | `c5d6a8a` |
| D4 | runner는 정의된 코드(`engine_live_not_approved`·`structure_unavailable`·`invalid_table_coordinates`·`table_too_large`·`input_too_large`·새 `engine_input_invalid`)를 보존하고 나머지만 `engine_pipeline_failed`. worker는 `input_hash_mismatch`·`engine_version_changed`·`engine_unavailable`·`engine_timeout`·`engine_process_failed`·`engine_output_invalid`를 그대로 저장하고 예상 밖 오류만 `engine_execution_failed`. 실패마다 `engine_run.failed` 로그(run id·worker id·코드·예외 클래스 이름만) | `3b3304f` |
| D5 | mock은 어떤 문장으로도 참가자격을 만들지 않는다. 게이트 경로는 테스트가 `MockRule`로 명시해 돌린다 | `49710b8` |
| 노출 | `BIDOPS_ENGINE_ANALYSIS_ENABLED`(기본 false). 꺼지면 생성 503 `engine_analysis_disabled`(재요청 replay보다 먼저), worker 슬롯은 claim하지 않음, 조회는 감사용으로 유지. `GET /api/feature-flags`에 `engine_analysis` 추가. compose·env 파일에는 넣지 않았다 | `f6e3b00` |
| 테스트 공백 | 원본 테스트 16개 파일(+이미 있던 2개)·`report_factory`·합성 fixture를 들여와 `engine_tests` 1,493개. `writer`는 원본 모듈 대신 테스트 전용 `ingest_writer.py`. 실회사 프로필 fixture(`tests/fixtures/knowledge/profile.yaml`)는 복사하지 않아 그것을 읽는 `knowledge_lint`·`knowledge_load`·`past_labels`는 뺐다 | `b7cd802` |

남은 것: 운영 번들의 화면 패널 import 제거(프런트엔드, 다른 작업자가 `engine_analysis` 플래그로 처리), D2(근거 수준 전달),
상주·제외·자격·지역 투영과 D6(신용등급), D7(묶음 합치기), D8(`input_payload` 보존), `regate.py` 공백, §6의 실사용 전제 전부,
코어 파서 결함. 이들은 §9의 사용자 결정 뒤에 다룬다.

검증(이 브랜치, 2026-11-19): `engine_tests` 1,493 passed. 백엔드 `test_engine_runs.py`·`test_engine_runs_api.py`·
`test_feature_flags.py`·`test_runtime_database_privileges.py`를 일회용 PostgreSQL 17.11로 83 passed·1 skipped(SQLite 변형의
PostgreSQL 전용 검사). 새 회귀 테스트는 수정 전 코드에서 실패하는 것을 확인했다. `fidelity.py`는 manifest의 원본 파일 76개 모두
`claim==upstream`이다.
