# 사용자 gold 10건 대조 인수 — spec

- 기능 ID: `RL-05-gold-acceptance`
- 근거: [intent.md](./intent.md). **계약 원본은 [HP-06 spec](../../../HP/features/HP-06-gold-acceptance/spec.md)**("정본·계약"·"측정과 사람 판정"·"actual·차단 조건 대응 계약") — 이 문서는 그 계약을 채택하고 아래 "루트랩 재명세 차이"만 바꾼다. 기준 수치는 `acceptance-criteria.approved.v1.json`(2026-10-15 사용자 확정)을 그대로 쓴다.
- 작성일: 2026-10-16 (같은 날 독립 검사 1차 17건 반영)

## 큰 틀 문서와의 관계

- 인용하는 절: HP 계약 §9, HP-06 spec 전체, RL-03 spec(attempt·`card_analysis_stage`·`verdict_request`·policy identity), RL-00 spec(graph_sha256·온톨로지 rl-v2), model-quality-gate.md(채점은 제품 밖·`scoring_input_sha256` 관례).
- 이 문서에서 새로 확정하는 항목: 표본 구성·holdout 규칙, binding 교체, 도구 이름·위치, 디렉터리 구조, 작성 시각 검사, 인수 기록 파일.
- 큰 틀 문서 수정이 필요한 항목(STEP-005): model-quality-gate.md "RL 판정 gold 인수" 절, operations.md 평가 절차, HP 계약 §9 주석, ADR.md 한 줄.

## 루트랩 재명세 차이 (HP-06 대비)

| 항목 | HP-06 | RL-05 |
|---|---|---|
| 표본 | 선정 10사업·11원문·541카드(가상회사 기준) | **실제 수집 사전규격 10건**(사용자가 RL-01 추천에서 고름; DB에 공고·첨부·묶음·구조·manifest가 있는 것만). fixture 4건(외교부·남양주·강원대·서울교육청)은 DB 공고가 아니라 RL-03 attempt를 만들 수 없으므로 gold 표본에서 제외하고 RL-03 단위 테스트 fixture로만 쓴다. 폴리텍은 RL-03 smoke 노출로 제외. `selection.v1.json` = `{schema_version:"bidops.rl-evaluation-selection.v1", documents:[{document_id, notice_id:int, opportunity_id:int, source_sha256, structure_id, manifest_id, title, agency}], company_sha256, ontology_sha256, selected_on}`(`notice_id` 필수) |
| binding | `company_sha256`=basis 파일 bytes | `company_sha256` = RL-00 활성 `graph_sha256`(HP-06의 "DB graph SHA 금지"를 의도적으로 뒤집음, §9 주석), `ontology_sha256` = 제품 `KnowledgeOntologyVersion.sha256`(정규화 payload sha; FrozenProvenance 값과 같음), `sources_sha256` = 문서별 `(DocumentStructure.payload_sha256, page_map_sha256)` 정렬 목록의 canonical sha — page map은 `prespec_v4_pdf_snapshot.para_page_map_sha256`(없으면 null로 넣음) |
| 독립성 | (A) 미노출 평가자 또는 (B) holdout | 홀드아웃 규칙: 선정 10건은 `verdict_request`에 `status=rejected, reason=gold_holdout, opportunity_id`를 미리 넣는다. RL-03 자동 트리거 조건 (7) "그 공고에 `rejected·gold_holdout` 행이 없음"(RL-03 spec에 추가)이 막고, gold `check` 통과 뒤 수동 `verdict-requests`가 holdout 행을 `started`로 바꿔 해제한다. 선정이 끝나기 전에는 `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`를 유지한다(operations 절차·설정 표). `written_before_model_output=true`는 **gold `authored_at`(ISO-8601, tz 포함) < 그 공고 `deep_review.created_at`(첫 RL review)**을 export가 검사해 거짓이면 `gold_after_model` |
| 정책·상태 필터 | `analysis-policy-hp-v1`·unmeasured_reference | RL identity(`analysis-policy-luna-rl-v1`~`-v6`(= `RL_POLICY_IDENTITIES`; v2 결정 B23, v3 B30, v4 B33, v5 B35, v6 B37))·`unmeasured_reference`·completed만 |
| 도구 | `hp_prepare.py`(`export\|coverage\|blank-gold\|gold-check\|score\|graph-score`, positional + `--out <파일>` exclusive create, 출력이 worktree 안이면 거부) | `scripts/rl-gold.py` 서브커맨드 `export-cards\|blank-gold\|gold-check\|score`(hp_prepare 함수 복사, `coverage`·`graph-score` 제외). 서명: `export-cards --cards-pack <dir> --out <file>`, `blank-gold --cards <file> --selection <file> --out <file>`, `gold-check --gold <file> --selection <file>`, `score --gold <file> --prediction <file> --criteria <file> --out <file>`. `--out`은 exclusive create; worktree 검사는 "git-ignored 경로면 허용"으로 완화(`.sdlc/local-runtime`은 `.git/info/exclude`). criteria 파일은 HP 경로를 그대로 읽는다(동일 bytes, sha `e7148fb4…`). schema_version 전부: `bidops.rl-preparation-cards.v1`, `bidops.rl-human-gold.v1`, `bidops.rl-gold-check.v1`, `bidops.rl-preparation-score.v1`, `bidops.rl-condition-alignment.v1`, `bidops.rl-evaluation-export-receipt.v1`, `bidops.rl-evaluation-actual.v1`(HP-06 키 동일). cards pack(구조·page map JSON)은 제품 CLI `export-evaluation --cards --selection <file> --out <dir>`이 bidops-local DB·객체 저장소에서 읽기 전용으로 꺼낸다(`<document_id>.structure.json`·`<document_id>.para_page_map.json`) |
| 디렉터리 | `.sdlc/local-runtime/hp-evaluation-<date>/` | `.sdlc/local-runtime/rl-evaluation-<date>/{selection.v1.json, cards/, gold.v1.json(단일 파일, `documents[10]` + 최상위 annotator·authored_at·company_sha256·ontology_sha256 — hp_prepare 구조), actual.v1.json, alignment.v1.json, prediction.v1.json, receipt.json, acceptance.json}` |
| 인수 기록 | 외부 artifact(decision null 생성) | `acceptance.json` = `{schema_version:"bidops.rl-acceptance.v1", criteria_sha256, selection_sha256, gold_sha256, actual_sha256, alignment_sha256, prediction_sha256, scoring_tool_sha256, scoring_input_sha256(= HP-06 정의: receipt + criteria sha + tool sha의 canonical sha — score 함수의 내부 값은 쓰지 않는다), metrics:{verdict_correct:int, verdict_total:int, blocking_recall:float|null, card_accuracy:float|null, critical_false_met:int|null, precision_unmatched_count:int}, adjudication_file_sha256, decision: accept|reject|defer|null, decided_by, decided_at, reason}`. 도구는 `decision=null`만 생성 |
| attempts manifest | 미정 | `--attempts` 없이 **selection에서 유도**: 문서별 "정책 rl-v1·`unmeasured_reference`·completed인 최신 attempt(`approved_at` 기준)". 없으면 그 문서는 `missing_attempt`로 export 거부. `quality_status`는 preview `provenance_jsonb`에서 읽는다 |

그 밖(gold 필드·카드 상태 10개·foreign block 거부·alignment·prediction·receipt·불일치 분류 enum·exit code·분모 0 미측정)은 HP-06 spec 그대로다.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| 기준 수치 | | 8/10 · 0.8 · 0.7 · 0 | 고정 | criteria v1, 사용자 확정 |
| `RL_EVALUATION_DIR` | path | `.sdlc/local-runtime/rl-evaluation-<date>/` | | Git 밖 |

## 상태 값과 실패 처리

- gold `status=human_completed`, decision enum, 불일치 분류 enum(HP-06). 새 오류 code(도구): `gold_after_model`, `holdout_violated`(선정 공고에 gold `authored_at` 전 RL review 존재), `selection_mismatch`, `missing_attempt`. 모든 CLI 오류는 exit 2 + stdout `{"error": code}`(기존 관례).

## 저장

DB 없음. 외부 파일·sha256. Git에는 `docs/validation-runs/<날짜>-rl/RL-05/README.md`(비민감 sha·결과 위치·metrics)만.

## 인터페이스(CLI·UI·API)

- `scripts/rl-gold.py export-cards|blank-gold|gold-check|score`(위 서명), `python -m app.deep_review.cli export-evaluation (--cards | --actual) --selection <file> [--gold <file> --condition-alignment <file>] --out <dir>`. UI 없음. 외부 호출 없음.
- `verdict_request` holdout 행은 RL-03 CLI `drain-verdict-queue --hold <notice_id,…> --reason gold_holdout`(RL-03 CLI 옵션; RL-05가 추가)로 만들고, RL-03 트리거 조건 (7)이 읽는다.

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 실제 수집 10건(fixture 제외) | fixture 4건은 DB 공고·묶음·구조가 없어 RL-03 attempt 불가(독립 검사); 로컬 원문 등록 경로를 새로 만들지 않음 | fixture 적재 경로 신설 |
| 폴리텍 제외 | RL-03 smoke 노출로 blind 불가(HP-06의 같은 지적) | 미노출 평가자 |
| holdout을 `verdict_request.rejected`로 + RL-03 조건 (7) + 선정 전 AUTO_START=false | 데이터와 플래그 두 겹으로 사람 실수 방지 | 플래그만 |
| 작성 시각 < 첫 attempt 검사 | "모델 출력 전 작성" 선언을 기계로 확인 | 선언만 |
| HP 도구 이관(복사) | HP 파일은 종료 기록, 제품 밖 스크립트 관례 | HP 디렉터리에서 실행 |
| 기준 수치 재사용 | 2026-10-15 사용자 확정, 변경 요청 없음 | 재산정 |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | `export-cards`·`blank-gold`·`gold-check`: 10건 미만·카드 10개 중복·foreign block·binding 불일치·`authored_at` 형식(ISO tz)·git-ignored 출력 경로 허용 | 거부 code / 허용 | 단위(`tests/test_rl_gold.py`, 저장소 루트 tests 관례) |
| T2 | export: `--cards`(구조·page map 추출)·`--actual`(selection 유도 최신 attempt, 정책 다름·mock·running·`missing_attempt`·`gold_after_model`·`holdout_violated`) | 거부/분리, 채점 대상 아님 | 단위(SQLite fixture) + PG 1건 |
| T3 | score 경계(8/10·0.8·0.7·분모 0·critical null) | 정확, 미측정 보존 | 단위 |
| T4 | alignment 미작성·임의 gold ID·false positive | HP-06 T5와 동일 | 단위 |
| T5 | 실제: 사용자 gold 10건 + RL-03 실제 attempt 10건 | 채점·사람 결정; 미완료면 `validating` 유지 | 수동(real_data_run) |

## 컨벤션 반영 항목

- schema 8종(위 열거), 도구 `scripts/rl-gold.py`·`export-evaluation --cards|--actual`, 오류 code 4, `verdict_request.reason=gold_holdout`, RL-03 트리거 조건 (7), roadmap RL-05 행("fixture 5 + 실제 5" → "실제 수집 10").
