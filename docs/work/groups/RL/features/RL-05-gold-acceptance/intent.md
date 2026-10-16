# 사용자 gold 10건 대조 인수 — intent

- 기능 ID: `RL-05-gold-acceptance`
- 상위 항목: roadmap §RL 표 6행, mission "성공 기준"(G2 gold 10건 대조), HP 공통 계약 §9(기준 재사용), [HP-06 spec](../../../HP/features/HP-06-gold-acceptance/spec.md)(도구·계약 재사용), [acceptance-criteria.approved.v1.json](../../../HP/preparation/acceptance-criteria.approved.v1.json)
- 크기: M — 제품 패키지에 읽기 전용 export CLI 1개와 RL-03 CLI 옵션 1개(`--hold`), 제품 밖 채점·준비 스크립트 이관, Git 밖 평가 디렉터리, 사람 작성·사람 인수. 외부 호출 없음.
- 작성일: 2026-10-16

## 문제

RL-03 판정이 "맞는지"를 모델 출력을 본 뒤 사람이 평가하면 편향된다. 사용자가 모델 출력 전에 쓴 정답 10건과 대조해 판정 일치·차단 조건 recall·카드 상태 일치를 재야 하고, 그 전까지 RL-03 결과는 참조 실행(`unmeasured_reference`)일 뿐 품질 근거가 아니다. HP-06의 도구·기준은 가상회사 binding에 묶여 있어 그대로는 쓸 수 없다.

## 기대 결과

- 사용자가 실제 수집 사전규격 10건마다 모델 출력을 보기 **전에** gold(판정·차단 조건·충족/부족·주의·카드 상태 표본 10)를 쓴다. fixture 4건은 DB에 공고·문서 묶음이 없어 판정 attempt를 만들 수 없으므로 표본에서 빼고(RL-03 단위 테스트용), 폴리텍은 RL-03 실제 smoke(T12)에 쓰이므로 뺀다.
- RL-03 실제 attempt 10건을 읽기 전용 export → 사람이 차단 조건 alignment를 쓴 뒤 → 제품 밖 채점 스크립트가 네 지표를 계산한다. 기준(HP §9·criteria v1): 판정 일치 ≥ 8/10, 차단 recall ≥ 0.8, 카드 상태 일치 ≥ 0.7, 명백한 필수자격 미충족을 충족으로 판단 0건. 분모 0은 미측정.
- 최종 인수(accept|reject|defer)는 사람이 적고, 그 전까지 RL-05는 `validating`에 머문다.

## 유즈케이스

| 유즈케이스 | 실행 방법 | 확인 기준 |
|---|---|---|
| 카드 pack·빈 gold 양식 | `python -m app.deep_review.cli export-evaluation --cards --selection <file> --out <dir>` → `python scripts/rl-gold.py export-cards --cards-pack <dir> --out cards.json` → `blank-gold --cards cards.json --selection <file> --out gold.v1.json` | 10건 양식(단일 파일), 모델 답 없음, binding(graph sha·온톨로지 sha·sources sha) 포함 |
| gold 검사 | `rl-gold.py gold-check --gold gold.v1.json --selection <file>` | 10건 전부·카드 ID 10개 상이·foreign block 거부·`authored_at` ISO |
| 모델 결과 export | `python -m app.deep_review.cli export-evaluation --actual --selection <file> --gold gold.v1.json --condition-alignment alignment.v1.json --out <dir>` (bidops-local, 읽기 전용) | actual·prediction·receipt, 상태 completed·policy rl-v1·`unmeasured_reference`만, `gold_after_model`·`holdout_violated` 거부 |
| 채점 | `rl-gold.py score --gold --prediction --criteria --out` | metrics 4개·unmatched 목록, decision=null |
| 인수 기록 | 사람이 `acceptance.json`의 decision·decided_by·reason 기입 | `status.json` 증명 `real_data_run`에 파일 sha 기록 |

## 선행·후속 기능

- 선행: `RL-03-fit-verdict`(채점 대상 attempt·`verdict_request`·트리거 조건 (7)), `RL-00`(회사 binding sha), `RL-01`(실제 수집 10건은 브리핑 추천에서 사용자가 고른다).
- 후속: 없음(인수 결과는 RL-03 품질 근거·운영 전환 판단 입력).

## 영향 범위

- 모듈·컴포넌트: `scripts/rl-gold.py`(HP `hp_prepare.py` 함수 복사·binding 교체·worktree 검사 완화), `web/backend/app/deep_review/cli/export_evaluation.py`(신규, `--cards`·`--actual`), `cli/drain_verdict_queue.py --hold`, 평가 디렉터리 `.sdlc/local-runtime/rl-evaluation-<date>/`(Git 밖), `tests/test_rl_gold.py`(저장소 루트).
- 큰 틀 문서의 절: HP 계약 §9 머리 주석(RL-05가 루트랩 기준으로 실행), docs/model-quality-gate.md에 "RL 판정 gold 인수" 절, operations.md(평가 절차), ADR.md 한 줄.
- 데이터·저장소: DB 변경 없음. 외부 디렉터리 파일(gold·actual·alignment·prediction·receipt·acceptance)과 sha256.
- 외부 서비스·호출: 없음(모델 실행은 RL-03 경로가 이미 끝낸 attempt를 읽기만).

## 제약

- (공통) feature.json constraints. 참조 실행을 운영 품질로 승격 금지, 원문·사람 답·모델 답은 Git 밖.
- (기능별) gold는 모델 출력 전에 사용자가 쓴다(`written_before_model_output=true`, 작성 시각 < attempt 생성 시각 검사). 미작성 `null`과 확인 후 없음 `[]` 구분. gold 수정은 새 버전 디렉터리. 자동 승인 없음.

## 범위 밖

브리핑 정밀도·채택률 측정(운영 지표, RL 이후), 제안서 품질 채점(RL-04 T11로 고정), 추가 표본 확대, Neo4j, HP 가상회사 표본 재사용.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 표본 구성 | roadmap "fixture 5 + 실제 5" | fixture는 DB 공고가 아니라 attempt 불가(코드), 폴리텍은 smoke 노출 | 실제 수집 10건. roadmap 행 갱신(STEP-005). **사용자 확인 대상으로 보고** |
| 회사 binding | HP-06 `company_sha256`=basis 파일 | RL-00 그래프 버전 | `company_sha256`=활성 graph_sha256, `ontology_sha256`=rl-v2 canonical |
| 도구 위치 | HP preparation 디렉터리 | 제품 밖 스크립트 관례(`scripts/score-c2-gate.py`) | `scripts/rl-gold.py`로 이관, HP 파일은 그대로 둠 |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| 실제 10건 선정 시점 | 구현 중(gold 작성 전) | 사용자가 RL-01 브리핑에서 채택한 사전규격 중 문서 준비 ready·개요 completed인 것부터 고른다. 선정이 끝날 때까지 `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`를 유지하고, 선정 뒤 holdout 행(`verdict_request rejected·gold_holdout`)을 넣은 다음에야 자동 시작을 켠다. gold 완료 뒤 수동 요청으로 분석한다 |
