# 사전규격 상세 `분석 완료` 화면 재구성 — 구현 설계 (2026-11-24)

## 0. 목표와 정본

- 실무자 리뷰 두 번을 거친 시안 `mockup/index.html`(데이터 `mockup/data.js`, 첫 화면 캡처 `mockup/first-1440.png`)을 **앱의 `분석 완료` 화면으로 그대로 옮긴다.** 배치·구역 순서·문구·조작·폭별 동작이 정본이다. 시안 HTML을 브라우저로 열어(`python3 -m http.server`로 `mockup/` 제공) 직접 조작해 보고 맞춘다.
- 시안은 4186 한 건의 정적 데이터로 만들었다. 앱은 **모든 사업의 실제 API 응답**으로 같은 화면을 그려야 하므로, 시안에서 손으로 정한 값(쟁점 제목, 사유·전제와 쟁점의 연결, 쪽 번호)은 아래 §4의 결정적 규칙으로 바꾼다. 그 밖의 차이는 §6에 적은 것만 허용한다.
- 이 화면은 지금처럼 **mock 빌드(`BIDOPS_REVIEW_MOCK`)와 포트폴리오 빌드(`BIDOPS_PORTFOLIO_ANALYSIS=1`)에서만** 번들에 들어간다. 운영 빌드 경계(`prespec-detail-layout.spec.ts`의 번들 검사)는 바꾸지 않는다.

## 1. 범위

| 구분 | 바꾼다 | 바꾸지 않는다 |
|---|---|---|
| 백엔드 | 읽기 전용 endpoint 1개 추가(§3), 그 테스트, 계약 문서 한 줄 | DB·migration·엔진·개요 실행기·다른 endpoint |
| 프런트 | `분석 완료` 화면(엔진 run이 있을 때) 본문·머리 사실 줄·탭·PDF 서랍, 해당 CSS, 타입, spec | 분석 전 화면(엔진 run 없음)의 모든 것, 셸 공용 동작, 다른 route, 테마 값 |
| 결정 띠 | 기존 `TrackingDecisionControl`(bar, after-analysis) 그대로 사용 — 시안의 흐름과 이미 같다 | 저장 API·사유 예시·종료 확인·이탈 확인 |

## 2. 읽어야 할 것

- 저장소 `AGENTS.md`, `docs/standards.md`, `docs/engineering-notes.md`, `web/frontend/AGENTS.md`, `web/backend/AGENTS.md`.
- 현재 구현: `web/frontend/src/pages/PreSpecDetailPage.tsx`(`analysisView` 분기, `PreSpecTrackingBar`), `web/frontend/src/components/pre-spec-analysis/PreSpecAnalysisView.tsx`, `web/frontend/src/styles/pre-spec-analysis.css`, `web/frontend/src/lib/engineApi.ts`, `web/frontend/src/lib/companyWikiApi.ts`(`wiki.portfolio`, `wiki.pages`), `web/frontend/src/lib/api.ts`(개요·PDF URL), `web/frontend/src/components/shell/route-meta.ts`·`styles/shell-relaxed.css`(읽기 폭), `web/frontend/tests/prespec-analysis-view.spec.ts`·`tests/api-mock.ts`·`tests/fixtures/engine-analysis.ts`.
- 백엔드: `web/backend/app/deep_review/routers/overviews.py`(`get_overview_pdf`), `web/backend/app/deep_review/services/overview_runs.py`(`run_snapshot_pdf`), `web/backend/app/deep_review/services/pdf_snapshot.py`(`read_snapshot_page_text`, `safe_snapshot`).

## 3. 백엔드: 개요 run의 쪽별 텍스트 endpoint

`GET /api/pre-specs/{notice_id}/overview/runs/{run_id}/page-text`

- 경계는 같은 router의 `GET …/runs/{run_id}/pdf`와 **완전히 같다**: 다른 공고의 run·스냅샷 없는 run은 `not_found`, 문서·원본이 지금 current·safe가 아니면 `document_not_current_safe`. 서비스 함수 `run_snapshot_page_text(session, notice_id, run_id, *, store=None)`를 `overview_runs.py`에 `run_snapshot_pdf` 옆에 두고, 스냅샷 확인 코드는 둘이 공유한다(복제하지 않는다).
- 읽기는 `read_snapshot_page_text(session, store, snapshot)`이며 store는 `object_store(namespaces=("structure",), read_namespaces=("structure",))`다(쪽별 텍스트는 `structure` namespace에 저장된다). `V4OpsError`·읽기 실패는 새 코드 `page_text_unavailable`(HTTP 409, 메시지 "고정된 쪽별 텍스트를 읽지 못했어요.")로 닫는다. `_STATUSES`·`_MESSAGES`에 추가한다.
- 응답(200, `application/json`):

```json
{
  "schema": "bidops.prespec-overview-page-text.v1",
  "run_id": "…", "notice_id": 4186,
  "document_version_id": "…", "pdf_sha256": "…",
  "page_count": 132,
  "pages": [{ "number": 1, "display_page": "…또는 null", "text": "…" }]
}
```

  - 저장된 산출물 스키마는 두 가지다: `bidops.prespec-v4-page-text.v1`(`number`·`text`) 와 `bidops.rhwp-page-text.v1`(`number`·`display_page`·`section`·`text`). 두 경우 모두 위 모양으로 정규화하고 `display_page`가 없으면 `null`이다. 다른 스키마나 `number`가 1부터 연속이 아니면 `page_text_unavailable`.
  - `page_count`·`pdf_sha256`·`document_version_id`는 run/스냅샷에 저장된 값이다. 다시 계산하지 않는다.
  - 텍스트는 원문 그대로다. 잘라 내거나 정규화하지 않는다.
- 테스트: 기존 개요 PDF endpoint 테스트가 있는 `web/backend/tests/app/test_overview_api.py`에 같은 방식으로 추가한다 — 정상(두 스키마), 다른 공고의 run, 스냅샷 없음, unsafe 문서, 산출물 읽기 실패, 이상한 스키마. **host에서 백엔드 pytest를 돌리지 않는다**(실행 환경이 없다). 리더가 release image에서 돌린다.
- 계약 문서: `docs/contracts/`의 개요 계약 파일(개요 PDF endpoint가 적힌 곳)에 endpoint·응답·오류 코드를 한 단락으로 추가한다.

## 4. 프런트: 데이터 연결과 결정적 규칙

### 4.1 화면 구성(시안 그대로)

`analysisView`(엔진 run 있음)일 때 `PreSpecDetailPage`는 기존 `RecordFrame`(정보 열 포함) 본문 대신 새 컴포넌트 `PreSpecAnalysisWorkbench`를 그린다. 구성 요소와 순서는 시안과 같다.

1. **셸 머리**: `usePageHeader`로 제목과 사실 줄(시안 순서: 의견 마감+D-n · 수요기관 · 공고기관 · 게시 · 사전규격번호 · 구분 · 본공고). 품질 표식(`참조 실행 · 품질 미측정` 등, `qualityStatusLabel`)은 머리 액션 자리에 둔다. 시안의 `개선 시안` 표식·사이드바 안내 문구·토스트는 옮기지 않는다.
2. **탭**(`PageHeaderTabs`): 한눈에 · 쟁점 n · 요구사항 n · 자격·계약 n · 원문·처리 정보 + 오른쪽 안내 "쪽 단추는 제안요청서 PDF의 그 쪽을 열어요". 스크롤 위치를 따라 활성 탭이 바뀐다(시안 `spy`). 탭 클릭은 해당 구역으로 스크롤한다.
3. **한눈에**: 왼쪽 — 사업 목적(개요 `business_overview` 중 "사업 목적"으로 시작하는 주장), 사업 금액 대조, 주요 과업(`main_tasks`), 추진 배경(나머지 `business_overview` 중 "사업명"이 아닌 것, 기본 접힘), 사업 기간. 오른쪽 — 세 층(엔진 참고 의견 / 추적 판단 / 최종 입찰 결정), 엔진이 ‘조건부’로 본 이유(`recommendation.why_not`), 심각도 상인데 사유에 없는 쟁점 안내 줄. **구역 제목 ‘무슨 사업인가요’·‘추적을 이어가려면’은 없다**(최종 시안 기준).
4. **쟁점**: 엔진 `risks` 전부. 필터(전체 · 조건부 사유 · 참여 전제만 · 심각도 상), 범례, 행 펼침(원문 근거·엔진 설명·엔진이 제안한 대응 / 엔진 의견과의 관계·확인 요청 자료·같은 원문 문장을 인용한 요구사항).
5. **요구사항 대응**: 회사 근거 안내 줄, 필터(대응 칩·분류 select·검색·회사 근거 없는 것만·건수), 목록|상세 두 칸, ↑↓ 이동, 이전/다음 단추, `#req=<id>` 주소.
6. **자격·계약 조건**: 참가 자격 표(판정 표식 + 쪽 단추 + 원문 요약 + 접힌 "판정에 쓴 회사 값") + 데모 입력 안내, 계약·평가 조건 표.
7. **원문·처리 정보**: 펼친 구역(토글 아님). 시안의 여덟 항목과 문장 그대로(값은 응답에서).
8. **PDF 서랍**: 오른쪽 고정 서랍. 머리(제목·`n쪽 / 전체쪽`·이전 쪽·다음 쪽·새 탭·닫기(Esc)), 인용 문장 위치 발췌(`<mark>` 강조, 앞뒤 160자), 아래 PDF iframe(`…/overview/runs/{run_id}/pdf#page=n&view=FitH`, 쪽을 바꿀 때 iframe을 새로 만든다). 연 단추로 초점 복귀.
9. **하단 결정 띠**: 기존 `PreSpecTrackingBar`(after-analysis)를 그대로 쓴다. 시안의 왼쪽 줄(현재 추적 상태 + 사유 · 담당자 · 날짜)과 같은 정보가 나오는지만 맞춘다.

`처리 상태·기술 정보` 접힘 구역은 `problem`(처리 문제)이 있을 때만 `원문·처리 정보` 아래에 기존 그대로 붙인다(실패를 숨기지 않는다). 문제가 없으면 시안처럼 없다.

### 4.2 값의 출처

| 화면 값 | 출처 |
|---|---|
| 제목·마감·게시·공고기관·첨부 파일명 | `GET /api/notices/{id}` (`title`, `deadline_at`, `published_at`, `agency`, `attachments[].acquired_file.filename`) |
| 수요기관·사전규격번호·구분·SW사업대상·사업기회 id·추적 상태 | `GET /api/pre-specs?notice_pk=` 항목 |
| 추적 사유·기록자·시각 | `GET /api/opportunities/{id}` (`tracking_reason`, `tracking_selected_by`, `tracking_selected_at`) — 기록자는 받은 문자열 그대로 |
| 본공고 | 기존 `lifecycle.bid_ntice_no_list`, 없으면 `미확인` |
| 사전규격 등록액 | `notice.budget`(없으면 `예산 미제공`), 출처 문구 "나라장터 사전규격 등록 정보(사전규격번호)" |
| 제안요청서 사업금액 | 엔진 `facts.project.budget_krw`와 `vat_included`; 쪽 단추는 개요 `budget_and_period`에서 "금액"을 포함한 주장의 근거 쪽, 그리고 엔진 `facts.project.evidence` 중 `VAT|부가` 인용의 PDF 쪽(§4.3) |
| 차이 | 두 값이 모두 있을 때만 `|등록액 − 사업금액|`과 어느 쪽이 큰지. 이유 문장은 항상 "차이가 생긴 이유는 수집한 자료에 없어요." — 자료에 이유 필드가 없다 |
| 개요 주장·근거 쪽·인용 | 기존 개요 응답의 현재 run(`shown`) 주장(`text`, `evidence[].page`, `evidence[].quote`) |
| 엔진 의견·사유·전제·확인 요청·리스크·요구사항·자격·계약·평가·회사 근거 입력·인용 건수·수익성 | 엔진 run `analysis`의 해당 필드(시안 `data.js`의 `engine` 키와 1:1). 응답에 이미 있는 필드는 `engineApi.ts` 타입에 추가해 쓴다(`any` 금지) |
| 회사 실적 이름·발주처·기간·유형·역할 | `GET /api/company-wiki/portfolio`의 `items[]` (`id`로 찾음). 값이 `unknown`/없음이면 `미확인`. 실적 열기 링크는 `/company?view=portfolio&project=<id>` |
| 회사 근거 위키 쪽 이름 | `GET /api/company-wiki/pages`의 `pages[].slug → title`, 실적 코드는 위 portfolio 이름. 못 찾으면 받은 slug 그대로 |
| 쪽별 텍스트 | §3 endpoint (개요 현재 run id) |

판단 사유(`rationale`)의 `[[<실적 코드>]]`는 실적 이름(코드는 `title` 속성)으로 바꿔 보인다. 화면 어디에도 `[[`가 남지 않는다.

### 4.3 엔진 인용 → PDF 쪽 (결정적 규칙)

- 엔진 인용은 HWPX 절만 가리킨다. 개요 현재 run의 `document_version_id`가 엔진 run `documents[].document_version_id` 중 하나와 **같을 때만** 그 run의 쪽별 텍스트에서 찾는다. 다르면 모든 엔진 인용은 `쪽 없음`이다.
- 정규화: 공백과 `❍ ○ • · - – — ‧ ㆍ`를 지운 문자열에서 인용(정규화)이 들어 있는 쪽을 찾는다. 인용이 4자 미만이면 찾지 않는다.
  - 정확히 한 쪽에 있으면 그 쪽(`exact`).
  - 여러 쪽에 있으면 가장 앞 쪽, 표기는 `exact`와 같다(현재 데이터에서는 없다).
  - 한 쪽에 없고 이웃한 두 쪽을 이은 문자열에 있으면 앞 쪽(`span`).
  - 없으면 `not_found` → `쪽 없음`.
- 서랍의 발췌 강조도 같은 정규화로 원문 위치를 되짚어 `<mark>`를 건다(시안 `highlight`). 개요 인용도 같은 함수로 강조한다.
- 이 함수는 `lib/pdfQuoteLocator.ts` 하나에 두고 화면은 결과만 쓴다. 쪽별 텍스트를 받는 중에는 쪽 단추 자리에 `쪽 찾는 중`, 실패하면 `쪽 없음`과 서랍 대신 PDF 새 탭 링크.

### 4.4 쟁점 제목과 사유·전제·확인 요청의 연결 (결정적 규칙)

시안의 쟁점 제목과 연결은 4186을 보고 손으로 붙인 것이라 그대로 옮길 수 없다. 다음 규칙으로 대신한다.

- **쟁점 제목**: 리스크의 원문 인용(`evidence.quote`)을 그대로 한 줄 말줄임으로 보인다(전체는 `title` 속성과 펼친 본문). 시안이 지은 요약 제목은 쓰지 않는다. 첫 화면의 "쟁점: …" 링크와 요구사항 상세의 "관련 쟁점"도 같은 문자열이다.
- **같은 원문 문장을 인용한 요구사항**: 리스크 인용과 요구사항 인용이 §4.3 정규화 후 같으면 연결한다.
- **사유(`why_not[i]`)·전제(`preconditions[i]`)·확인 요청(`review_actions.requests` 중 `kind="execution"`의 `title + why`) → 리스크 한 건**:
  - 토큰: 정규식 `[0-9][0-9,.]*\s*(?:명|건|일|개월|년|%|원)?|[A-Za-z]{2,}|[가-힣]{2,}`로 뽑고 공백 제거. 한글 토큰은 끝의 조사(긴 것부터: 으로·에서·에게·까지·부터·이며·이고·하고·되어·되며·하며·하는·되는·한다·된다·이다·은·는·이·가·을·를·의·에·와·과·로·도·만·및)를 남는 길이 2 이상일 때 한 번 뗀다. 불용어(확인·확인한다·있는지·요구·요구된다·요구되며·요구되지만·제공·자료·근거·회사·현재·해당·필요·경우·관련·사업·수행·범위·기준·이상·대한·없는·없이·등·통해·위한)와 1자 토큰은 버린다.
  - 리스크 쪽 토큰은 `evidence.quote + " " + description`. 점수는 공유 토큰의 가중합(숫자·영문으로 시작하면 3, 한글 1).
  - 최고 점수가 **5 이상**인 리스크 하나에 연결한다. 동점이면 리스크 인용(`quote`)만으로 센 점수가 큰 쪽, 그래도 같으면 앞 index.
  - 이 연결은 엔진 출력이 아니다. 범례 문장 "사유·전제와 리스크의 연결은 엔진 출력이 아니라 화면이 문장을 대조해 붙였어요."를 쟁점 구역과 첫 화면 사유 목록 아래 둘 다에 둔다.
- 규칙은 `lib/engineRiskLinks.ts` 하나에 두고 단위로 검사한다. 4186 실제 데이터 기대값(why_not → 리스크 index): 0→3, 1→2, 2→1. 전제: 0→3, 1→2, 2→4, 3→5, 4→0, 5→7, 6→없음. 확인 요청: 0→3, 1→2, 2→0, 3→7, 4→6. (index는 `analysis.risks` 순서.)

### 4.5 기타 규칙

- 정렬: 쟁점은 심각도(H→M→L), 같은 심각도에서 사유 연결 있는 것 먼저, 그다음 원래 순서. 요구사항은 대응(GAP→UNKNOWN→PARTIAL→FULL), 같으면 원래 순서.
- 분류 select는 `req_id`의 `-` 앞 접두어. 이름 표(SFR 기능, SER 보안, PER 성능, INR 인터페이스, DAR 데이터, TER 테스트, QUR 품질, COR 제약사항, PMR 프로젝트 관리, PSR 프로젝트 지원, ECR 장비 구성)에 없으면 접두어만.
- 검색은 id·이름·정의·사유(실적 이름 치환 후)·원문 발췌·보완 방안을 대소문자 무시 포함 검색.
- 데모 입력 안내: `assessment.provisional.demo_fields`가 있으면 "자격 판정에 쓰인 회사 값 가운데 n개는 데모 입력이에요." 그리고 `input_fields`가 그 필드와 접두가 같은 자격 행에 `데모 입력` 표식(중립색). 시안의 한국어 필드 이름 나열은 쓰지 않는다.
- 회사 정보 확인 요청 건수는 `review_actions.requests` 중 `purpose="scoring"` 수, 예시는 그 첫 항목의 `title`.
- 인용 건수 문장은 `analysis.citations`(total·verified·unverified)를 그대로. 쪽 연결 문장(“인용 n문장 가운데 m개는 …”)은 화면이 실제로 찾아 본 인용 수로 만든다.
- 개요 경고 코드의 뜻 문장은 시안의 `OV_WARN` 세 개만 번역하고 모르는 코드는 "뜻이 등록되지 않은 경고예요."와 코드를 그대로 보인다.
- 값 없음·미확인·계산 불가·0을 구분한다. 화면에 없는 회사 역량이나 판정 사유를 만들지 않는다.

## 5. 배치·스타일

- 시안 CSS 값을 옮기되 색은 테마 토큰(`--color-*`, `--bo-line-soft` 등)으로, 글자·조작 높이는 `--bo-k-*` 단으로 바꾼다. `:root`·화면 CSS에서 `--color-*`를 재정의하지 않는다. 새 CSS는 `styles/pre-spec-analysis-workbench.css` 한 파일, 선택자는 화면 루트 접두(`.paw-`)로 가둔다. 기존 `pre-spec-analysis.css`의 옛 규칙은 더 쓰지 않으면 지운다.
- 읽기 폭: `analysisView`일 때 `.app-content`에 `data-reading-width="analysis"`를 달아(셸의 `detailReadingWidth`와 같은 방식) 패널 헤더 안쪽·본문·하단 띠 안쪽을 같은 최대 폭(1240px, 1800px 이상에서 1400px)으로 가운데 정렬한다. 분석 전 화면은 지금의 `detail`(1040px) 그대로.
- 스크롤하면 머리를 줄인다(시안 `compact`: 60px 넘게 내려가면 사실 줄의 보조 항목을 숨기고 제목을 17px 한 줄로). 셸 공용 동작을 바꾸지 말고 이 화면이 붙어 있는 동안에만 `.app-content`(또는 셸 루트)에 `data-header-compact`를 달고 해제할 때 지운다. CSS는 `[data-reading-width="analysis"][data-header-compact="true"]`로 가둔다.
- 요구사항 목록은 ADR-0077대로 공용 `RecordTable` + `useRowKeyboardNavigation`(행 `<tr>`이 `rowProps`를 받음)으로 그리고, 열·행 모양(56px 두 줄 행, 열 폭 ID 80 · 대응 74 · 회사 근거 150/170/240 · 원문 64)은 시안과 같게 맞춘다. 목록|상세 높이는 시안처럼 화면 높이에 맞춘 고정 칸(`calc(100vh - 290px)`, 최소 460px)이다.
- 지원 폭 1280·1440·1920에서 시안과 같은 배치. 1280 미만은 가로 스크롤.

## 6. 시안과 의도적으로 다른 점 (이것만 허용)

1. 쟁점 제목 = 원문 인용(§4.4). 시안의 요약 제목은 4186 전용 수작업이었다.
2. 사유·전제·확인 요청 연결 = §4.4 규칙. 4186에서 시안과 다른 곳: 전제 3은 30일 쟁점에만, 전제 5는 SLA 쟁점에만, 확인 요청 3은 SLA 쟁점에만 붙는다.
3. "원문 3쪽 ‘사업내용’에는 항목이 7개" 줄은 원문 텍스트를 해석하는 4186 전용 계산이라 넣지 않는다.
4. 제안서 분량은 엔진 값만 있고 단위가 없으므로 `엔진 추출 값 100 · 단위·조건은 원문 확인`으로 쓴다(시안의 "100쪽 이내"는 단위를 지어냈다).
5. 자격 데모 입력은 §4.5 방식(필드 이름 번역 없음, 행별 표식).
6. 시안 전용 장식(사이드바 모형, `개선 시안` 표식, "시안이라 저장하지 않았어요" 토스트, 사이드바 담당자 입력 모형)은 옮기지 않는다. 결정 띠는 기존 컴포넌트다.

## 7. 검증(작업자가 돌리고 결과를 보고)

- `cd web/frontend && npm run build` (TypeScript strict) — `BIDOPS_PORTFOLIO_ANALYSIS=1 npm run build -- --outDir dist-portfolio`도 통과.
- `npm run test:contrast`.
- 단위 검사: `lib/pdfQuoteLocator.ts`·`lib/engineRiskLinks.ts`에 대한 node 테스트(`node --test`로 도는 `.test.mjs`, 기존 `scripts/check-contrast.test.mjs` 방식)를 추가하고 §4.4의 4186 기대값과 §4.3 경계(4자 미만·두 쪽 걸침·미발견)를 검사한다. 4186 입력은 `docs/1124_prespec-analysis-redesign/mockup/data.js`에서 읽지 말고 테스트 fixture에 필요한 필드만 옮긴다(엔진 `why_not`·`preconditions`·execution 요청·`risks`).
- Playwright: `tests/prespec-analysis-view.spec.ts`를 새 화면에 맞게 다시 쓴다(mock 개발 서버 전용 약속 유지). fixture는 `tests/fixtures/engine-analysis.ts`를 넓히고, 쪽별 텍스트 endpoint와 company-wiki portfolio/pages 응답을 `mockEngineAnalysis`(또는 `mockApi`)에 추가한다. 검사: 탭 5개와 스크롤 추적, 첫 화면(1440×900)에 목적·금액 대조·과업·세 층·사유가 결정 띠 위에 보임, 쟁점 필터·펼침·사유 링크 이동, 요구사항 필터·검색·↑↓·`#req=`, 상세에 원문 발췌·회사 근거(실적 이름)·보완 방안, `[[` 미노출, PDF 서랍 열림·쪽 번호·iframe src·`<mark>`·Esc 초점 복귀, 원문·처리 정보 여덟 항목, 결정 띠 저장 흐름(기존 검사 유지), 1280/1440/1920 가로 넘침 없음. 실행:
  `BIDOPS_MOCK_API=1 npx vite --host 127.0.0.1 --port <빈 port> --strictPort` 를 띄운 뒤
  `BIDOPS_MOCK_UI=1 PW_PORT=<port> node_modules/.bin/playwright test prespec-analysis-view prespec-detail-layout --project=app --workers=2`
  (port 4173은 다른 앱이 쓴다. `lsof -iTCP:<port> -sTCP:LISTEN`로 빈 것을 고른다. 이 Mac은 운영과 같이 돌므로 Playwright는 한 번에 하나, `--workers=2`.)
- 백엔드 테스트는 작성만 하고 실행은 리더가 한다.
- 검사용으로 띄운 서버는 끝나면 끈다.

## 8. 보고

- 바뀐 파일 목록, 각 검사 명령과 종료 코드·요약 줄, 실패·skip 사유. §6 밖의 차이가 생겼으면 이유와 함께 따로 적는다.
- commit하지 않는다.
