# rhwp 문서 변환 파이프라인 명세

작업명: rhwp-document-pipeline · 기준일: 2026-09-11 · 상태: native 변환·MVP 보완 구현과 승인된 운영 배포·6건 core 재준비·Qwen 참조 실행 4건 사람 검토 대기
이 문서는 구현이 따라야 할 계약과 단계다. 배경은 [ADR.md](ADR.md), 요구는 [Requirements.md](Requirements.md), 구조는 [Design.md](Design.md)에 있다.

## 1. rhwp 호출 계약

바이너리: vendor `rhwp` v0.8.6 (upstream `edwardkim/rhwp` 커밋 `cac9b4f7c`, SHA-256 `c82684971756d58ba7391cd08c38c93bb4280ab9ebf0e21c0936574a0084fc8c`). 모든 호출은 worker의 요청별 임시 디렉터리 안에서, `cwd`=임시 디렉터리, 환경은 `_child_environment`(자격증명·프록시 없음), 네트워크 없음으로 실행한다. 입력 파일명은 `source.bin`이 아니라 확장자를 가진 `source.hwp`/`source.hwpx`로 둔다(rhwp가 확장자로 형식을 판별한다).

| 단계 | 명령 | 성공 조건 | 사용하는 JSON 필드 |
|---|---|---|---|
| ① HWPX 변환(HWP만) | `rhwp export-hwpx source.hwp converted.hwpx --verify --verify-pages --json` | exit 0, `format=="hwpx"`, `verify.identical==true`, `verifyPages.identical==true`, `passwordProtected==false`, 출력 파일이 ZIP magic | `bytes`, `verify.diffCount`, `verifyPages.before/after` |
| ③ PDF | `rhwp export-pdf source.<ext> -o output.pdf --backend svg --fallback-serif NanumMyeongjo --fallback-sans NanumGothic --fallback-mono NanumGothicCoding --json` | exit 0, `format=="pdf"`, `backend=="svg"`, `pageCount==renderedCount>=1`, 파일이 `%PDF-`로 시작, `bytes`==실제 크기, `pdfinfo` Pages==`pageCount` | `pageCount`, `renderedCount`, `bytes` |
| ④ 페이지 텍스트 | `rhwp export-text source.<ext> --json` | exit 0, `pageCount`==③의 `pageCount`, `omittedCount==0`, `truncated`가 없거나 false | `pages[].page`(0 기준), `pages[].text` |
| ⑤ 페이지 배치 | `rhwp dump-pages source.<ext> --json` | exit 0, `pageCount`==③, `pages[].pageIndex`가 0..N-1 연속 | `pages[].pageIndex`, `pages[].displayPage`, `pages[].section`, `pages[].columns[].items[].{kind,paraIndex,isEndnote}` |

- exit code: `export-hwpx`는 IR 차이 3, 페이지 수 불일치 4. 그 외 0이 아니면 `conversion_required`. 실행 시간 초과는 `timeout`, 네 native 호출(`export-hwpx`, `export-pdf`, `export-text`, `dump-pages`) 각각의 JSON stdout 1 MiB(1,048,576 B) 초과는 `output_size_limit`이다. 이 stdout cap은 호출별로 적용하며 무제한 stdout이나 파일 출력 우회로 대체하지 않는다.
- `untrustedContent`/`untrustedFields`가 가리키는 필드(`textPreview` 등)는 저장·로그하지 않는다. 정렬 검증에서만 메모리 안에서 비교한다.
- 옵션 고정값: `--compat` 기본(2022), `--profile` 미지정, `--text-as-paths` 미사용(텍스트 선택·검색이 필요), `--font-path` 미지정(이미지 fontconfig 사용).
- 페이지 번호 규약: rhwp는 0 기준(`page`, `pageIndex`). 저장·REST·화면은 1 기준 물리 순번이며 변환은 저장 직전에 한 번만 한다. `displayPage`는 부가 정보로 저장한다.
- 원본이 PDF인 첨부는 이 표를 적용하지 않고 기존 Poppler 경로를 쓴다.

## 2. 산출물과 저장

| # | 산출물 | 형식·schema | namespace | 결속 |
|---|---|---|---|---|
| ① | 원본 | 그대로 | `source` | 기존 |
| ② | 변환 HWPX(HWP만) | ZIP | `source` | `hwpx_sha256`, `hwpx_verify_jsonb` |
| ③ | 구조 JSON | `bidops.document-structure.v1` (불변) | `structure` | 기존 `document_structure` 행 |
| ④ | PDF | `application/pdf` | `source` | `pdf_sha256`, `pdf_page_count`, ClamAV exact-bytes clean |
| ⑤ | 페이지 텍스트 | `bidops.rhwp-page-text.v1` | `structure` | 페이지별 `text_sha256` |
| ⑥ | 대응표 | `bidops.para-page-map.v1` | `structure` | `para_page_map_sha256` |
| ⑦ | 절 후보(보조) | 현재 생산 `bidops.section-candidates.v2`, 과거 읽기 v1 | `structure` | sidecar descriptor의 size·SHA-256·object version |

`bidops.rhwp-page-text.v1`:

```json
{"schema":"bidops.rhwp-page-text.v1","page_count":79,
 "pages":[{"number":1,"display_page":null,"section":0,"text":"...","text_sha256":"..."}]}
```

`bidops.para-page-map.v1`:

```json
{"schema":"bidops.para-page-map.v1","page_count":79,"paragraph_count":1112,
 "paragraphs":[{"section":0,"para_index":66,"page_first":5,"page_last":5,"kind":"fullParagraph"}],
 "blocks":[
   {"block_key":"paragraph-1-71","section":0,"para_index":66,"page_first":5,"page_last":5,"match":"exact"},
   {"block_key":"table-1-3-r0-c0","section":0,"para_index":null,"page_first":5,"page_last":5,"match":"page_text"}],
 "unmapped_block_keys":["table-1-4-r0-c1"],
 "mapping":{"blocks_total":2321,"blocks_mapped":1420,"blocks_unmapped":901,"rule":"para-page-align.v1"}}
```

`para_index`가 있는 모든 항목에는 항상 같은 공간의 `section`을 함께 기록한다. `match="page_text"`인 블록은 원본 블록의 section을 알고 있어도 `para_index`를 `null`로 둘 수 있다. 이는 source paragraph identity를 발명하지 않고 페이지 텍스트에만 연결한다는 뜻이며, source identity가 없는 블록의 `section`은 `null`로 둘 수 있다.

현재 `bidops.section-candidates.v2`의 닫힌 shape는 다음과 같다.

```json
{"schema":"bidops.section-candidates.v2","page_count":79,"mode":"outline",
 "section_count":2,"returned_count":1,"truncated":true,"candidates_truncated":true,
 "sections":[{"index":0,"title":"I. 사업 개요","page":3,"char_count":1200,"truncated":false}]}
```

- `mode`는 `outline|clause|page`, `page`는 같은 snapshot PDF의 1 기준 물리 쪽이다.
- `section_count`는 upstream 전체 후보 수, `returned_count`는 실제 `sections` 길이다.
  `candidates_truncated == (returned_count < section_count)`이며 이때 `truncated=true`여야 한다.
  `truncated`는 발췌 절단도 포함하는 upstream 표식이므로 `candidates_truncated=false`여도 true일 수 있다.
- title은 공백 정규화 뒤 최대 300자만 저장하고 개별 `truncated`로 제목 절단을 표시한다.
  `excerpt`, `nextStep`, `source`와 원문 유래의 다른 필드는 저장하지 않는다.
- reader는 v1의 닫힌 shape(`mode=clause|page`, `section_count==len(sections)`)도 계속 읽는다.
  v1을 v2 bytes로 다시 쓰거나 누락된 전체 개수를 추정하지 않는다.

snapshot 행(`prespec_v4_pdf_snapshot`)에는 `pdf_metadata_jsonb.renderer='rhwp-svg-pdf'`(별도 renderer 열 없음), `renderer_jsonb={"renderer":"rhwp-svg-pdf","rhwp_version":"0.8.6","rhwp_binary_sha256":...,"backend":"svg","compat":"2022","fallback_fonts":{...},"worker_image_digest":null|...}`, `font_jsonb`(기존 manifest hash), `config_jsonb.options`(정규화 ProcessorOptions), 새 열(Design §2.4)을 채운다. `renderer_digest = sha256(canonical_json(renderer_jsonb))`, `font_digest`, `config_sha256` 세 값이 같고 같은 원본 version이면 재변환 없이 재사용한다(기존 캐시 검증 규칙 그대로).

scratch v2의 native 성공 결과는 `native_sidecars`를 추가한다. 키는 `hwpx`,
`page_text`, `para_page_map`, `section_candidates`, `hwpx_verify`이며 파일 항목은
`{file,byte_count,sha256}` descriptor다. 파일은 각각 `native/<request UUID>.hwpx`,
`native/<request UUID>.page-text.json`, `native/<request UUID>.para-page-map.json`,
`native/<request UUID>.section-candidates.json`이다.
검증된 core 생성 뒤 digest가 bounded 실행·해석에 실패하면 `warnings`에
`section_candidates_unavailable`을 넣고 `native_sidecars.section_candidates=null`로
발행한다. 이 경고가 없는 null descriptor는 `section_candidates_invalid`이며,
descriptor가 있으면 canonical bytes·size·SHA-256 검증을 모두 통과해야 한다.
실제 후보 파일의 JSON `null`은 유효 후보가 아니므로 거부한다. 신규 snapshot의 nullable
후보 content object·location·SHA-256 참조도 같은 warning 경계에서만 전부 null이다.
0024 이전 snapshot의 기존 null 참조는 경고를 소급 추가하지 않고 그대로 읽고 재사용한다.
원본 HWPX는 `hwpx=null`, `hwpx_verify=null`이며 원문 bytes를 그대로 쓴다. HWP는
검증된 변환본과 안전한 `{identical,diff_count,pages:{before,after,identical}}`만 전달한다.
모든 파일이 원자적으로 쓰인 뒤 결과 JSON을 마지막에 발행하며, 실패·소비 완료 시
해당 요청의 파일만 정리한다. raw dump-pages·textPreview는 전달·저장하지 않는다.

저장 시와 cache hit 모두 source·PDF·page-text·변환 HWPX·구조·대응표의 고정된
객체 version·etag·size·SHA-256을 읽어 확인한다. native page text를 구조 블록에서
재조합하지 않는다. HWP 변환본은 원문·PDF와 함께 exact-byte scan을 거치고 최신
clean scan이 없으면 재사용을 거부한다. 기존 구조 충돌은 Design §2.4를 따른다.

## 3. ProcessorOptions

기존 필드를 유지하고 다음을 확정한다.

| 필드 | 값 | 비고 |
|---|---|---|
| `prepare_pdf` | true (v4 준비), false (구조만) | false여도 HWP는 ①·②를 수행. ③~⑥은 true일 때만 |
| `timeout_seconds` | 300 | 네 호출이 공유 |
| `max_output_bytes` | 64 MiB | PDF·HWPX·JSON 각각 상한. rhwp PDF는 Canvas보다 작다(142: 4.7 MB) |
| `max_pdf_objects`, `max_pdf_pages`(512) | 유지 | stdlib PDF limit 검사는 rhwp PDF에도 그대로 적용 |

`max_output_bytes`의 per-artifact 값과 적용 범위는 유지한다. 위 네 native 호출의 JSON
stdout 1 MiB cap은 이 artifact cap과 별도의 호출 경계다.

## 4. 문단↔페이지 정렬 규칙 (`para-page-align.v1`)

R0 실측과 upstream `dump_page_items_json` 구현으로 다음 의미를 확정했다.

- 식별자는 전역 정수가 아니라 `(section, paraIndex)`다. `paraIndex`는 해당 구역의 0 기준
  최상위 본문 paragraph 배열 인덱스다.
- `fullParagraph`·`partialParagraph`는 그 본문 문단을 가리키고, `table`·`partialTable`·
  `shape`는 해당 control을 소유한 **최상위 본문 문단**의 같은 인덱스를 쓴다. 표 셀 안의
  문단은 별도 `paraIndex`를 받지 않는다.
- `columns[].items`만으로는 본문 인덱스가 완전하지 않다. `extras[]`의
  `hiddenEmptyPara`·`wrapAroundPara`도 같은 `(section, paraIndex)` 공간에 속한다.
  notice 142 HWPX는 items 1,107개 인덱스와 extras 5개를 합쳐 구조의 최상위 문단
  1,112개를 정확히 덮었다. 셀 문단 1,775개는 이 인덱스 공간에 없었다.

확정 규칙은 다음과 같다.

1. `isEndnote==false`인 `columns[].items`와 `extras[]`를 함께 읽고
   `(section, paraIndex)`별 `page_first=min(pageIndex)+1`,
   `page_last=max(pageIndex)+1`을 만든다. 한 문단이 여러 item 또는 페이지에 나타나도
   같은 키로 합친다.
2. 원본 HWPX의 `paragraph` 블록과 그 문단이 소유한 top-level control 블록은 **extractor
   identity가 증명된 경우에만** source XML의 구역별 top-level `p` ordinal을
   `(section, paraIndex)`로 정확히 연결한다. extractor의 identity를 증명하지 않은
   rendered block list ordinal은 crosswalk로 사용하지 않는다.
   `textPreview`는 이 identity를 만들거나 보정하는 데 쓰지 않는다.
3. HWP에서 변환한 HWPX는 ordinal crosswalk를 가정하지 않는다. 비어 있지 않은
   `paragraph`와 `table_cell`의 **FULL text**가 `export-text`의 정확히 한 페이지에서
   정확히 한 번만 exact occurrence로 나타날 때만 `match="page_text"`로 연결하고
   `para_index`는 `null`로 둔다. 빈 값·반복·여러 페이지·불일치는 `unmapped`다.
4. `table_cell`은 source paragraph identity가 증명되지 않는 한 `paraIndex`로 연결하지
   않는다. 원본 HWPX의 cell도 비어 있지 않은 FULL text가 `export-text`의 정확히 한
   페이지에서 정확히 한 번 나타날 때만 `match="page_text"`로 연결하고 `para_index`는
   `null`로 둔다. 빈 블록은 종류와 무관하게 항상 `unmapped`다. 확인되지 않은 쌍은 앞
   문단 페이지를 물려받지 않는다.
5. prefix·LCS·whitespace correction·fuzzy matching·인접 페이지 상속·여러 페이지 추정은
   사용하지 않는다. 확인된 exact match가 아니면 `unmapped`이며, `unknown`을 추정으로
   채우지 않는 기존 게이트를 따른다.
6. 결과는 canonical JSON으로 직렬화하며 같은 입력에서 두 번 만든 바이트가 같아야 한다.
   매핑률은 F5에 따라 정보성으로만 기록하고 문서 실패 임계로 사용하지 않는다.

R2 구현의 identity 증명은 `extract_hwpx`가 구조 블록을 만드는 같은 XML 순회에서 수행한다.
`Contents/content.hpf`의 manifest·spine 순서를 pinned rhwp와 대조해 구역을 정하고,
구역 root의 직접 자식 `p` ordinal만 본문 identity로 기록한다. 중첩 문단은 본문 순번을
받지 않으며, top-level 표 control은 가장 가까운 소유 문단이 그 직접 자식일 때만 같은
identity를 받는다. 패키지 구역 순서를 확인할 수 없으면 identity를 만들지 않는다.
구역별 source ordinal 집합이 연속적이고 dump의 items+extras 집합과 정확히 같아야
그 구역의 ordinal 대응을 사용한다. 개수·인덱스 불일치는 해당 구역의 exact 대응을 닫되
문서를 실패시키지 않는다. 기존 구조의 page·block_key·text·순서는 바꾸지 않는다.

`paragraph_count`는 endnote를 제외한 dump의 고유 `(section, paraIndex)` 수다.
같은 identity에 여러 kind가 있으면 사전순 첫 값을 대표 `kind`로 기록하며 페이지 범위는
모든 item을 합친다. `paragraphs`는 `(section, para_index)`, `blocks`와
`unmapped_block_keys`는 block_key 사전순이다. 각 구조 블록은 mapped·unmapped 중 정확히
한 곳에만 존재하며, 집계 분모에는 빈 블록·빈 table control도 포함한다. validator는
닫힌 필드 집합·정수 타입·페이지 범위·identity·중복·집계·블록 누락을 검사한다.
R2는 대응표와 canonical UTF-8 JSON을 `ProcessedDocument.para_page_map`·
`para_page_map_bytes`로 생성한다. versioned object·snapshot·sidecar 결속은 R3에서 구현한다.

HWP 입력의 ordinal crosswalk에는 확인된 보수적 경계가 있다. 원본 HWP의 `dump-pages`와 변환 HWPX 구조가
같은 문단 인덱스 공간이라는 기존 가정은 실측에서 깨졌다. 제안요청서는 원본 dump의
items+extras가 `(section, paraIndex)` 669개(최대 668)인데 변환 HWPX의 최상위 문단은
709개였고, 과업지시서는 각각 347개(최대 346)와 351개였다. `--verify`의 IR diff 0과
`--verify-pages`의 같은 페이지 수는 이 crosswalk를 증명하지 않는다. 따라서 HWP에서
변환한 HWPX의 ordinal crosswalk 부재는 추가 실험을 요구하는 미결 조건이 아니라
명시적인 보수적 지원 동작이다. R2 정렬기는 위의 exact FULL text 단일 페이지 규칙만
적용하고 나머지를 `unmapped`로 둔다.

## 5. 오류 코드

기존 코드를 유지하고 다음을 추가한다. 모두 `^[a-z][a-z0-9_]{0,63}$`.

| 코드 | 조건 |
|---|---|
| `hwpx_verify_failed` | `export-hwpx` exit 3/4 또는 `verify.identical`·`verifyPages.identical`이 false |
| `encrypted_document` | `passwordProtected==true` 또는 rhwp가 암호 문서 오류 |
| `rhwp_manifest_invalid` | stdout JSON 파싱 실패·`schemaVersion` 불일치·필수 필드 누락 |
| `pdf_page_mismatch` | ③·④·⑤·`pdfinfo` 페이지 수 불일치 |
| `para_page_map_invalid` | 대응표 생성 예외(정렬 실패 블록은 여기 해당하지 않음) |
| `section_candidates_invalid` | `digest --sections` 봉투·`sectionsMode`·절 형식·쪽 범위 위반, 절 2,000개 초과, 저장 bytes 비정규 (빈 목록은 유효) |

core 실패의 attempt `error_code`는 `pdf_preparation_failed:<위 코드 또는 기존 processor 코드>`로 기록한다(N6). 감사 `safe_metadata.converter_code`에 같은 값을 둔다.

2026-09-11 MVP 보완([안정화 Spec](../0910_prespec-workflow-hardening/Spec.md)): native core
검증 뒤 보조 digest를 처리한다. `sectionsMode=outline|clause|page`, `sectionCount`는 전체,
`sections`는 최대 50개의 반환 후보이며 둘의 동등성을 요구하지 않는다. 새
`bidops.section-candidates.v2`는 `returned_count,truncated,candidates_truncated`를 추가해
부분 반환과 발췌 절단을 구분하고 기존 v1 bytes/reader를 보존한다. 후보 목록 부분 반환은
`section_candidates_incomplete`, digest의 bounded 실패/해석 실패는
`section_candidates_unavailable` warning이다. 실패한 후보는 쓰지 않지만 독립적으로
확인한 PDF·전체 페이지 텍스트는 사용할 수 있다. core 실패를 이 경고로 낮추지 않는다.
부분 후보는 참고 표이며 자동 범위/index 확정/모델 범위 보조 대신 사람이 직접 쪽을 고른다.
같은 줄에 복수 장 제목이 있으면 열 순서를 추정하지 않는다. 자동 선택된 장의 정규화 제목이
정확히 `제안개요`인 경우도 발주 사업 범위가 아닌 작성 양식일 수 있으므로 둘 다
`ambiguous_scope_boundary`로 보낸다.

선택 manifest는 선택한 각 쪽의 원문 `text`, 그 `text_sha256`, 원래 전체 쪽의
`source_page_text_sha256`을 유지한다. 일부 공백 쪽도 그대로 포함한다. 선택 쪽 전체가 공백이면
runner가 `manifest_invalid`로 닫아 모델을 호출하지 않는다. 초안 응답 후 claim 결정적
검증은 비어 있지 않은 quote가 같은 고정 쪽에서 유일하게 대응해야 통과하므로
공백 쪽은 근거가 될 수 없다.

## 6. REST·화면 변경

아래는 원래 rhwp 교체 범위다. 이후 MVP의 target-only PDF 조회·범위 조회 v2·수동 쪽 선택은
[현재 계약](../contracts.md)의 "v4 개요 입력 범위의 사람 확인"과 안정화 Spec을 따른다.

- `GET /api/pre-specs/{id}/overview-pages`: 필드 불변. `renderer` 문자열만 `rhwp-svg-pdf`로 바뀐다.
- `GET /api/pre-specs/{id}/overview-pages/v2`: `range_review`는
  `schema_version=bidops.prespec-overview-range-view.v2`, `candidate_status=complete|partial|unavailable`,
  nullable `candidate_count_total`, `candidate_count_returned`, `warning_codes`, `selected_pages`,
  `can_confirm`을 반환한다. 자동 ready와 사람 확인 target을 모두 표시한다. v1에서 `outline`
  또는 부분 후보를 정직하게 표현할 수 없으면 409 `overview_contract_upgrade_required`다.
- 근거 PDF endpoint: 불변(snapshot의 PDF object 서빙).
- `GET /api/pre-specs/{id}/overview-pages/targets/{target_id}/pdf`: attempt/result 없이도 exact
  target PDF를 반환한다. 안전한 과거 document의 target도 열람할 수 있고 current document
  조건은 범위 확정에만 적용한다. 공고/target/document/snapshot 계보, 원본·PDF 최신 clean
  scan, 고정 object version·etag·size·hash 중 하나라도 어긋나면 안전하게 실패한다.
- `POST /api/pre-specs/{id}/overview-pages/range-confirmations`: 후보 index 쌍 또는 직접 page 쌍
  중 정확히 하나를 받는다. 부분 후보 index는 422 `candidate_range_incomplete`, 후보 읽기 실패
  index는 422 `candidate_range_unavailable`이고 직접 page 쌍은 후보와 무관하다. queued/running은
  409 `target_execution_active`; 성공은 새 `human_confirmed` ready target과 감사만 만들며
  `attempt_enqueued=false`다.
- `GET /api/document-structures/{id}/segments` (`bidops.document-segments.v1`): `segments[].page_range: {"first":n,"last":m} | null`, `mapping_status: "mapped"|"partial"|"unavailable"`를 추가한다. 응답에 원문 텍스트는 여전히 없다.
- 심층 검토 보고서·segment 화면: `page_range`가 있으면 PDF 페이지 링크, 없으면 "페이지 미확인" 문구.
- 페이지 개요 화면 문구 "표지를 포함한 변환 PDF 순번 기준"은 유지한다.

새 target 뒤 이전 target의 attempt는 저장 행과 결과를 바꾸지 않는다. current projection은 이전
queued/running/completed를 `stale`, `reason_code=target_superseded`, `result_id=null`로 표시하고
이전 verification을 현재 diagnostic에 붙이지 않는다. 이전 target enqueue도
`target_superseded`로 거부하며 회사 핏은 이전 완료 결과를 새 범위 입력으로 사용하지 않는다.

### 6.1 policy v5 두 단계 호출 경계

- 정상은 claims 초안 1회 + semantic 검토 1회다. 초안의 허용된 형식 오류에만 seed를 바꾼
  재생성 1회를 허용해 attempt당 최대 3회, semantic은 최대 1회다. 결정적 내용 검증 실패에는
  semantic 호출이나 자동 보정을 하지 않는다.
- 각 stage는 authorization/dispatch 전에 실제 structured request 전체를 canonical UTF-8 JSON으로
  직렬화한다. byte 수를 보수적 입력 token 상계로 쓰고 chat template 1,024와 출력 16,384를
  더해 `min(served max_model_len, policy 262,144)` 이하인지 확인한다. 확인된 context가 없거나
  양수가 아니거나 stage별 prompt/page text 24,000자 등 기존 payload 상한을 넘으면 전송하지 않는다.
- 이 기술적 미실행은 `failed/input_capacity_exceeded`다. `needs_human_review` 내용 검증 실패,
  `completed`, 품질 승인과 다르다. semantic 단계에서 막히면 앞선 초안 call event와 암호화
  원응답은 이력으로 남지만 semantic dispatch/HTTP는 0이다. 자동 절단·요약·분할·hosted fallback은 없다.

2026-09-11 실제 참조 실행에서는 744·749·759·761의 draft dispatch/response event가
각 1쌍씩, 총 8건이고 model response object 4건, attempt 4건, verification 4건을
append했으며 result row는 0건이다. 기존 10개 테이블의 기존 행 MD5는 전후 같고,
재수집·재변환은 0건으로 C-1/C-2 입력을 그대로 재사용했다. 기록상 744·749·761은
`main_tasks` 섹션 누락, 네 건 공통으로 수치·단위 metadata 확인 실패가 있고,
759에는 `analysis_premise_unverified`·미확인 사유 검증 문제도 있다. 이는 코드의
실제 오류 원인을 단정하는 규격이 아니라 저장된 검증 실패 관측이다.

## 7. 역사적 구현 단계와 당시 게이트

아래 R0~R7은 2026-09-10 당시 구현·인수 이력이다. 현재 계약이나 앞으로 반복할 phase가
아니며, 특히 R7의 v1 후보·실표본 미재현 기록은 위 §5~6의 2026-09-11 계약을 대신하지 않는다.

| 단계 | 내용 | 게이트 |
|---|---|---|
| R0 기준선 | vendor에 바이너리·SHA256SUMS·PROVENANCE 등록, Dockerfile에 `fonts-nanum`, worker 이미지 빌드, 격리 컨테이너에서 표본 3건 rhwp 4호출 실측(시간·RSS·pids·페이지 수·바이트 결정성·`paraIndex` 의미) | 실측표를 이 문서 §8에 기록. 호출별 JSON stdout 1 MiB cap과 실제 최대 747,110 B를 기록하고, `(section, paraIndex)`·보수적 HWP 매핑 규칙을 확정. 매핑률은 정보성 지표 |
| R1 변환기 | `DocumentProcessor`에 rhwp 경로 구현(①~⑤), JSON 파서, 오류 코드, 기존 Canvas 경로는 남김 | `test_document_mcp.py` rhwp 계약 테스트, 표본 3건 격리 통과 |
| R2 대응표 | 정렬기 `para-page-align.v1`, `bidops.para-page-map.v1` 저장 | 결정성 테스트, 표본 매핑률 기록 |
| R3 저장·snapshot | migration(nullable 열), `prepare_v4_pdf_snapshot` rhwp 결속, 캐시 재사용, 감사 코드(N6) | 임시 PostgreSQL 17 migration·trigger·권한 검사, 격리 roundtrip |
| R4 소비자 | page-overview·회사 핏 renderer 교체, segments `page_range`, 화면 링크 | focused backend·Playwright(영향 spec만), 1280×800·1440×900 |
| R5 제거 | Chromium·Node·WASM·Canvas 코드와 Dockerfile·compose 완화 제거, `pids_limit` 재조정 | runtime contract, 이미지 크기·의존성 확인 |
| R6 운영 인수 | 백업 → migration → worker 재생성 → 표본 3건 새 snapshot 준비 → API·UI 확인 → 문서 갱신 | status·findings·validation-run 기록. 기존 행 미변경 확인 |
| R7 범위 선택 보조 | 당시 `bidops.section-candidates.v1`, 선택기 미결정 target, CLI 보조 제안, 사람 확정 REST·화면 | 2026-09-10 당시 완료. 자동 실행은 열지 않았고 실표본 사람 확정은 재현하지 못했음 |

위 당시 검증은 변경 파일이 닿는 테스트만 돌리고 R5 뒤 최종 트리의 전체
스위트를 1회 돌린 역사 기록이다. 현재 작업에 전체 스위트 재실행을 지시하지 않는다.

## 8. 실측 기록

| 일자 | 표본 | 명령 | 결과 |
|---|---|---|---|
| 2026-09-10 | 142.hwpx | `export-pdf` svg | 12.80초, RSS 128 MB, 79쪽, 4,754,740 B, `pdftotext` 71,389자, 폰트 NotoSansKR·NanumMyeongjo·Unifont 임베드 |
| 2026-09-10 | rfp.hwp | `export-pdf` svg | 10.47초, RSS 70 MB, 53쪽, 2,943,696 B, 62,146자 |
| 2026-09-10 | sow.hwp | `export-pdf` svg | 4.41초, RSS 57 MB, 31쪽, 1,731,063 B, 36,752자 |
| 2026-09-10 | rfp.hwp | `export-hwpx --verify --verify-pages` | 0.23초, diffCount 0, 53=53, 139,694 B → stdlib 추출 2,493블록 |
| 2026-09-10 | sow.hwp | `export-hwpx --verify --verify-pages` | 0.11초, diffCount 0, 31=31, 81,250 B → 1,353블록 |
| 2026-09-10 | 142.hwpx | `dump-pages --json` | 79쪽, items에 `paraIndex`·`kind`·`textPreview`(untrusted) |
| 2026-09-10 | 142.hwpx | `digest --sections --json` | 43절, `paraCount` 1112, 절별 `title`·`page`·`charCount` |
| 2026-09-10 | 142.hwpx | `export-pdf --backend direct` | 실패: native-skia feature 미포함 빌드 |
| 2026-09-10 | 142.hwpx, 격리 이미지 2회 | R0 3호출 | 합계 22.384/22.443초, PDF 79쪽·4,829,134 B, 최대 rhwp RSS 162,840 KiB, 컨테이너 pids 4, `dump-pages` stdout 최대 747,110 B, 세 산출물 hash 동일 |
| 2026-09-10 | 제안요청서 HWP, 격리 이미지 2회 | R0 4호출 | 합계 18.531/17.905초, HWPX verify diff 0·53=53, PDF 53쪽·2,874,883 B, 최대 rhwp RSS 160,536 KiB, pids 4, `dump-pages` stdout 432,607 B, 네 산출물 hash 동일 |
| 2026-09-10 | 과업지시서 HWP, 격리 이미지 2회 | R0 4호출 | 합계 10.281/10.418초, HWPX verify diff 0·31=31, PDF 31쪽·1,616,896 B, 최대 rhwp RSS 128,240 KiB, pids 4, `dump-pages` stdout 221,095 B, 네 산출물 hash 동일 |

R0 이미지는 `network none`, non-root 1000:1000, 1 GiB, pids 128, `cap_drop ALL`,
`no-new-privileges` 조건이었다. PDF·HWPX·`export-text`·`dump-pages`는 같은 입력의 두 실행에서
각각 byte hash가 같았다. 이 결정은 네 native 호출별 JSON stdout cap을 1 MiB(1,048,576 B)로
고정하며, 관측된 R0 최대는 747,110 B다. per-artifact `max_output_bytes` 상한과 문서당
공유 deadline은 별도로 유지하고, stdout 무제한 또는 파일 출력 우회는 허용하지 않는다.
HWP 매핑은 source XML extractor identity가 증명된 원본 HWPX의 ordinal만 허용하고, HWP→HWPX는
exact FULL text가 정확히 한 export-text 페이지에 한 번 나타나는 경우만 `page_text`로
연결한다. 매핑률은 F5에 따라 정보성으로만 남긴다. PDF 바이트 결정성은 같은 검증 이미지에서
실행한 세 표본의 동일 hash라는 증거에 한정하며 보편적 보증이 아니다. 전체 안전 지표는
[R0 metrics](../validation-runs/2026-09-10-rhwp-r0-baseline.metrics.json)에 있다.

## 9. 변경 이력

- 2026-09-10 최초 작성. 사용자 결정: vendor 바이너리 배포, Chromium 전면 대체, 산출물 전부 저장, LLM 역할 3종(개요 해석·범위 선택 보조·역할별 분석).
- 2026-09-10 R0 계약 종결. 최초 실측에서 닫혔던 게이트는 validation run에 역사 기록으로 보존하고, 이미 측정한 증거로 1 MiB 호출별 stdout cap·보수적 매핑 규칙·정보성 매핑률을 확정했다. 다음 R1은 coordinator acceptance 뒤에 연다.
