# 판정 탭 실무자 화면 개선(프런트엔드 1차) — spec

- 기능 ID: `RL-07-verdict-ux`
- 근거: [intent.md](./intent.md), RL-05 실제 10건 독립 UX 검토(2026-10-20, 캡처는 Git 밖)
- 작성일: 2026-10-20 (같은 날 독립 검사 지적 반영)

## 큰 틀 문서와의 관계

- 인용하는 절: [HP 계약 §8](../../../../hp-contract.md)(판정 화면 5블록·판정 카드의 차단 조건 수·쪽 없으면 점프 없음), [ui-spec §4.4](../../../../../1016_rootlab-redefinition/ui-spec.md)(RL-03 구현 기준: 서버 `PractitionerVerdictView`를 그대로 읽고 다시 계산하지 않음, 금지 문자열, 1280/1440), §4.1(브리핑), §5(검증), [contracts.md "카드 기반 참여 판정"](../../../../contracts.md)(view 필드; `blocking_condition_ids` = mandatory ∧ gap unit id 목록; 브리핑 `record_path` = `/opportunities/<id>`, `verdict_display` 11값), business-rules RL-03 절(B51·B55·C16·C19 격리, `unknown`은 확인 필요).
- 이 문서에서 새로 확정하는 항목: 주의 포인트 블록의 위치·구성, 판정 한 줄 요약, 코드 "사람 확인" 행 묶음, 격리 번호·목록↔표 연결, 행 이동 시 필터 해제, 회사 근거 열 고정 문구, 쪽 미확인일 때 원문 열, 1280 원문 패널 배치, 브리핑 판정 탭 직행.
- 큰 틀 문서 수정이 필요한 항목: ui-spec §4.4를 이 문서 규칙으로 정정(주의 포인트 블록 추가 — HP §8과 일치시키는 정정; HP §8의 "unknown 묶음"은 표 제목 집계·상태 필터가 맡는다는 결정 기록), §4.1 브리핑 직행 한 줄. roadmap RL 표 RL-07 행(문서화 때 추가 완료). ADR.md 한 줄(STEP-006).

## 입력·출력 계약

서버 계약은 바뀌지 않는다. 화면이 읽는 필드(`GET /api/opportunities/{id}/verdict`, `PractitionerVerdictView`, contracts.md 그대로):

- `result.verdict` ∈ {`진행 가능`, `조건부 진행`, `진행 어려움`, `판단 불가`}, `result.reason`, `result.blocking_condition_ids: string[]`, `result.checklist[5]{key,status}`, `result.matrix[]{unit_id, type, fit_status ∈ {met,gap,unknown}, role_findings[]{role, assessment, reason, evidence_refs}, evidence_refs, page_range|null, mapping_status, normalized_requirement?, mandatory?, fact_labels?, rejected_rule_codes?}`, `result.cautions[]{unit_id, text, evidence_refs}`, `result.conflicts[]{unit_id, roles[], assessments[]}`(같은 인덱스끼리 짝), `result.next_actions[]{unit_id, owner, action, evidence_refs, origin ∈ {model, code, null}}`.
- view 최상위: `availability`, `missing_sections[]`, `rejected_units[]{unit_id, normalized_id|null, rule_codes}`, `role_isolations[]{role, unit_id, normalized_id|null, kind, rule_codes}`, `synthesis_isolations[]{unit_id, normalized_id|null, kind, rule_codes}`, `partial_matrix`(진행 중·실패 시 부분표).
- 브리핑 항목: `record_path`(= `/opportunities/<opportunity_id>`), `verdict_display`(BriefingVerdictDisplay 11값).

화면 파생 규칙(모두 서버 값의 개수·묶음·대응이며 판정을 만들지 않는다):

1. **주의 항목 목록** `cautionItems` = `cautions`(서버 순서) 다음에 `conflicts`(서버 순서). 항목 = `{kind: "caution"|"conflict", unitId, text}`. caution의 text는 서버 `text` 그대로. conflict의 text는 고정 형식 "역할 의견이 다름: " + 각 `roles[i]`의 역할 한글 이름(기존 `ROLE_LABEL`/`roleLabel` 그대로: `eligibility_economics`=자격·사업성, `technical_fit`=기술 적합, `operations_risk`=운영·위험)과 `assessments[i]`의 판단 한글(`met`=충족, `gap`=부족, `unknown`=확인 필요)을 "역할 판단" 꼴로 " · "로 이은 것. 각 항목은 `unitId`가 `matrix`에 있으면 그 행의 표시 문장을 기존 `requirementText(row)` 그대로(격리 행이면 그 함수가 주는 "검증 실패 — 사람 확인 필요") 함께 보이고 "요구사항 보기"를 둔다. 없으면 문장 없이 항목만, 버튼 없음. HP §8의 "unknown 묶음"은 넣지 않는다(표 보조 줄·상태 필터가 맡음, 2026-10-20 사용자 결정).
2. **한 줄 요약** = `차단 {blocking_condition_ids.length} · 주의 {cautionItems.length} · 사람 확인 {codeActions.length}`. `codeActions` = `next_actions` 중 `origin === "code"`. 차단은 항상 글자(이동할 블록이 없음). 주의는 0이 아니면 버튼 → 중앙 주의 블록으로 스크롤. 사람 확인은 0이 아니면 버튼 → 좌측 코드 행 묶음을 펼치고 그 위치로 스크롤.
3. **코드 다음 행동 묶음**: `next_actions` 중 `origin !== "code"`는 지금처럼 나열. 코드 행은 한 줄 "사람 확인 {n}건" + 보조 "원문에서 찾지 못한 영역 {missing_sections.length} · 검증 실패 요구사항 {rejected_units.length}"(0인 쪽은 생략)로 묶는다. 기본 접힘, 펼치면 코드 행 문장들을 지금 형식("사람 확인" pill·담당 미지정)으로 보인다. 펼친 영역에는 `rejected_units`가 있으면 "검증 실패 목록으로", `missing_sections`가 있으면 "누락 영역으로" 버튼을 둔다(둘 다 있으면 둘 다). 각각 중앙 검증 실패 목록·누락 영역 배너로 스크롤한다.
4. **격리 번호** `isolationLabels(view)` → `Map<unitId, string>`: 검증 실패 세 목록을 `rejected_units` → `role_isolations` → `synthesis_isolations` 순서(각 서버 순서)로 이어 붙이고 unit id 첫 등장만 남긴 목록을 만든다(세 목록은 선택 필드이며 없으면 `[]`). 항목마다 `normalized_id`가 있으면 그 값(카드 번호), 없으면 "격리 항목 k" — k는 이 중복 제거 목록에서 `normalized_id`가 없는 항목만의 1부터 순번. 표·matrix의 정렬·종류(segment/카드)와 무관하므로 unit id 형식(contracts: 불투명 키)에 기대지 않는다. 이 지도를 검증 실패 목록(세 목록 모두)과 표의 격리 행(`rejected_rule_codes`가 비어 있지 않은 행) 보조 줄이 함께 쓴다. 역할만 격리된 unit은 표에서 격리 행이 아니므로(기존 규칙) 표 보조 줄에 번호가 없고 목록에서만 번호가 보인다. 주의 항목은 번호를 쓰지 않는다(규칙 1의 `requirementText`). 기존 `isolationTarget`의 목록별 `index+1`과 "판정 대상에 없는 항목" 구분은 폐기한다.
5. **회사 근거 열 고정 문구 조건**: 행이 격리 행(`rejected_rule_codes` 비어 있지 않음)이 아니고 `fit_status === "unknown"`이며 공백 아닌 `fact_labels`가 없으면 "연결된 회사 사실 없음"(muted). 그 밖은 지금 규칙(첫 `role_findings.reason` 한 줄 + 보조 `fact_labels`, 없으면 "회사 근거 없음").
6. **전 행 쪽 미확인**: 표에 넘어온 행(완료 `matrix` 또는 부분표)이 비지 않았고 모든 행에서 기존 `pageRangeLabel(row) === null`(= `page_range` 없음 또는 `mapping_status === "unavailable"`)이면 원문 열을 그리지 않고 표 위 안내 한 줄을 보인다. 한 행이라도 쪽 라벨이 있으면 원문 열 그대로.
7. **근본 원인 안내 조건**: 판정 완료이고 `matrix`가 비지 않았고 모든 행이 `unknown`이며 공백 아닌 `fact_labels`를 가진 행이 하나도 없다. 판정 이름과 무관하다. 문구는 이 조건에서 사실인 것만 말한다(아래 인터페이스).
8. **브리핑 판정 탭 직행**: `verdict_display` ∈ {`진행 가능`, `조건부 진행`, `진행 어려움`, `판단 불가`, `사전규격 판정 참조`}(contracts 브리핑 절: 마지막 값은 같은 사업기회의 권위 연결 사전규격에 completed 판정이 있다는 뜻이고 `record_path`는 같은 사업기회)이고 `safeRecordPath(record_path)`가 `^/opportunities/[0-9]+$`이면 피크 패널 링크·Enter 이동 대상을 `<record_path>/verdict`로. 그 밖은 지금처럼 `record_path`.
9. **체크리스트 축약**: `checklist`의 모든 행이 같은 상태이면 한 줄 "{checklist.length}개 조건 모두 {상태 한글}" + "펼치기"(펼치면 행 전부). 하나라도 다르면 행 전부 그대로.
10. **상태 필터 숨김**: 표에 넘어온 행의 `fit_status`가 한 종류뿐이면 상태 select를 그리지 않고 상태 필터를 "전체"로 고정한다("필수만" 토글은 유지). 두 종류 이상이면 지금 그대로(기본 "부족·확인 필요만").
11. **요구사항으로 이동** `revealRow(unitId)`: 대상 행이 현재 필터·"필수만"·페이지 때문에 표에 없으면 상태 필터를 "전체"(select가 숨은 경우 이미 전체), "필수만"을 끔, 그 행이 들어가도록 페이지를 펼친 뒤(사용자 결정 2026-10-20) 그 행을 선택(`aria-selected`)하고 화면 안으로 스크롤한다. 이 경로는 선택을 지우지 않는다(지금 필터 변경 시 선택을 지우는 동작과 구분).

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| 주의 포인트 처음 보이는 수 | int(코드 상수) | 5 | 1~ | tunable. 넘으면 "n건 더 보기" |
| 검증 실패 목록 처음 보이는 수 | int(코드 상수) | 3 | 1~ | tunable. 세 목록을 합친 순서(rejected → 역할 → 종합)에 적용 |
| 패널 열림 시 회사 근거 열 숨김 기준 | `window.matchMedia("(min-width: 1440px)")` 불일치 | 뷰포트 폭 < 1440px | — | tunable. JS로 판단해 열 정의에서 뺀다(CSS로 감추지 않음) |

## 상태 값과 실패 처리

- 판정 4값·대조 3값·`availability`는 서버 enum 그대로. 새 상태 값 없음.
- **완료 판정에서만 새로 그리는 것**: 주의 포인트 블록, 한 줄 요약, 근본 원인 안내, 코드 행 묶음, 체크리스트 축약(좌측 요약은 원래 완료에서만 보인다).
- **상태와 무관하게 적용(표·목록 수준)**: 검증 실패 목록(지금처럼 격리가 있으면 어느 상태에서나 보임)의 번호 규칙 4·3건 접기·요구사항 보기, 표 규칙 5·6·10·"필수 여부 미표기"·주의 표식(주의는 완료일 때만 있음)·1280 숨김 — 부분표에도 같은 규칙.
- 그 밖의 상태별 배너(분석 중·사람 검토 필요·legacy·none·stale)는 바꾸지 않는다.
- `unitId`가 표에 없는 주의·격리 항목은 이동 버튼 없이 보인다(에러 아님).

## 저장

없음. 서버·DB·migration 변경 없음. 펼침·선택·필터는 컴포넌트 상태만.

## 인터페이스(CLI·UI·API)

화면만 바뀐다(`/opportunities/:id/verdict`, `/briefing`). 외부 호출 없음.

- **좌측(280px, 판정 완료; `OpportunityRecordPage`가 `VerdictSummary`에 `result`와 함께 `missingSections`(=`view.missing_sections ?? []`)·`rejectedUnitCount`(=`(view.rejected_units ?? []).length`)와 스크롤 콜백을 넘긴다):** 판정 이름(색 규칙 그대로) → **한 줄 요약**(규칙 2) → **근본 원인 안내**(규칙 7: "모든 요구사항이 확인 필요이고, 회사 사실과 연결된 요구사항이 없습니다. 회사 근거를 보강하면 판정이 구체화될 수 있습니다." + "회사 근거 보기" 링크 `/company`) → 사유(접기 그대로) → 체크리스트(규칙 9) → 다음 행동(규칙 3) → 고지 그대로. "판정 기준" 도움말은 두지 않는다(정의 문서 없음, 사용자 결정 2026-10-20).
- **중앙(판정 탭):** 누락 영역 배너(그대로, 완료 판정의 누락 영역 안내 위치) → **주의 포인트 블록** "주의 n"(완료이고 n>0일 때; 규칙 1, 5건 넘으면 "n건 더 보기") → 검증 실패 목록(규칙 4 번호, 항목마다 표에 있으면 "요구사항 보기", 3건 넘으면 "n건 더 보기", 설명: 첫 문장 "원문 근거 검증을 통과하지 못해 판정 근거에서 뺐고 자동으로 고치지 않았습니다. 담당자가 원문을 확인하세요." + `role_isolations`가 있을 때만 둘째 문장 "역할 판단이 격리된 요구사항은 확인 필요로 남습니다.") → 전 행 쪽 미확인 안내(규칙 6: "이 판정은 원문 쪽 위치를 연결하지 못했습니다. 행을 선택하면 원문 인용을 볼 수 있습니다.") → 요구사항 대조표.
- **대조표 `RequirementTable` props 추가:** `isolationLabels: Map<unitId, string>`(규칙 4 결과), `cautionUnitIds: Set<unitId>`(cautions와 conflicts 양쪽 unit), `revealUnitId: string | null`(규칙 11 대상; 바뀌면 필터 해제·페이지 확장·선택·스크롤 후 부모에 소비 알림), `hideCompanyColumn: boolean`(패널 열림 ∧ 뷰포트 < 1440; true면 표 컨테이너에 `is-compact` 클래스를 붙여 `.vd-table-scroll table`의 `min-width: 480px`를 해제). 원문 열 숨김(규칙 6)과 상태 select 숨김(규칙 10)은 표가 받은 행으로 스스로 판단한다. 표 내용: 주의 대상 행의 요구사항 칸에 "주의" 표식(warning 계열 pill), 격리 행 보조 줄 = "{격리 번호} · {규칙 문구}"(규칙 4 지도), 비격리 행 보조 줄의 `mandatory=null` 문구 "필수 여부 미표기", 회사 근거 열(규칙 5). 열을 숨길 때는 Astryx `Table` 열 정의에서 빼며 CSS로 감추지 않는다.
- **원문 패널 `SourcePanel`:** 기존 내용 + "역할 의견" 절 — 행의 `role_findings`를 역할 한글 이름 · 판단 한글 · `reason`(서버 문장 그대로) 순으로 모두 보인다(없으면 절 생략). 행 번호(`r<순번>`) 외 unit id 미노출 그대로.
- **1280 배치:** 패널 열림이고 뷰포트 폭 < 1440px이면 `hideCompanyColumn`(회사 근거 열 제거 + 표 `min-width` 해제). 표는 `.vd-table-scroll` 컨테이너 안에 들어가고(표 scrollWidth ≤ 컨테이너 clientWidth) 문서에 가로 스크롤이 생기지 않는다. 1440 이상은 열 유지.
- **브리핑:** 규칙 8(`lib/briefing.ts` 경로 함수 하나를 피크 패널 링크와 Enter 이동이 함께 쓴다).

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 주의 포인트를 중앙 표 위에 둔다 | 사용자 선택(2026-10-20). 폭이 넓어 긴 문장을 읽기 쉽고 행 이동과 가깝다 | 좌측 다음 행동 위(280px 줄바꿈 과다) |
| 주의 포인트에 unknown 묶음은 넣지 않는다 | 사용자 결정(2026-10-20). 표 보조 줄 "확인 필요 b"와 상태 필터가 이미 묶어 보인다 | 블록 끝 한 줄 추가 |
| 회사 사실 미연결 확인 필요 행은 표에서 고정 문구, 전문은 패널 | 사용자 선택(2026-10-20). 실데이터 515행 중 405행이 영어 시스템 문장이라 표 정보량이 0이고, 문장을 고치지 않는 원칙은 패널 전문으로 지킨다 | 문장 그대로(현행) |
| 전 행 쪽 미확인이면 원문 열 숨김 + 안내 한 줄 | 사용자 선택(2026-10-20). HP §8 "쪽이 없으면 점프를 만들지 않는다"와 일치 | 행마다 "쪽 미확인"(현행) |
| 요구사항 보기는 필터를 풀고 이동 | 사용자 선택(2026-10-20). 주의·불일치는 충족 행에도 생겨 기본 필터 밖일 수 있다 | 필터 유지·패널만 |
| 판정 기준 도움말은 두지 않는다 | 사용자 결정(2026-10-20). 4값 정의가 규칙 문서에 없어 화면이 정의를 지어내게 된다 | 제안 문구 추가 |
| 코드 "사람 확인" 행을 한 줄로 묶는다 | 독립 검토: 같은 문장 6~19개가 모델 다음 행동을 묻음. 서버 행은 그대로, 화면 접기만(사용자 지시 "프런트엔드만") | 서버에서 묶기(범위 밖) |
| 한 줄 요약에 차단 수 포함, 차단은 글자만 | HP §8 판정 카드 "차단 조건 수". 차단만 모은 블록이 없어 이동 대상이 없다 | 차단 버튼(대상 없음) |
| 격리 번호를 세 목록 합친 중복 제거 순번으로 통일 | 목록마다 `index+1`이면 같은 "영역 항목 1"이 다른 unit을 가리킨다(독립 검사). matrix는 대조 상태로 정렬돼 오고 unit id는 불투명 키라 matrix 순번·접두사 판정은 쓰지 않는다 | 목록별 순번(현행), matrix segment 순번 |
| 근본 원인 안내는 전 행 unknown ∧ 회사 사실 연결 0일 때만 | 화면이 원인을 지어내지 않도록 문구가 사실인 조건으로 좁힘(독립 검사) | 전 행 unknown만 |
| 체크리스트 축약·상태 select 숨김·"필수 여부 미표기" | 독립 UX 검토(2026-10-20) 개선 권고를 "프런트엔드 1차" 범위로 문서화하라는 사용자 지시. 상태 select 숨김은 ui-spec §4.4 기본 필터를 바꾸므로 STEP-006에서 정정 | 현행 유지 |
| 1280에서 패널 열림 시 회사 근거 열 숨김 | ui-spec §4.4 "1280px에서 가로 넘침 없음" 위반(측정 456px > 399px). 숨긴 내용은 패널 "역할 의견"에서 보인다 | 좌측 열 접기(판정 요약을 가림) |
| 브리핑 직행은 판정 이름 4값과 "사전규격 판정 참조"일 때만 | contracts 브리핑 절: 이 다섯 값일 때 같은 사업기회에 completed 판정이 있다. "분석 대기·분석 중·판정 대상 아님" 등은 판정이 없거나 진행 중 | 항상 직행 |
| "원문 탭에서 찾기" | N/A — 원문 탭이 사전규격 링크 빈 화면이라 새 열람 화면이 필요(범위 밖) | — |

## 테스트 케이스

Playwright `--project=app`, mock fixture(실데이터 아님, 카드 번호 형식은 fixture의 `REQ-…`). 1280×800·1440×900.

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | cautions 2 + conflicts 1(met 행)인 완료 판정 | "주의 3" 블록이 표 위에 있고 caution 문장이 서버 값 그대로, conflict는 "역할 의견이 다름: 기술 적합 충족 · 운영·위험 부족" 꼴. "요구사항 보기" → 해당 행 `aria-selected`, 화면 안 | 통합 |
| T2 | cautions·conflicts 0 | 주의 블록 없음, 요약 "주의 0" 글자(버튼 아님) | 통합 |
| T3 | cautions 7 | 5건 + "2건 더 보기", 누르면 7건 | 통합 |
| T4 | 표에 없는 unit의 caution | 문장만, "요구사항 보기" 없음 | 통합 |
| T5 | caution·conflict가 가리키는 표 행 | 두 행 모두 요구사항 칸에 "주의" 표식, 다른 행엔 없음 | 통합 |
| T6 | next_actions: model 2 + code 5, missing_sections 2, rejected 3 | 좌측 모델 2행 + "사람 확인 5건 / 원문에서 찾지 못한 영역 2 · 검증 실패 요구사항 3" 한 줄(접힘); 펼치면 코드 5행과 버튼 둘; "검증 실패 목록으로" → 목록 화면 안, "누락 영역으로" → 누락 배너 화면 안. rejected 0이면 "검증 실패 목록으로" 없음 | 통합 |
| T7 | 요약 | "차단 1 · 주의 3 · 사람 확인 5"; 차단은 글자, 주의 버튼 → 주의 블록 화면 안, 사람 확인 버튼 → 코드 묶음 펼침·화면 안 | 통합 |
| T8 | rejected_units: normalized_id 있는 것 1 + 없는 것 2, role_isolations: normalized_id 없는 것 1(다른 unit) + rejected와 같은 unit 1 | 목록 번호: 카드 번호, "격리 항목 1·2"(rejected), "격리 항목 3"(역할), 같은 unit은 같은 번호. 표의 rejected 행 보조 줄이 목록과 같은 번호, 역할만 격리된 행은 보조 줄 번호 없음. 목록 "요구사항 보기" → 표 행 선택 | 통합 |
| T9 | 세 목록 합계 5 | 3건 + "2건 더 보기" | 통합 |
| T10 | unknown + fact_labels 없음 / unknown + fact_labels 있음 / gap | 첫 행 "연결된 회사 사실 없음", 둘째·셋째 기존 규칙. 첫 행 선택 시 패널 "역할 의견"에 reason 전문 그대로 | 통합 |
| T11 | 모든 행 쪽 라벨 없음(page_range null 섞기 + mapping_status unavailable 섞기) / 한 행만 쪽 라벨 있음 | 앞: 원문 열 없음 + 안내 한 줄 / 뒤: 원문 열 있음, 안내 없음 | 통합 |
| T12 | 전 행 unknown·fact_labels 없음 / 전 행 unknown·한 행 fact_labels 있음 / 판단 불가 + met 섞임 / 조건부 진행 + gap | 첫째만 근본 원인 안내 + "회사 근거 보기" 링크 `/company` | 통합 |
| T13 | 체크리스트 5행 모두 unknown / 섞임 | 한 줄 "5개 조건 모두 확인 필요" + 펼치기 / 5행 | 통합 |
| T14 | 표 행 fit_status 모두 unknown / 모두 met / 두 종류 | 앞 둘: 상태 select 없음, 모든 행 보임("필수만" 있음) / 셋째: select 있음, 기본 "부족·확인 필요만" | 통합 |
| T15 | mandatory null 행 | 보조 줄 "필수 여부 미표기" | 통합 |
| T16 | 1280×800에서 행 선택(패널 열림), 실데이터처럼 긴 문장 fixture | 회사 근거 열 없음, 표 scrollWidth ≤ `.vd-table-scroll` clientWidth, 문서 가로 스크롤 없음; 1440×900 패널 열림은 회사 근거 열 유지·넘침 없음 | 통합 |
| T17 | 기본 필터 밖(met) 행을 가리키는 conflict의 "요구사항 보기", 50행 넘는 표의 뒤 행 | 필터 "전체"·필수만 끔·페이지 확장 뒤 그 행 선택·화면 안, 선택 유지 | 통합 |
| T18 | 기존 금지 검사 | 실무 화면 DOM에 unit id·정책 id·모델명·해시·`unmeasured_reference` 없음(새 블록 포함) | 통합 |
| T19 | 브리핑: verdict_display "조건부 진행" / "사전규격 판정 참조" / "분석 대기" | 앞 둘: 피크 링크·Enter가 `/opportunities/{id}/verdict` / 셋째: `/opportunities/{id}` | 통합 |
| T20 | 판정 미완료 상태(pending·needs_human_review, 부분표에 격리 있음) | 주의·요약·묶음·근본 원인 안내 없음, 검증 실패 목록은 보이고 번호 규칙 적용, 기존 배너 그대로 | 통합 |

## 컨벤션 반영 항목

없음(새 설정 키·상태 값·식별자 형식 없음).
