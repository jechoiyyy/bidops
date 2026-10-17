# RL-00 루트랩 회사 근거 fixture — 출처 기록과 dry-run

- 기능: `RL-00-company-ground-truth` STEP-004(회사 파일 작성). 기준 spec: [spec.md](../../../work/groups/RL/features/RL-00-company-ground-truth/spec.md) "회사 파일 `bidops.company-knowledge-source.v1` 확장"·"노드 value 스키마 확장"·"루트랩 회사 파일 구성 규칙".
- 작성일: 2026-10-16. 원본 파일은 Git 밖 `~/orca/fixtures/company/rootlab/`에 있다.
- 쓴 출처는 네 문서뿐이다: `docs/reference/company-profile.md`(회사소개서 기준, §8은 인터뷰 확인), `docs/reference/company-homepage-profile.md`(홈페이지 2026-10-16 열람), `docs/reference/company-preferences.md`(§1~§4 사용자 확인), `docs/1016_rootlab-redefinition/company-interview.md`(A~G 답).
- 이 기록은 등록·활성화 결과가 아니다. 문서에 없는 값은 `unknown`으로 두었고 추정값을 확인됨으로 올리지 않았다.

## 파일

| 파일 | 내용 |
|---|---|
| `ontology.v2.json` | `schema_version=bidops.company-ontology.v1`, `version=bidops.company-ontology.rl-v2`. HP 승인 온톨로지 v1(`docs/work/groups/HP/preparation/ontology.approved.v1.json`, 51 concept·11 관계)을 그대로 두고 `rl.*` 54 concept를 추가해 105 concept |
| `rootlab.source.v1.json` | `company={slug:"rootlab", name:"㈜루트랩", is_fictional:false}`, `scenario_version="rootlab-2026-10-16"`, 노드 148·관계 129 |

### 추가 concept (`rl.<kind>.<nn>`, label 한글)

| 범위 | 개수 | 출처 |
|---|---|---|
| `rl.qualification.01`~`09` | 9 | 인터뷰 자격 행: 입찰참가자격 등록(1468)·SW사업자 일반현황·신용평가등급·지점·정보보호·SW프로세스 인증·사회적기업·부정당 제재 없음·인력 자격증·창업기업확인서. 직접생산확인·중소기업확인·GS인증은 HP v1 concept(`qual.direct-production`·`qual.sme`·`qual.gs`)을 재사용 |
| `rl.qualification.10`~`23` | 14 | 회사소개서 인증 13종(profile §2.5)과 특허(§2.6) — `cert:*` 노드용 |
| `rl.domain.01`~`08` | 8 | preferences §1 관심 분야 8행 |
| `rl.domain.09`~`14` | 6 | preferences §2 제외·기피 조건 중 spec `kind` enum에 대응하는 6행 |
| `rl.domain.15`~`26` | 12 | preferences §3 반복 발주처 12곳(약칭 alias NIA·KISA·KERIS·NIPA는 profile §3.1·homepage §4.1 표기) |
| `rl.capability.01`~`05` | 5 | 사업 금액 조건·컨소시엄·하도급 조건·동시 수행·상주 상한·사업 기간 선호·마진·투찰률 기준 |

spec이 예상한 "약 40개"보다 많은 54개다. 차이는 회사소개서 인증·특허 14개(spec 구성 규칙의 "회사소개서에서만 확인된 사실(인증·특허·조직) → `company_brochure`"를 `cert:*` 노드로 옮기면서 concept가 필요해짐)이다.

## 노드 그룹별 출처

SourceRef는 spec대로 `{source_id:"self", locator:{json_pointer:"/nodes/<i>/value/..."}, quote}` 하나이며 quote는 그 위치의 scalar 그대로다. 출처 문서의 절·행·URL은 파일에 넣지 않고 아래에 적는다.

| 노드 그룹 | 개수(status) | origin | 출처 |
|---|---|---|---|
| `company:rootlab` | 1 confirmed | homepage | homepage §1 "회사명 ㈜루트랩 (RootLab)", https://www.rootlab.xyz/ |
| `qual:procurement_1468` | 1 confirmed `{held:true, detail:null}` | user_interview | profile §8.1 1행, interview A1 "자격 있음" |
| `qual:direct_production` | 1 confirmed `{held:true, detail:null}` | user_interview | profile §8.1 2행, interview A2 "자격 있음" |
| `qual:sme_certificate` | 1 confirmed `{held:true, detail:null}` | user_interview | profile §8.1 3행, interview A3 "자격있음" |
| `qual:sw_business` | 1 confirmed `{held:true, detail:null}` | user_interview | profile §8.1 4행, interview A4 "자격있음" |
| `qual:credit_rating` | 1 **proposed** `detail="BBB0 수준(2026-08 소개서 BBO 표기 기준), 설립 2022-09-23이므로 2029-09까지 창업 7년 이내"` | agent_proposal | profile §8.1 5행 값 칸 원문, interview A5 "확인불가. 너가 임의로 넣어줘", preferences §5 신용평가등급 행 |
| `qual:branch` | 1 confirmed `detail="대구(본점), 세종"` | user_interview | profile §8.1 6행, interview A6 "대구, 세종" |
| `qual:infosec_cert` | 1 confirmed `{held:true, detail:null}` | user_interview | profile §8.1 7행, interview A7 "보유" |
| `qual:social_enterprise` | 1 confirmed `detail="사회적기업"` | user_interview | profile §8.1 8행, interview A8 |
| `qual:sanction_free` | 1 confirmed `detail="해당 없음"` | user_interview | profile §8.1 9행, interview A9 |
| `qual:staff_certifications` | 1 confirmed `{held:true, detail:null}` | user_interview | profile §8.3 자격증 행 "전원 보유(종류 미입력)", interview C6 |
| `cert:venture`·`research_business`·`rnd_center`·`innobiz`·`mainbiz`·`iso_9001`·`iso_14001`·`iso_20000_1`·`iso_45001`·`kpaas`·`csap`·`kaci`·`tech_rating_t3` | 13 confirmed, `detail`=소개서 표기 그대로 | company_brochure | profile §2.5 `certifications.confirmed` 목록(§5.2 "확인됨"과 같음). 홈페이지 §5.1 연혁에도 같은 인증이 있으나 origin은 소개서 하나로 둠(홈페이지 표기 "T3-"와 소개서 "T3" 차이는 소개서 값 사용) |
| `cert:patents` | 1 confirmed `detail="등록 8건, 출원 18건"` | company_brochure | profile §2.6 `registered_patents: 8`, `patent_applications: 18`. 홈페이지 게시 9건·"29+"는 쓰지 않음(homepage §7) |
| `staff:total` | 1 confirmed `{role:"전체 임직원", total:58}` | company_brochure | profile §1 `employees.value: 58`, §2.7 `workforce.total` (as_of "2026-08"은 날짜 형식이 아니어서 value에 넣지 않고 label에 "2026-08 기준") |
| `staff:dev` | 1 confirmed `total=20` | user_interview | profile §8.3 기술 인력 행, interview C1 "개발 인력 20명" |
| `staff:planning` | 1 confirmed `total=15` | user_interview | profile §8.3, interview C1 "기획 인력 15명" |
| `staff:design_publishing` | 1 confirmed `available=5`, `total=null` | user_interview | profile §8.3 "분야별 투입 가능 — 디자인·퍼블리싱 5명", interview C3 |
| `staff:onsite` | 1 confirmed `{role:"onsite", available:6, region:"대구"}` | user_interview | 인원 6: preferences §4 최대 상주 인력(D4 확인); 지역: profile §8.3 "상주 가능 지역 대구만", interview C4 "대구". "대구 외 3명"은 넣지 않음(preferences §4가 폐기 명시) |
| `project:<year>-<nn>` | 63 confirmed | homepage | homepage §4.2 전체 목록(https://www.rootlab.xyz/businessPerformance) 63행을 표 순서대로, 연도별 순번. value는 `agency`·`year`만, `role`·`scope`·`amount_krw`·`started_on`·`ended_on`은 null |
| `pref:domain:01`~`08` | 8 confirmed `{tier, keywords, excluded:false, kind:null}` | user_interview | preferences §1 표 8행(등급→tier, 탐색 키워드 칸→keywords, 분야 칸→label) |
| `excl:hardware`·`staffing_only`·`design_only`·`election`·`region`·`amount_floor` | 6 confirmed `{tier:null, keywords, excluded:true, kind}` | user_interview | preferences §2 표(D6 "맞음") 1·2·3·4·6·7행. label은 조건 칸 원문, keywords는 조건 칸에 있는 낱말만 발췌. `excl:amount_floor`는 keywords=[] 표식이고 금액은 `pref:amount_floor`가 가진다 |
| `pref:agency:01`~`12` | 12 confirmed `{tier:null, keywords:[기관명], excluded:false, kind:null}` | user_interview | preferences §3 "발주처 우선순위(반복 실적)" 12곳, 순서 그대로 |
| `pref:amount_floor` `{krw:30000000}` | confirmed | user_interview | preferences §4 브리핑 최소 추정가격 3천만 원, interview D1 |
| `pref:amount_range` `{min_krw:100000000, max_krw:1000000000}` | confirmed | user_interview | preferences §4 선호 구간 1억~10억, interview D2 |
| `pref:solo_cap` `{krw:1500000000}` | confirmed | user_interview | preferences §4 단독 수행 상한 15억, interview D2 |
| `pref:consortium` `{over_krw:1000000000, over_onsite_count:8}` | confirmed | user_interview | preferences §4 컨소시엄 검토 조건, interview D3. "비보유 기술 요구" 조건은 수치가 없어 description에만 둠 |
| `pref:concurrent_cap` `{count:8, onsite_count:3}` | confirmed | user_interview | preferences §4 동시 수행 상한, interview D4 |
| `pref:onsite_cap` `{count:6}` | confirmed | user_interview | preferences §4 최대 상주 인력, interview D4·C4 |
| `pref:duration` `{min_months:6, max_months:12}` | confirmed | user_interview | preferences §4 사업 기간 선호 6~12개월 |
| `pref:subcontract` `{allowed:true, max_ratio_percent:10}` | confirmed | user_interview | preferences §4 하도급 "원칙 미사용, 디자인·콘텐츠만 10% 이내" |

관계 129개: `holds_qualification`(company→`qual:*`·`cert:*` 38), `has_staff`(8), `performed`(66), `operates_in`(company→`pref:domain:*` 8), `has_capability`(company→`pref:*` 9). 관계의 status·origin은 대상 노드와 같고 source_ref는 대상 노드의 것을 재사용한다. unknown 대상은 관계도 `unknown`/`user_interview`/`[]`. project→domain `operates_in`과 project→capability 관계는 홈페이지 표에 분야가 적혀 있지 않아 만들지 않았다. `excl:*`·`pref:agency:*`는 "업무 분야" 관계가 아니므로 관계 없이 둔다. evidence(`ev:`) 노드는 두지 않았다(선택 사항, 노드 상한 여유).

## 문서에 없어 unknown으로 둔 항목

모두 `status=unknown`, `value=null`, `source_refs=[]`, `origin=user_interview`.

| 노드 id | label | 근거(문서가 비어 있다고 적은 곳) |
|---|---|---|
| `qual:procurement_1468:extra_industries` | 입찰참가자격 추가 업종 | profile §8.1 1행 남은 세부 "추가 업종", interview A1 답은 "자격 있음"뿐 |
| `qual:procurement_1468:renewed_on` | 입찰참가자격 등록 갱신일 | profile §8.1 1행 남은 세부 "갱신일" |
| `qual:direct_production:items` | 직접생산확인증명서 세부품명 목록 | profile §8.1 2행, interview G1 미응답 |
| `qual:direct_production:valid_until` | 직접생산확인증명서 유효기간 | profile §8.1 2행, interview G1 미응답 |
| `qual:sme_certificate:valid_until` | 중소기업 확인서 유효기간 | profile §8.1 3행 |
| `qual:sw_business:fiscal_year` | SW사업자 일반현황 관리확인서 결산연도 | profile §8.1 4행 |
| `qual:sw_business:no_limit_notation` | 제한금액 없음 표기 | profile §8.1 4행 |
| `qual:credit_rating:valid_until` | 신용평가등급 유효기간 | profile §8.1 5행, interview G6 미응답 |
| `qual:startup_certificate` | 창업기업확인서 보유 | profile §8.1 5행 남은 세부 "창업기업확인서 보유", interview G6 미응답 |
| `qual:branch:sejong_registration` | 세종 지점 등기 형태 | profile §8.1 6행 |
| `qual:infosec_cert:kind` | 정보보호·SW프로세스 인증 종류 | profile §8.1 7행, interview G4 미응답 |
| `qual:social_enterprise:valid_until` | 사회적기업 인증서 유효기간 | profile §8.1 8행 |
| `qual:staff_certifications:kinds` | 인력 자격증 종류 | profile §8.3 "종류 미입력" |
| `qual:gs_certification` | GS인증 | profile §5.2 `qualification_unknowns`, §8.5 "세부 값이 남은 것" 16 |
| `staff:pm` | PM 가능 인력·경력 | profile §8.3 "미응답", interview C2·G3 빈칸 |
| `staff:grade_distribution` | SW기술자 등급별 분포 | profile §8.3 "등급별 분포는 unknown", interview G3 |
| `staff:dispatch_partner` | 파견·협력사 인력 | profile §8.3, interview C5 "알 수 없음" |
| `project:certified_list` | 최근 3년 실적증명 발급 가능 사업 목록 | profile §8.2 "목록은 미입력", interview B1 "존재함"·G2 미응답 |
| `project:web_cms_list` | 홈페이지·포털·CMS 실적 건별 목록 | profile §8.2 "건별 목록 미입력", interview B2 |
| `project:current_list` | 현재 수행 중 사업 목록 | profile §8.2 unknown, interview B4 "알 수 없음" |
| `pref:margin` | 목표 마진·투찰률 기준 | preferences 머리말 "마진·투찰률(D7)은 unknown", interview D7 |

## 옮기지 않은 사실과 판단 기록

- 홈페이지 실적은 행 63·고유 사업명 57이다(homepage §4). spec "57건"은 고유 사업명 수이고 id 규칙이 "같은 사업명의 연차는 연도로 구분"이므로 63행 전부를 노드로 만들었다(2025년 "블록체인 기반 자원봉사은행 플랫폼 운영 및 유지관리 용역"은 발주처가 `부산광역시`·`부산광역시자원봉사센터`로 다른 두 행이라 둘 다 둠). 노드 148개로 상한 256 안이므로 잘라 낸 실적은 없다.
- preferences §2의 "대기업 참여 허용(20억 이상) 전국 대형 SI — 기피(컨소시엄 참여만)"는 spec `kind` enum(hardware·staffing_only·design_only·election·region·amount_floor)에 맞는 값이 없고 `excluded=true`면 kind가 필수라 `excl:*` 노드로 만들지 않았다. 금액 조건은 `pref:solo_cap`(15억)·`pref:consortium`(10억 초과)이 가진다.
- preferences §3 유형 우선순위(D8: 운영·유지관리 = 고도화 = 구축 > R&D)와 §4 지역 우선순위(대구·경북 최우선, 부산·서울·전국 허용)는 spec 구성 규칙에 노드 id가 없어 넣지 않았다. 지역 사실은 spec대로 `staff:onsite.region`과 `qual:branch.detail`로만 표현한다.
- profile §8.2 "홈페이지·포털·CMS 실적 존재함"·"2022-09 이전 실적의 법인 귀속 증명 가능(confirmed)"은 project value에 보유 여부를 담는 키가 없어 노드로 만들지 않았다(건별 목록은 unknown 노드로 둠).
- profile §8.4 제안서 자산·운영(과거 제안서 없음·형식·Slack·브리핑 시각)은 spec대로 그래프에 넣지 않았다.
- 회사소개서의 기술·사업영역·수상, 홈페이지 전용 인증(산업디자인전문회사·ESG·엔지니어링 사업자·병역지정업체 등)과 솔루션 카탈로그는 spec 구성 규칙 범위 밖이라 넣지 않았다.
- `pref:subcontract.allowed=true`는 "원칙 미사용, 디자인·콘텐츠만 10% 이내"를 bool로 옮긴 판단이다(디자인·콘텐츠 한정 허용). 원문은 description에 그대로 있다.
- `staff:design_publishing`은 원문이 "투입 가능 5명"이라 `available=5`, `total=null`로 두었다(spec 괄호 "(5)"를 총원으로 읽지 않음).
- 기존 HP concept 재사용: `qual:direct_production`→`qual.direct-production`, `qual:sme_certificate`→`qual.sme`, `qual:gs_certification`→`qual.gs`. 세부 unknown 노드는 부모 노드와 같은 concept_id를 쓴다.

## 오프라인 점검

scratchpad 점검 스크립트(평문 python3, BidOps 코드 import 없음)로 id 규칙·status×origin·concept 존재·중복 id·value 스키마(spec 표)·self source_ref 대조·관계 재사용·온톨로지 label/alias 모호성·온톨로지 canonical SHA-256과 회사 파일 `ontology_sha256` 일치를 검사했다. 위반 0.

| 항목 | 값 |
|---|---|
| 노드 | 148 (non-evidence 148) |
| status_counts | confirmed 126 · proposed 1 · inferred 0 · unknown 21 |
| origin | homepage 64 · user_interview 68 · company_brochure 15 · agent_proposal 1 |
| 타입별 | company 1 · qualification 38(confirmed 23·proposed 1·unknown 14) · staff_group 8(confirmed 5·unknown 3) · project 66(confirmed 63·unknown 3) · domain 26(confirmed 26) · capability 9(confirmed 8·unknown 1) |
| 관계 | 129 (confirmed 107 · proposed 1 · unknown 21) |
| 온톨로지 | 105 concept(rl.* 54: qualification 23·domain 26·capability 5) |

## dry-run

2026-10-16 T9, STEP-001 검증기 반영 뒤 실제 CLI(`BIDOPS_DEMO_ENABLED=false`, 임시 SQLite·filesystem, DB 미사용):

```text
python -m app.deep_review.cli import-company-knowledge \
  --ontology ~/orca/fixtures/company/rootlab/ontology.v2.json \
  --company ~/orca/fixtures/company/rootlab/rootlab.source.v1.json \
  --actor "RL-00 dry-run" --dry-run
exit=0
errors=[]  is_fictional=false  ontology_version=bidops.company-ontology.rl-v2
status_counts={confirmed:126, proposed:1, inferred:0, unknown:21}
source_sha256=76b78132464e69731e9295f4be260987b824a50373691ef25b323c55b7ef8e83
graph_sha256=a179624a566397126bd85df13a1978a3292239039d93fe1db14865639b30e0e1
```

status_counts는 자체 검사기 결과와 같다(비evidence 노드 148개).

## SHA-256

| 파일 | 값 |
|---|---|
| `~/orca/fixtures/company/rootlab/ontology.v2.json` (파일 bytes) | `7e6f4d8a51a65907460f60aedb20dd96a15ddaa0e65ff707a0dd7aa58f7f96d7` |
| `~/orca/fixtures/company/rootlab/ontology.v2.json` (canonical JSON, 회사 파일 `ontology_sha256`) | `4d0f95c274e18c5774d9254f6d36a8125ade2844b7b2ff2a6593f95a001d7a15` |
| `~/orca/fixtures/company/rootlab/rootlab.source.v1.json` (파일 bytes = `source_sha256`) | `76b78132464e69731e9295f4be260987b824a50373691ef25b323c55b7ef8e83` |

## STEP-006 격리 등록·활성화 (bidops-local `bidops_rla`)

- 환경: `COMPOSE_PROJECT_NAME=bidops-local` 안의 새 DB `bidops_rla`(사용자 결정 2026-10-16; 기존 `bidops` DB는 HP-03 migration `0039`에 있어 main 계열 `0037`과 이력이 갈라짐). 기존 web·DB는 건드리지 않음. 이미지 `bidops-local:rla-20261016-rl00`(RL-00 worktree 빌드, linux/amd64). 일회용 서비스 `rla-migrate`·`rla-web`(내부망 database·storage·scanning만, 모델·첨부 egress 없음, `BIDOPS_DEMO_ENABLED=false`).
- `rla-migrate`: `alembic upgrade head` + `scripts/runtime-privileges.sql` exit 0.
- import(exit 0): `company_id=fef3800f-6669-490b-aa1e-f6d7b163fa20`, `graph_version_id=3437d2fc-487c-4ac9-9347-c648e5b8cdc1`, `profile_version_id=8ac7293a-95ff-42ed-a09b-834b56cb87d1`, `created=true`, `is_fictional=false`, `status_counts={confirmed:126, proposed:1, inferred:0, unknown:21}`, `graph_sha256=a179624a566397126bd85df13a1978a3292239039d93fe1db14865639b30e0e1`.
- activate(exit 0): `changed=true`, `revision=1`.
- REST(rla-web 내부 호출): `GET /api/company` 200, 키 4개 정확(`schema_version=bidops.company-context.v1`, `company.name=㈜루트랩`, `is_fictional=false`, `expiry_warning_days=60`, `active_graph_version.graph_version_id`=위 값); `GET /api/companies/{id}/profile` 200, facts 148(= 비evidence 노드 수, confirmed 126·proposed 1·unknown 21); `staff:onsite` confirmed·`region="대구"`·`available=6`(대구 외 표기 없음); `GET /api/workload` `company_attention` count 22(=proposed+unknown), 키 순서 끝.
- 검사 뒤 `rla-web` 컨테이너는 제거했다. DB `bidops_rla`와 volume `bidops-local_rla-web-data`·`bidops-local_rla-pipeline-data`는 RL-01·02 시운전에서 이어 쓰려고 남겼다.

## v2 재등록 (2026-10-17, RL-01 지역 규칙 정합)

- 사유: RL-01 브리핑 지역 제외 규칙은 `excl:region.keywords`를 **허용 지역 이름**으로 읽는다(RL-01 spec "결정적 점수와 제외"). v1은 `["지역제한"]`이라 지역제한 공고가 거의 전부 제외된다. 사용자 결정(2026-10-17): **대구·세종**. 근거 preferences "지역제한 입찰에서 본점 소재지(대구) 외 지역 제한 → 제외", "지역제한 입찰: 대구 본점, 세종 지점"(세종 지점 등기 형태는 unknown이므로 세종 제한 공고를 제외하면 unknown을 차단 조건으로 쓰게 됨 → 허용에 포함).
- 변경: `excl:region.value.keywords` `["지역제한"]` → `["대구","세종"]` 한 곳. 새 파일 `rootlab.source.v2.json`(v1은 그대로 보존).
- `rootlab.source.v2.json` sha256 `5ffdcef056448639e0e43b18cd9ad24654bca774ce00c337ebca184a11d4f952`, graph_sha256 `a638050fb0a886868f1a2f19d59be8445688b12ea065a2c32f2f0cc944b228f0`, status_counts 동일(c126·p1·u21).
- bidops-local `bidops_rla`: dry-run exit 0 → import `created=true`, `graph_version_id=089239e1-77d5-4fad-9893-1e3f293c294f`, `profile_version_id=8b2eca53-be22-49c0-834f-6e766e9a8440` → activate `revision=2`(이전 3437d2fc… 버전 불변).
