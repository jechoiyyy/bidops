# 제안서 초안(요구사항 대응표·절 초안·PDF) — spec

- 기능 ID: `RL-04-proposal-draft`
- 근거: [intent.md](./intent.md), RL-03 spec(전송 승인·unit·compare·verdict·gate 순서·cap·감사), RL-00 spec(사실 노드), RL-02 spec(hook·탭), bid-procedure §4·§5, ui-spec §3·§4.5, ux-review §5 결정 5·6
- 작성일: 2026-10-16 (같은 날 독립 검사 1차 20건 반영)

## 큰 틀 문서와의 관계

- 인용하는 절: RL-03 spec "정책 단위 사전 승인"(테이블·CLI·검사 순서·감사 이벤트)·"REST"(verdict view)·HP-03 "단계 wire 계약"(Evidence·unit·quote 규칙), DEMO 계약 §9(오류·gate), contracts.md 공통 REST 규칙·"심층 검토 내부 artifact"(객체 저장 hash 규칙), ui-spec §3(상태 pill·버튼)·§4.5, bid-procedure §5(목차·배점·제안서 규칙).
- 이 문서에서 새로 확정하는 항목: 절 6개와 §5 대응, 문장 계약(출처·표식), 생성 입력·정책·호출 수, 검증 규칙(금지 내용), 저장 4 테이블, REST 6개, PDF 렌더 규칙, 화면 상태.
- 큰 틀 문서 수정이 필요한 항목(STEP-009): contracts.md(REST·DB·정책·PDF artifact), business-rules.md "제안서 초안" 절, operations.md(승인 행·폰트·cap), tech-stack(`reportlab`·Noto Sans KR), ui-spec §4.5(절 대응표 주석), ADR.md 한 줄.

## 입력·출력 계약

### 절과 목차 대응

| key | 화면 이름 | bid-procedure §5 대응 | 입력 |
|---|---|---|---|
| `overview` | 제안 개요 | Ⅰ 배경·목적·범위·특징·기대효과 | unit `overview|schedule|budget` segment 추출, 공고 메타 |
| `track_record` | 사업수행 실적 | Ⅱ-3 사업수행 실적, Ⅱ-4 주요사업·기술 | `project:*`(confirmed)·`cert:*`·특허(confirmed) |
| `strategy` | 수행 전략 | Ⅲ-1 수행 전략, Ⅲ-5 제약(접근성·호환성·표준프레임워크) | unit type 기술·기능·보안 + compare |
| `requirements` | 요구사항 수행방안 | Ⅲ-2 기능 요구사항별 수행 방안 | 모든 요구사항 카드 unit + compare + verdict matrix |
| `operations_sla` | 운영·SLA | Ⅲ-3 운영·유지관리, Ⅲ-4 보안, Ⅴ 지원 | unit type 운영·성능SLA·보안·계약 |
| `organization` | 수행조직 | Ⅳ-2 수행조직(인력 수치 제외), Ⅳ-3 보고·산출물 | `staff:*`(confirmed, 총원·역할만; 투입 인원은 빈 자리) |

Ⅱ-1·2(일반현황·경영실태)·Ⅳ-1(추진 일정)·가격은 생성하지 않는다(사람·서식).

### 문장 계약 `bidops.proposal-section.v1`

```
Section = { section_key, title, paragraphs: [{ paragraph_id, heading: string|null, sentences: Sentence[] }],
            requirement_links: [{ unit_id, paragraph_id }] }
Sentence = { sentence_id: string(UUID), text: string(1..400자), kind: statement|placeholder|proposed_figure,
             sources: Source[], placeholder_hint: string|null }
Source = { kind: requirement_unit|company_fact|notice_meta, ref: string(unit_id | fact_key | meta_key), quote: string }
```

- `statement`는 `sources` ≥ 1 필수. `placeholder`는 `sources=[]`·`placeholder_hint` 필수(예: "실적증명서 발급 건 목록", "투입 인력 수", "가격"). `proposed_figure`는 숫자가 포함된 제안값(예: "응답시간 3초 이내")으로 `sources` ≥ 1이면서 화면·PDF에 warning 표식.
- `quote`는 `requirement_unit`이면 그 unit block의 부분문자열(HP-03 Evidence 규칙), `company_fact`면 그 fact의 `label` 또는 **value의 scalar 값들을 `" · "`로 이은 문자열**(객체 value는 키 정렬 순 scalar만; null 제외)의 부분문자열, `notice_meta`면 공고 메타 값 5개(`title`·`agency`·`deadline_at`·`method`·`estimated_price`; 추정가격 인용은 허용되며 금지 내용 검증의 "원문 숫자 인용" 예외에 든다)의 문자열. 검증은 schema가 아니라 `proposal_validation.py`가 한다(runner `output_schema`는 oneOf/조건을 제거하므로 kind별 조건을 schema에 두지 않는다). 검증 실패는 절 `failed`.
- `requirements` 절은 RL-03 completed attempt의 모든 카드 unit(`kind=card`)을 `requirement_links`로 정확히 1회 이상 덮어야 한다(누락 0). segment unit은 다른 절에서 참조.
- 금지 내용 검증(코드): `statement`·`proposed_figure` 텍스트에 (a) 통화 금액(`\d[\d,]*\s*(원|천원|백만원|억)`), (b) 투입 인원(`\d+\s*(명|인)\s*(투입|상주|배치)`), (c) 기간·일정 약속(`\d+\s*(개월|일)\s*(내|이내)\s*(완료|구축)`)이 있고 그 숫자가 `sources`의 quote에 그대로 없으면 거부(공고 원문 숫자 인용은 허용). 거부는 절 `failed`·`proposal_forbidden_content`.
- 회사 사실은 `confirmed`만 입력에 넣는다. `proposed`·`unknown`은 입력 `missing_facts[]`(fact_key·label)로만 전달해 placeholder 힌트에 쓴다.

### 생성 입력·정책·호출

- 정책 `proposal-policy-luna-v1.json`(canonical JSON bytes): `schema="bidops.analysis-policy.v2"` 구조 재사용 — loader가 필수로 읽는 `validation`·`generation`·`stages`·`quality_status`(=`unmeasured_reference`)·`model_name`·`model_endpoint_ref`·`chunking`·`execution`·`report_schema`·`stage_schema`·`prompt_output_contract` 키를 모두 두고, `policy_identity="proposal-policy-luna-v1"`, `pipeline_version="proposal-v1"`, `purpose="proposal"`(추가 키), model/generation/execution(HP-00 identity, `timeout_seconds=900`, `review_timeout_seconds=5400`(초안 전체), `validation_repair_attempts=1`), `stages`=절 6개 순서(각 `{stage:<section_key>, instruction}`), `prompt_output_contract`에 문장 계약·금지 내용·"출처 없는 문장 금지·가격/인력/전략 수치는 placeholder"·"실회사 루트랩, proposed/unknown은 근거 아님" 규칙. `input_versions._LUNA_POLICY_FILES_BY_IDENTITY`·`luna_identity`에 identity 등록, `import-profile-policy`로 행 import, 선택 env `BIDOPS_PROPOSAL_POLICY_VERSION_ID`.
- 실행 조건(기존 gate 그대로): `BIDOPS_LUNA_DEEP_REVIEW_ENABLED=true`·`BIDOPS_REFERENCE_WORKFLOW_MODE=true`·`BIDOPS_ANALYSIS_PROVIDER!=mock`(T10 mock은 provider=mock).
- 입력 예산: contract `proposal-section-v1`의 prompt 상한 120,000자(`luna_client` 집합에 등록). `requirements` 절 입력이 넘치면 **분할하지 않고** 절 `failed`·`input_budget_exceeded`(호출 수 6 고정). 사람은 다른 절을 검토하고 requirements 절은 사람 검토로 남는다.
- 전송 승인: RL-03 `transfer_policy_approval` 행을 **이 정책 sha로 별도 발행**(`scope.purposes=["proposal"]`, `daily_cap` 기본 3 = 초안 생성 수; 절 재생성은 1/6로 센다 → 정수화: 하루 호출 상한 = cap×6 호출). gate 순서는 RL-03과 같다.
- 입력 `bidops.proposal-input.v1` 키 전체: `{schema_version, purpose:"proposal", execution_nonce, draft_id, opportunity_id, notice_id, verdict_attempt_id, verdict_input_sha256, company_binding(RL-03과 동일 구조), policy_sha256, model_name, reasoning_effort, section_key, notice_meta:{title,agency,deadline_at,method,estimated_price}, units:[RL-03 unit 중 이 절 입력], compares:[해당 unit의 Compare], verdict:{verdict, reason, checklist}, company_facts:[{fact_key,type,label,value}], missing_facts:[{fact_key,label}], toc_reference:[§5 해당 장·절 제목]}`. 노트 본문·`proposed`/`unknown` 값·운영 정보 금지(T9 payload 검사). `input_sha256`은 canonical JSON SHA, 절마다 다르다.
- 호출 수 = 6(+repair ≤ 6; cap 계산에 repair는 넣지 않는다 — 초안 1건 = cap 1, 절 재생성 = cap 1/6). 절 단위 실행은 **기존 `DeepReviewAttempt`를 쓰지 않는다**: `assumption_analysis` 패턴대로 WorkJob `job_type="proposal_section"`, `aggregate_type="proposal_section"`, aggregate_id=`proposal_section.id`, 절당 job 1개(초안 생성은 6 job을 한 transaction에서 queued로 만든다), 전용 `workers/proposal.py`의 `run_once`가 공용 슬롯 규칙(analysis worker 1 슬롯)을 그대로 따른다. `draft_in_progress` = 그 opportunity의 draft가 `queued|running`; `section_in_progress` = 그 절의 최신 revision이 `queued|running`(web이 queued 행을 INSERT하므로 판정 가능). `review_timeout_seconds=5400`은 draft 단위(첫 job claim부터 단조 시계), 초과 시 남은 job은 `failed·proposal_review_timeout`. 절 하나 실패해도 다른 절은 보존. draft `status`는 worker가 마지막 job 종료 시 갱신: 6절 모두 completed → `completed`, 하나라도 failed → `partial`(사람 검토).
- 입력 읽기 경로: unit은 verdict attempt의 `deep_review_preview.input_snapshot.card_analysis.units`, Extract·Compare는 `card_analysis_stage(stage=extract|compare)` payload, verdict·checklist는 `card_analysis_stage(stage=synthesis)` + HP-04 코드 조립 결과(verdict view 함수 재사용).

### 저장

- `proposal_draft` {id UUID PK, opportunity_id INT, notice_id INT, verdict_attempt_id UUID FK deep_review_attempt, policy_version_id UUID FK, policy_sha256, approval_id UUID FK transfer_policy_approval, status `queued|running|completed|partial|failed|superseded`, stage `toc|draft|reviewed|ready`, created_by, created_at, started_at, completed_at}. stage 전이: 생성 시 `toc`; 첫 절 completed 시 `draft`(worker); 6절 모두 `reviewed` 시 `reviewed`(web, review PATCH 안에서); `ready`는 `PATCH /api/proposals/{draft_id}/stage` body `{stage:"ready", request_id}`(actor; `reviewed`에서만, 되돌리기 없음). 같은 opportunity의 새 draft 생성 시 이전은 `superseded`.
- `proposal_section` {id UUID PK, draft_id FK, section_key, revision INT, status `queued|running|completed|failed|reviewed`, input_sha256 NULL, result_sha256 NULL, payload JSONB NULL(Section; INSERT 후 채움), error_code TEXT NULL, prompt_tokens INT NULL, output_tokens INT NULL, latency_ms INT NULL, created_at, completed_at NULL, reviewed_by NULL, reviewed_at NULL}; UNIQUE(draft_id, section_key, revision). 행 생성 주체·UPDATE 권한(열 단위 GRANT + trigger):

| 역할 | INSERT | UPDATE 허용 열 | trigger 규칙 |
|---|---|---|---|
| web(app) | `proposal_draft`, `proposal_section`(queued 행), `proposal_sentence_edit`, `proposal_export` | draft: `stage`·`status`(superseded만); section: `status`(completed→reviewed만)·`reviewed_by`·`reviewed_at` | 그 외 전이·DELETE 거부 |
| worker | 없음(job은 web이 만든 행을 claim) | draft: `status`·`started_at`·`completed_at`; section: `status`(queued→running→completed\|failed)·`input_sha256`·`result_sha256`·`payload`·`error_code`·`prompt_tokens`·`output_tokens`·`latency_ms`·`completed_at`(각 1회) | payload·result 재기록 거부 |
| ro_backup | — | — | — |
- `proposal_sentence_edit` {id UUID PK, section_id FK, sentence_id UUID, text TEXT(1..400), actor, request_id, created_at}; append-only overlay. 화면·PDF는 sentence_id별 최신 edit을 적용하고 "수정됨" 표식.
- `proposal_export` {id UUID PK, draft_id FK, overlay_sha256 CHAR(64)(절 revision·edit 집합·`renderer_version`·`font_sha256`의 canonical SHA), renderer_version TEXT(`reportlab==x.y.z`), font_sha256 CHAR(64), content_object_id UUID FK content_object(namespace `proposal-pdf`, retention_class `proposal-pdf-365d`, 암호화 없음 — 회사 자료가 아닌 초안), pdf_sha256, page_count INT, created_by, created_at}; UNIQUE(draft_id, overlay_sha256) — 같은 내용은 재렌더하지 않는다.
- migration(단일 head 다음), 권한: worker INSERT/UPDATE(section 1회 채움 열)·SELECT; web SELECT/INSERT draft·edit·export, UPDATE draft(status·stage)·section(status reviewed 열); ro_backup SELECT; DELETE 없음.

### REST (`bidops.proposal.v1`)

| 호출 | 입력 | 성공 | 실패 |
|---|---|---|---|
| `GET /api/opportunities/{id}/proposal` | `?draft_id=` 생략 시 최신 | 200 `ProposalView` | 404 `opportunity_not_found`; 200 `{draft:null}`(초안 없음) |
| `POST /api/opportunities/{id}/proposal-requests` | actor; `{request_id}` | 202 `{draft_id, status:"queued"}` | 409 `verdict_required`(completed 판정 없음)·`policy_not_approved`·`daily_cap_reached`·`draft_in_progress`; 404; 422 |
| `POST /api/proposals/{draft_id}/sections/{key}/regenerations` | actor; `{request_id}` | 202 `{section_id, revision}` | 409 `daily_cap_reached`·`section_in_progress`; 404 |
| `PATCH /api/proposals/{draft_id}/sections/{key}/review` | actor; `{request_id}` | 200 `SectionView`(`status=reviewed`) | 409 `section_not_completed`; 404 |
| `POST /api/proposals/{draft_id}/sentences/{sentence_id}/edits` | actor; `{text, request_id}` | 201 `{edit_id}` | 404 `sentence_not_found`; 422 |
| `POST /api/proposals/{draft_id}/exports` | actor; `{request_id}` | 201 `{export_id, pdf_sha256, created:bool}`(같은 overlay면 기존 행·`created=false`) | 409 `draft_not_completed`(partial 허용: 실패 절은 "생성 실패" 페이지로), 503 `pdf_unavailable` |
| `GET /api/proposals/{draft_id}/exports/{export_id}.pdf` | 없음 | 200 `application/pdf`(헤더 `X-BidOps-Export-Sha256`; 부작용 없음) | 404 |
| `PATCH /api/proposals/{draft_id}/stage` | actor; `{stage:"ready", request_id}` | 200 `{stage}` | 409 `stage_transition_invalid`; 404 |

`ProposalView = {schema_version:"bidops.proposal.v1", draft: {draft_id, status, stage, created_at, sections: SectionView[], requirement_coverage: {total:int, linked:int, unlinked_unit_ids:string[]}, counters: {sentences_to_confirm:int(= `proposed_figure` 수 + `placeholder` 수; ux-review 결정 6의 "초안 연결 n"은 `requirement_coverage.linked`), placeholders:int, proposed_figures:int, reviewed_sections:int}, latest_export: {export_id, created_at, pdf_sha256}|null} | null}`. `SectionView = {section_key, title, revision, status, paragraphs(edit 적용·`edited:bool`), requirement_links[{unit_id, paragraph_id, fit_status}], error_code}`. 운영 정보(정책·모델·sha·토큰)는 응답에 넣지 않는다(⋯ "실행 정보"는 RL-03 verdict의 identity를 재사용).

### PDF 렌더

- 렌더러 `reportlab`(순수 Python; 전이 의존 `pillow`·`chardet`의 x86_64 cp312 wheel hash를 `requirements.lock`에 추가) + 폰트는 **이미 백엔드 이미지(`web/Dockerfile`)가 apt로 설치하는 `fonts-nanum`의 TrueType `NanumGothic.ttf`·`NanumGothicBold.ttf`**(`BIDOPS_PDF_FONT_DIR` 기본 `/usr/share/fonts/truetype/nanum`; `fonts-noto-cjk`는 CFF `.ttc`라 ReportLab `TTFont`가 못 읽으므로 쓰지 않는다; 바이너리 폰트를 저장소에 넣지 않는다). 로컬 테스트는 같은 경로가 없으면 `BIDOPS_PDF_FONT_DIR`로 지정하고 없으면 T7의 503 분기만 돈다. A4 세로, 본문 11pt/1.6, 쪽 번호, 표지(공고명·기관·"초안 · 생성일 · 제출본 아님"), 목차, 절 6개, 부록 A 요구사항 대응표(unit_id·정규화 문장·대조 pill 텍스트·절/문단), 부록 B 출처 목록(위첨자 번호 → 출처 kind·ref·quote).
- 표식: `placeholder` 문장은 노란 바탕(`#FFF4E5`) + "[채울 것: 힌트]", `proposed_figure`는 같은 바탕 + "[제안 수치]", 수정된 문장은 끝에 "[수정됨]", 각 `statement` 끝에 위첨자 출처 번호. 색은 PDF 전용 상수(화면 테마 토큰과 무관).
- 결정성: ReportLab `invariant=1`(CreationDate·trailer `/ID` 고정) + 생성일은 draft `created_at` + 폰트 subset 고정. 같은 `overlay_sha256`(렌더러 버전·폰트 sha 포함)이면 바이트 동일.

### 화면 `/opportunities/:id/proposal` (ui-spec §4.5)

- 헤더 액션: PDF로 내보내기(주; `status∈completed|partial`; `POST …/exports` 뒤 GET 링크) · 다시 만들기(새 draft) · ⋯(제출 준비로 표시(`PATCH stage`, reviewed에서만) · HWP 후속 비활성 · 버전 비교 비활성).
- 좌측(280px): stepper 4(목차·초안·검토 완료·제출 준비) / 숫자 3(확인할 문장=`sentences_to_confirm`, 비어 있는 자리=`placeholders`, 분량=전체 문장 수) / 채워야 할 것(placeholder 힌트별 건수) / 범례 1줄.
- 중앙: 절 탭 6(요구사항 수행방안 탭에 확인 건수 pill) → 본문 카드(세리프 14px/1.8, 최대 620px; 문장 클릭 → 인라인 수정 TextArea) + 우측 "이 절이 답하는 요구사항" 표. 하단 버튼: 문장 수정(선택 문장) · 이 절 다시 쓰기 · 검토 완료(주).
- 상태: `draft:null` → "제안서 초안은 판정 뒤 만들 수 있습니다" + 버튼(판정 completed면 활성); `queued|running` → "초안 생성 중"(절별 진행); `partial` → 실패 절 카드에 "생성 실패 · 다시 쓰기"; `superseded` 초안은 `?draft_id=`로만.
- 금지 문자열: 정책 id·모델명·sha·토큰 수.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| 승인 행 `daily_cap`(proposal) | int | 3 | 1..20 | 초안 수, `tunable` |
| 정책 `execution.timeout_seconds` | int | 900 | | 절당 |
| 정책 `execution.review_timeout_seconds` | int | 5400 | | 초안 전체 |
| `BIDOPS_PROPOSAL_POLICY_PATH` | path | `policies/proposal-policy-luna-v1.json` | | immutable |
| `BIDOPS_PDF_FONT_DIR` | path | `/usr/share/fonts/truetype/nanum` | | 없으면 `pdf_unavailable` |
| `BIDOPS_PROPOSAL_POLICY_VERSION_ID` | UUID | 없음 | | import된 정책 행 선택 |
| `BIDOPS_LUNA_DEEP_REVIEW_ENABLED`·`BIDOPS_REFERENCE_WORKFLOW_MODE`·`BIDOPS_ANALYSIS_PROVIDER` | 기존 | | | 실행 조건 |
| contract `proposal-section-v1` prompt 상한 | int | 120000자 | 고정 | 초과는 `input_budget_exceeded` |

## 상태 값과 실패 처리

- draft status 6값, stage 4값, section status 5값, sentence kind 3값, source kind 3값(위).
- 오류 code: `verdict_required`, `draft_in_progress`, `section_in_progress`, `section_not_completed`, `sentence_not_found`, `draft_not_completed`, `stage_transition_invalid`, `pdf_unavailable`, `proposal_forbidden_content`, `proposal_section_invalid`, `proposal_coverage_incomplete`(requirements 절이 카드 unit을 다 덮지 못함 → 절 failed), `proposal_review_timeout`, `input_budget_exceeded`, + RL-03 `policy_not_approved`·`daily_cap_reached`. 검증 실패는 자동 보정 없이 `failed`·사람 검토.
- 감사 `analysis.transfer.sent`(purpose=proposal) safe_metadata: approval_id, policy_sha256, input_sha256, draft_id, section_id, section_key, notice_id. RL-03 승인 행의 `scope.stages` 검사는 proposal에는 적용하지 않는다(`purposes`만).

## 저장

위 표 4개. 객체 저장소: PDF는 `content_object`(기존 hash·version 규칙).

## 인터페이스(CLI·UI·API)

- 위 REST(8개). CLI 없음(승인은 RL-03 `approve-transfer-policy --policy proposal-policy-luna-v1 --daily-cap 3`).
- 외부 호출 보호 장치: RL-03과 동일(gate 순서·감사). contract `proposal-section-v1` 등록 5곳: `runner.py` contract 집합·schema 경로 분기, `web/codex-runner/Dockerfile` COPY, `luna_client.py` 집합+길이 상한, `contracts/__init__.py SCHEMA_FILES`. RL-03의 `card-*` 등록과 같은 줄이므로 RL-03 병합 뒤에 추가한다.

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| PDF만, HWP 후속 | ADR-0073 개정(E2), HWP 생성기 없음 | DOCX |
| ReportLab + 이미지의 NanumGothic(TrueType) | 순수 Python·결정적 바이트; 폰트는 이미 이미지에 있어 바이너리 커밋 불필요(독립 검사: Noto CJK는 CFF라 ReportLab 불가) | Noto Sans KR vendoring(11MB 바이너리), WeasyPrint, headless Chromium |
| 절 실행은 전용 WorkJob·worker | 기존 `claim_next_job`·`run_claim`이 deep_review stage 3개에 묶임(`assumption_analysis` 선례) | DeepReviewAttempt 재사용 |
| export는 POST 생성 + GET 읽기 | GET 부작용 금지(기존 REST 관례) | GET이 렌더 |
| 절당 1회 호출·절 단위 실패 보존 | 호출 상한 예측 가능(6), 부분 실패 보존 규칙(강제 게이트) | 전체 1회 |
| 출처 없는 문장 금지·placeholder | ui-spec §4.5 규칙, ux-review 결정 5·6 | 자유 서술 |
| 가격·인력·전략 수치 금지 검증을 코드가 | 사람 책임(mission), 모델 규칙만으론 보증 불가 | 프롬프트만 |
| 실적 절은 홈페이지 confirmed만 | 인터뷰 B1·B2 목록 unknown | 실적증명 추정 |
| 별도 승인 행·cap | 용도별 설정 분리(강제 게이트 "용도별") | RL-03 승인 공유 |
| 수정은 overlay | 생성 원문 불변(append-only) | payload 덮어쓰기 |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | 입력 조립: 절별 unit 선택·confirmed만·missing_facts·노트 배제·허용 키 | 키 집합 정확, `proposed`/`unknown` 값 없음 | 단위 |
| T2 | 문장 검증: 출처 없는 statement, quote 비부분문자열, placeholder 힌트 없음, 금지 금액/인원/일정(원문 인용 허용 케이스 포함) | 각 code로 `failed`, 자동 보정 없음 | 단위 |
| T3 | requirements 절 커버리지(카드 unit 1개 누락) | `proposal_coverage_incomplete` | 단위 |
| T4 | gate: 판정 없음·승인 없음·cap(초안 3, 재생성 1/6)·진행 중 중복 | 409 code, 호출 0 | 단위 |
| T5 | 절 단위 실패·부분 보존·재생성 revision·superseded·timeout 5400·job 6개·권한 행렬(web/worker UPDATE 열·trigger) | PG append-only·UNIQUE·권한 거부 | PostgreSQL |
| T6 | edit overlay·review 전이·`section_not_completed` | 원문 불변, 최신 edit 적용 | 통합(PG) |
| T7 | PDF: 표식 3종·출처 위첨자·부록 2개·결정성(`invariant=1`, 같은 overlay → 같은 sha; 렌더러 버전·폰트 sha가 overlay에 포함)·폰트 없음 503·POST 멱등(`created=false`) | 바이트 동일, 텍스트 추출로 표식 확인 | 단위 |
| T8 | 화면: 상태 4종·절 탭·숫자 3·문장 수정·검토 완료·내보내기·금지 문자열·1280/1440 | Playwright app | 프런트 |
| T9 | payload·감사(purpose=proposal) | 허용 키·토큰/원문 부재 | 단위 |
| T10 | mock 전 경로(bidops-local) | 연결 증명 | 수동 |
| T11 | 실제 Luna 1건(RL-03 T12와 같은 공고; 사람 직전 확인) | 절 6개·누락 0·금지 내용 0, `unmeasured_reference` | 수동(real_data_run) |

## 컨벤션 반영 항목

- `bidops.proposal.v1`·`bidops.proposal-section.v1`·`bidops.proposal-input.v1`, 테이블 4(권한 행렬·trigger), REST 8, 오류 code 14, WorkJob `job_type=proposal_section`, runner contract `proposal-section-v1`(5곳), 정책 identity·행 선택 env, 설정 4, 의존 `reportlab`(+pillow·chardet lock), 객체 namespace `proposal-pdf`, tech-stack "DOCX 중간 형식" 문장 삭제.
