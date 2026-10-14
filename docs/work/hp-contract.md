# HP 공통 계약 — 홈페이지 전문 가상 1사 심층 검토

- 버전: v0.1 (2026-10-14). 근거: [ADR-0071](../tracking/decisions/0071-homepage-single-company-deep-review.md).
- 성격: HP-00~06이 공유하는 계약이다. **확정**은 사용자 결정이나 검증된 사실, **결정 대기**는 해당 기능의 interview에서 닫는다.
  결정 대기 항목은 §11 표에 모아 두고, 닫히면 이 문서를 고치고 `docs/ADR.md`에 한 줄 남긴다.
- 재사용: [DEMO 공통 계약](demo-contract.md) §1(회사 문맥) §2(REST 공통형) §3(온톨로지·원본·그래프) §4(프로필 projection·CLI·그래프 조회) §8(등록·저장·fingerprint)은 그대로 쓴다.
  DEMO §5·6·7·9·10의 3사 비교·LiteLLM 핏·6/18/9건 인수는 HP에서 폐기하고, 심층 preview·승인·공용 슬롯·오류 code(§9)는 HP-03이 다시 쓴다.

## 0. 모델 identity (확정, HP-00)

| 항목 | 값 |
|---|---|
| provider / transport | `codex-exec` (기존 codex-runner 컨테이너, 슬롯 1개) |
| model | `gpt-6-luna` |
| reasoning_effort | `high` |
| codex CLI | `0.162.1` (`tunable`: 호스트에서 gpt-6 계열과 함께 검증된 버전) |
| 정책 identity | 회사 계보 `analysis-policy-luna-hp-v1`, NULL 계보 `analysis-policy-luna-v5`(둘 다 HP-00, narrative-v2 유지) → HP-03이 `analysis-policy-hp-v1`(card-v1 파이프라인) 발행 |
| 품질 표식 | `quality_status=unmeasured_reference` 유지 |

preview·승인·attempt·감사의 model/reasoning_effort/cli_version은 **고정된 정책 row와 identity 모듈에서 읽는다**. 코드 여러 곳에 문자열을 복제하지 않는다.
runner는 하나이므로 정책의 모델이 runner identity와 다르면 preview·생성·claim 어느 단계에서든 호출 없이 `model_binding_invalid`로 닫는다.
기존 정책 파일 v1~v4·demo-v1과 그 실행 row는 바꾸지 않으며 `gpt-5.6-luna`/`xhigh` 값은 legacy 조회에서만 허용한다.
LiteLLM `local-agent-main`·Qwen·Terra는 HP에서 호출하지 않는다. 실제 호출은 건별 승인 뒤 `bidops-local`에서만 한다.

## 1. 회사 (확정 일부, HP-02)

- 회사는 하나다. `is_fictional=true`, 모든 사실 노드·관계의 origin은 `fictional_scenario`다. 저장·등록·활성화는 DEMO §3·4·8 그대로다.
- 회사명·slug·업태 설명·의도적 격차 목록은 **결정 대기**(HP-02, 사용자 승인 뒤 동결).
- `bidops-local` DB에 남은 DEMO 3사 row는 지우지 않는다. HP 화면·분석이 어느 회사를 보이는지는 **결정 대기**(HP-04: 활성 회사 목록 설정 또는 HP 회사만 등록한 새 DB).

## 2. 입력 정본과 변환 (확정, HP-01)

- 입력 정본은 HWP/HWPX 원본이다. 기존 격리 document worker의 rhwp 네이티브 경로(`hwp-rhwp-native-hwpx`·`hwpx-stdlib`)가 `DocumentStructure`를 만든다.
- 구조 payload의 block은 `paragraph|table|table_cell`이며 `table_cell`은 `attributes{table_key,row,column}`과 `parent_block_key=<table block key>`를 가진다. 모든 block에 `page`가 있으나 HWPX 경로의 `page`는 물리 쪽이 아니라 구역 기준이다.
- 물리 쪽은 `para_page_map`(`bidops.para-page-map.v1`, `blocks[]{block_key,page_first,page_last,match}`)이 정본이다. 대응표는 원본 HWPX의 문단·표를 문단 identity로(`match=exact`), 셀과 비원본 문단은 PDF 쪽 text와의 유일 일치로 매핑한다. 2026-10-14 외교부 문서의 매핑 1,339건은 전부 문단이었다. 매핑되지 않은 표 셀의 쪽은 §3의 상속 규칙으로 구한다.
- PDF는 PDF 전용 첨부와 쪽 locator(`para_page_map`·`/pages/{page}`)에만 쓴다. OCR은 범위 밖이다. PDF 전용 첨부가 실제 수집에서 나타나면 findings에 적고 별도 결정한다.
- 2026-10-14 검증값: 5건(27·57·31·35·48 카드)이 3.6~9.5초에 변환되고 카드 198/198, 쪽 상속 198/198이다(scratchpad `cards_vocab.py`, HP-01 증거 실행으로 재현한다).

## 3. 요구사항 카드 (확정, HP-01)

### 3.1 카드 양식과 라벨 사전

국내 제안요청서의 요구사항 카드는 라벨·값 표다. 라벨은 공백 제거·casefold 뒤 다음 사전과 정확히 일치해야 한다.

| 필드 | 라벨(공백 제거) | 필수 |
|---|---|---|
| category | 요구사항분류 | 예 |
| requirement_id | 요구사항고유번호, 고유번호, 요구사항번호, 요구사항id | 예 |
| title | 요구사항명칭, 명칭, 요구사항명 | 예 |
| compliance_level | 응락수준, 필수여부, 중요도 | 아니오 |
| definition | 정의 | 예 |
| details | 세부내용, 세부설명 | 예 |
| outputs | 산출정보, 산출내용, 산출물 | 아니오 |
| related | 관련요구사항 | 아니오 |

규칙: 값은 같은 행에서 라벨 오른쪽의 첫 비어 있지 않은 비라벨 셀이다. 한 표에 카드가 여러 장 쌓일 수 있다. 카드 범위는 requirement_id 라벨 행 위쪽의 가장 가까운 category 라벨 행부터 다음 requirement_id 라벨 행 직전까지다.
카드 표 = requirement_id 라벨 셀의 같은 행 오른쪽 값 셀에 `_ID_TOKEN`이 있는 표. 카드 표는 기존 열 제목 표 탐지에서 제외하고 열 제목 표와 같이 segment 경계로 삼는다.
requirement_id는 기존 `_ID_TOKEN`으로 읽고 `_normalize_id`로 정규화하며 ID가 없거나 토큰이 아니면 카드가 아니다. hwpx 변환기는 중첩 표를 최상위 표로 평탄화하므로 중첩 규칙은 두지 않고, 같은 ID가 두 표에서 나오면 둘 다 보존하며 `duplicate_ids`에 적는다.
필수 필드가 비면 카드를 만들되 `card_warnings`에 `missing:<field>`를 적는다. 값은 원문 그대로 보존하고 요약·정규화하지 않는다(ID만 정규화).

### 3.2 inventory 항목 (`bidops.requirement-card.v1`)

기존 `inventory_items`(DB 저장, 조회 응답에 없음)에 카드 필드를 더한다. 기존 열 제목 표 경로의 항목은 `source=column_header_table`로 그대로 남는다.

```
InventoryItem = {
  raw_id, normalized_id, locator{kind:"table_cell",block_key,table_key,row,column,page,ordinal}, title, ordinal,   // 기존
  source: "column_header_table" | "label_value_table",                                                             // 신규
  card: null | {                                                                                                   // label_value_table만
    category: string, compliance_level: string|null, definition: string, details: string,
    outputs: string|null, related_raw: string|null, related_ids: string[],   // related_ids는 related_raw에서 _ID_TOKEN으로 읽은 정규화 ID
    table_key: string, first_cell_block_key: string, card_warnings: string[],
    page_anchor_block_keys: string[]        // 표 앞의 비어 있지 않은 문단 block_key 최대 3개(가까운 순), build 시점에 저장
  }
}
```

- 저장: 항목은 `requirement_inventory_item` 행이다. `source`(TEXT, 기본 `column_header_table`)와 `card`(JSONB, null 허용) 열을 더하고 기존 행은 바꾸지 않는다. segment 행에는 `page_anchor_block_keys`(JSONB) 열을 더한다. wire 응답 shape는 바뀌지 않는다.
- `normalized_id`는 문서 안에서 유일해야 하며 두 경로(열 제목·라벨 값)가 같은 ID를 내면 `duplicate_ids`에 적고 둘 다 보존한다.
- `inventory_summary`에 `card_item_count`(라벨 값 카드 수)와 `label_value_table_count`를 더한다. `expected_ids`·`prefixes`는 두 경로의 합집합이다.
- extractor는 `EXTRACTOR_VERSION="2"`, 규칙 hash가 바뀌므로 같은 구조에 새 manifest 행이 생기고 기존 행은 남는다. 업그레이드 전 구조는 CLI `rebuild-segment-manifests`(analysis-worker 이미지·worker 역할)로 현재 manifest를 만든다(멱등, 기존 행 보존).
- 카드 prefix는 문단 경로 후보를 확정하지 않는다. 본문의 ID 언급은 기존 규칙으로 확정된 prefix일 때만 항목이 된다.
- deep_review가 쓰는 조회 함수 `requirement_cards(session, structure_id, store) -> list[InventoryItem + page_range + mapping_status]`를 둔다(최신 manifest, 카드 항목만, 문서 순서).

### 3.3 쪽 상속

읽기 시점(`segments_view`·`requirement_cards`)에 `para_page_map`이 있으면: 대상의 block 키 중 매핑된 것이 하나라도 있으면 기존 규칙(`mapped|partial`)이 우선한다. 하나도 없으면 build 시점에 저장한 `page_anchor_block_keys`를 가까운 순으로 보고 **첫 매핑된 문단의 `page_first`**를 쪽으로 쓴다.
결과의 `mapping_status`는 `inherited`(새 enum 값)이며 `page_range={first:p,last:p}`다. 매핑된 anchor가 없으면 `unavailable`·`null`이다. 대응표가 없으면 기존처럼 `unavailable`이다. 읽기 시점에 구조 payload를 다시 읽지 않는다.
segment의 `mapping_status` enum은 `mapped|partial|inherited|unavailable`이 된다(contracts.md 갱신). 상속은 추정이므로 화면은 "앞 문단에서 상속"임을 밝힌다.

### 3.4 taxonomy v2 (`bidops.segment-taxonomy.v2`)

label 집합: `business_eligibility_evaluation`, `technical_functional`, `quality_security_constraints`, `partnership_governance`, **`operations_maintenance`**(신규).

| 카드 category(공백 제거, 접미 "요구사항" 유무 무관) | 접두사 | label |
|---|---|---|
| 기능, 데이터, 인터페이스, 시스템, 시스템장비구성 | SFR, DAR, INR, SYR, TFR, ECR | technical_functional |
| 보안, 품질, 성능, 제약, 테스트, 표준 | SER, QUR, PER, COR, TER, STR | quality_security_constraints |
| 프로젝트관리, 프로젝트지원 | PMR, PSR | partnership_governance |
| 유지관리, 유지관리수행, 유지관리인력, 운영 | MAR, MPR, MHR | operations_maintenance |

카드가 있는 segment의 label은 카드 category 매핑을 우선하고(`classification_source=deterministic`, 근거 `category`), 카드가 없으면 기존 제목 키워드·접두사 규칙을 쓴다.
제목 키워드에 `유지관리`, `유지보수`, `운영`, `장애`, `서비스수준`, `상주`를 `operations_maintenance`로 더한다. 충돌 규칙(`taxonomy_conflict`)은 그대로다.

## 4. 온톨로지 (결정 대기, HP-02)

- 스키마는 `bidops.company-ontology.v1`(DEMO §3)을 유지하고 내용 버전만 홈페이지 도메인으로 바꾼다. 매핑은 기존 결정적 NFKC 어휘 일치와 3단계 경로 검색을 그대로 쓴다.
- 출발점은 카드 198장에서 뽑은 [어휘 후보](groups/HP/features/HP-02-homepage-ontology-company/vocabulary-candidates.md)다. 후보 묶음은 기능·기술·보안·운영/유지관리·품질/성능·계약/사업관리·자격/실적 일곱 가지다.
- 권장 순서: 어휘 후보 검토 → 분류(kind) 확정 → concept id·label·alias 확정 → 요구사항 카드 전수 매핑 결과 검토(미매핑 카드 목록) → 동결.
- 결정 대기: kind 확장 여부(예: 서비스 수준·인력 조건을 capability와 구분할지), 관계 확장 여부(예: `requires_staffing`), concept id 접두 규칙(`cap.`/`tech.`/`qual.`/`dom.`), alias 정규화 규칙 변경 여부.

## 5. 회사 프로필 (결정 대기, HP-02)

- 사실 축: 자격(소프트웨어사업자 신고, 직접생산확인, 중소기업 확인, 웹접근성 품질인증 수행 경험 등), 실적(홈페이지 구축·유지관리 project 노드: 역할·범위·금액·기간), 인력(staff_group: PM/PL·개발·디자인·퍼블리싱·운영 상주 가능 인원), 기술(technology), 운영 역량(capability: 24×365 장애 대응·정기 점검·취약점 점검·백업·콘텐츠 운영), 계약 조건(하도급·공동수급 경험).
- 의도적 격차는 셋 이상 두고 §8 gold가 그것을 잡는지 본다(예: ISMS 미보유, 외국어 사이트 실적 없음, 상주 인원 상한, 특정 DBMS 경험 없음).
- 모든 사실은 `status=confirmed|inferred|unknown`과 `source_refs`를 갖는다. unknown은 "모름"이며 미보유가 아니다.
- 결정 대기: 회사명·slug, 격차 목록, 수치(실적 금액·인원·기간), 프로필 원본 파일 위치(`docs/hp-fixtures/` 제안).

## 6. 분석 단위와 1층 추출 (확정 뼈대, 세부는 HP-03)

- 분석 단위는 **unit**이다. unit은 (a) 요구사항 카드 1장, 또는 (b) 카드가 아닌 segment(사업개요·추진 일정·예산·입찰참가자격·평가·계약 조건) 하나다. unit id는 `card:<normalized_id>` 또는 `segment:<segment_id>`다.
- 1층 출력 계약 `bidops.requirement-extract.v1`(확정 필드, enum 전체는 HP-03 spec):

```
Extract = { unit_id, type: 자격|실적|인력|기술|기능|성능SLA|보안|운영|계약|평가,
            normalized_requirement: string, mandatory: true|false|null,
            constraints: [{kind: amount|duration|count|date|percentage|boolean|text, value, unit|null, quote, locator}],
            concept_candidates: [{concept_id|null, alias_text}], unknowns: [string], evidence: [{quote, locator}] }
```

- 모든 quote는 해당 unit의 원문 block 부분문자열이어야 하고 locator는 §3의 block_key다. 검증 실패는 사람 검토로 보내며 자동 보정하지 않는다(기존 규칙).
- 카드 여러 장을 한 호출에 묶는 `batch_size`와 묶음 문자 상한은 정책 값이다(결정 대기, 기본 제안 8장/12,000자).

## 7. 결정적 대조와 2층 판단 (확정 뼈대, 세부는 HP-03)

- 대조는 코드가 한다. unit의 concept_candidates → 온톨로지 concept → 회사 그래프 경로(direct/partial/unmapped, DEMO §5 규칙) → 수치 제약은 회사 사실 value와 비교.
  unit별 `fit_status ∈ met|gap|unknown`: met = confirmed 사실에 direct 경로가 있고 수치 제약을 만족, gap = confirmed 사실이 요구를 부정(미보유·미달), unknown = 그 밖(경로 없음·unknown 사실·비교 불가).
- 2층은 역할 셋 + 종합 하나다. 역할: `eligibility_economics`(참여조건·사업성), `technical_fit`(기술·기능 적합), `operations_risk`(운영·위험). 각 역할은 자기 type의 unit·추출·대조 결과만 받고 `bidops.verdict-role.v1`을 돌려준다. 종합은 세 역할 결과만 받고 `bidops.practitioner-verdict.v1`을 만든다.
- 코드가 unit id로 결과를 합친다. 역할 간 충돌은 `conflicts[]`에 그대로 두고 종합이 해소하지 않는다.
- 실무자 판정 enum: `진행 가능 | 조건부 진행 | 진행 어려움 | 판단 불가`. 체크리스트 항목 key: `qualification_track_record | staffing_onsite | amount_period | technology | operations_sla_security`. 항목 상태: `met|gap|unknown`.
- 호출 수 = ceil(unit 수 / batch_size) + 3 + 1. 100쪽·unit 70개 기준 목표는 **40분 이내**(정책 `review_timeout_seconds`로 상한, 결정 대기: 기본 제안 3600초).
- 저장은 새 테이블(HP-03 spec: 추출·대조·역할·종합 각각 불변 row, attempt 단위)이며 기존 narrative-v2 보고서 테이블을 덮지 않는다. 오류 code는 DEMO §9를 재사용하고 새 code는 HP-03 spec에 열거한다.

## 8. 실무자 판정 화면 (확정 구성, 세부는 HP-04)

다섯 블록을 한 화면에 둔다. 데스크톱 전용·테마 토큰 규칙은 기존과 같다.

| 블록 | 내용 | 출처 |
|---|---|---|
| 판정 카드 | 판정 enum, 한 줄 사유, 차단 조건 수, 실행 시각·정책 identity·참조 표식 | 종합 |
| 조건 체크리스트 | 다섯 항목 key별 met/gap/unknown, 근거 quote와 쪽 | 종합·대조 |
| 요구사항 매트릭스 | 카드/segment unit별 type·fit_status·역할 판단·쪽 점프 | 1층·대조·역할 |
| 주의 포인트 | 역할이 표시한 caution·conflicts·unknown 묶음 | 역할·종합 |
| 다음 행동 | 확인할 일(누가·무엇·근거) 목록 | 종합 |

REST는 `/api/companies/{company_id}` 아래에 둔다(경로명 결정 대기). 화면은 추적 승인·Go/No-Go를 저장하지 않는다(기존 추적 조작은 그대로).

## 9. gold 10건 (확정 형식, HP-06)

- 문서마다 사용자가 모델 출력을 보기 전에 쓴다: 참여 판정(§7 enum), 차단 조건, 충족 5·부족 5(카드 ID 또는 조건 문장), 주의 포인트, 카드 ID 상태 표본 10(met/gap/unknown).
- 파일: `docs/hp-gold/<notice 또는 fixture 이름>/gold.v1.json`(스키마는 HP-06 spec). 작성 뒤 sha256을 기록하고 바꾸면 새 버전 디렉터리를 만든다.
- 채점은 제품 밖 스크립트가 한다: 판정 일치 수, 차단 조건 recall, 충족/부족 5의 precision, 카드 상태 일치율. 채택 임계값은 **결정 대기**(제안: 판정 일치 ≥ 8/10, 차단 조건 recall ≥ 0.8, 카드 상태 일치 ≥ 0.7).

## 10. Neo4j 비교 실험 (확정 기준, HP-05)

- 비교 대상: PostgreSQL 그래프 테이블 + 코드 BFS(현행) 대 Neo4j 5 컨테이너 + Cypher. Apache AGE는 비교하지 않는다(사용자 결정).
- 데이터: 동결된 홈페이지 온톨로지·회사 1곳·gold 10건의 요구 concept. 가상회사 자료만 적재하고 실제 공고 원문은 넣지 않는다.
- 기준 셋: (1) **경로 recall** — 사용자가 표시한 기대 경로 집합 대비 각 엔진이 찾은 경로; (2) **질의 표현력** — 고정 질의 5개(조건부 다중 홉)를 Python과 Cypher로 각각 쓰고 길이·가독성·변경 용이성을 비교; (3) **설명 가능성** — 같은 경로 10개를 화면에 보이는 형태로 나란히 두고 실무자 관점 평가.
- 채택 조건은 실행 전에 숫자로 적는다(결정 대기, 제안: recall 차이 ≥ 2경로/10건 또는 질의 5개 중 3개 이상에서 뚜렷한 우위가 있고 운영 비용 항목을 사용자가 수용할 때 채택, 아니면 유지).
- 결과는 `docs/experiments/<날짜>-neo4j-vs-postgres.md`에 가설→기준→명령→결과→판단으로 남기고, 채택이면 replan으로 제품 범위를 다시 정한다.

## 11. 결정 대기 목록

| 번호 | 항목 | 닫는 기능 | 제안 |
|---|---|---|---|
| D1 | 회사명·slug·격차 목록·수치 | HP-02 | 어휘 후보 검토 뒤 초안 제시 |
| D2 | 온톨로지 kind·관계 확장, id 접두 규칙 | HP-02 | kind 유지, 접두 `cap./tech./qual./dom.` |
| D3 | HP 화면이 보이는 회사(DEMO 3사 row 처리) | HP-04 | 활성 회사 목록 설정으로 HP 회사만 표시 |
| D4 | batch_size·묶음 문자 상한·timeout·repair 횟수 | HP-03 | 8장/12,000자/3600초/1회 |
| D5 | 카드가 아닌 segment를 unit으로 넣는 범위 | HP-03 | 사업개요·일정·예산·참가자격·평가·계약 label segment만 |
| D6 | 판정 REST 경로명·응답 키 | HP-04 | `/pre-specs/{notice_id}/verdict` |
| D7 | gold 채점 임계값 | HP-06 | §9 제안값 |
| D8 | Neo4j 채택 조건 숫자 | HP-05 | §10 제안값 |
| D9 | PDF 전용 첨부 처리 | 해당 시 findings | 보류 |
