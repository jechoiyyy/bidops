# rhwp 문서 변환 파이프라인 설계

작업명: rhwp-document-pipeline · 기준일: 2026-09-11 · 상태: native 변환·MVP 보완 구현과 승인된 운영 배포·6건 core 재준비·Qwen 참조 실행 4건 사람 검토 대기
요구는 [Requirements.md](Requirements.md), 결정은 [ADR.md](ADR.md), 세부 계약과 단계는 [Spec.md](Spec.md)에 있다.

## 1. 현재 구조와 바뀌는 지점

```text
[도입 전]
attachment fetch ─ quarantine ─ ClamAV ─ DocumentProcessor(prepare_pdf=False)
                                            ├─ HWP ─ node rhwp_convert.mjs(WASM exportHwpx) ─┐
                                            └─ HWPX ────────────────────────────────────────┴─ extract_hwpx ─ 구조 JSON(page=구역)
v4 prepare ──────────────────── DocumentProcessor(prepare_pdf=True)
                                            ├─ node rhwp_render_canvas.mjs(geometry)
                                            ├─ Canvas print HTML + Chromium --print-to-pdf
                                            ├─ pdfinfo receipt, stdlib PDF limit, pdftotext
                                            └─ PDF + 페이지 텍스트 (구조와 미연결)

[현재]
attachment fetch ─ quarantine ─ ClamAV ─ DocumentProcessor(rhwp)
                                            ├─ HWP:  rhwp export-hwpx --verify --verify-pages --json ─ HWPX(검증)
                                            ├─ HWPX: extract_hwpx ─ 구조 JSON (계약 불변)
                                            ├─ rhwp export-pdf --json ─ PDF
                                            ├─ rhwp export-text --json ─ 페이지 텍스트
                                            ├─ rhwp dump-pages --json ─ 문단↔페이지
                                            ├─ core 검증·결속(PDF/page text/map/renderer/source)
                                            └─ digest --sections --json ─ 보조 후보 v2 또는 경고
```

바뀌는 것은 worker 안의 변환 엔진과 산출물 묶음이다. 안전 경계(quarantine, MIME·magic, ZIP 경계, ClamAV, scratch 프로토콜, versioned object, 불변 snapshot, 단일 analysis 슬롯, v4 target/attempt/current)는 그대로 쓴다.

## 2. 구성 요소

### 2.1 rhwp 바이너리(vendor)

- 위치 `web/backend/app/deep_review/document_mcp/vendor/rhwp/bin/rhwp`, `SHA256SUMS`에 등재, `PROVENANCE.md`에 upstream·태그·커밋·빌드 환경 기록(ADR-RDP-002).
- 런타임 이미지에서 `/app/web/backend/.../bin/rhwp`로 COPY되며 실행 권한만 가진다. 기존 Node·Chromium·WASM 자산과 `rhwp_convert.mjs`·`rhwp_render_canvas.mjs`는 삭제한다.
- 폰트: `fonts-noto-cjk` 유지, `fonts-nanum` 추가. `export-pdf`에 fallback 세 옵션 고정(ADR-RDP-006).

### 2.2 DocumentProcessor 변경

`process(bytes, media_type, options)`의 결과 계약을 한 종류로 합친다. `prepare_pdf` 플래그는 남기되 의미를 "PDF·페이지 텍스트·대응표까지 만든다"로 한정한다.

| 입력 | 단계 | 산출 |
|---|---|---|
| HWP | ① `export-hwpx --verify --verify-pages --json` → ② `extract_hwpx` → ③ `export-pdf` → ④ `export-text` → ⑤ `dump-pages` → ⑥ 정렬 | HWPX, 구조, PDF, 페이지 텍스트, 대응표 |
| HWPX | ② → ③ → ④ → ⑤ → ⑥ | 구조, PDF, 페이지 텍스트, 대응표 |
| PDF | 기존 Poppler 경로(재렌더 없음) | 구조(페이지 블록), 페이지 텍스트(=구조), 대응표는 항등 |
| 이미지 | 기존 경로 | 변경 없음 |

③~⑤는 같은 입력 파일(HWP는 원본 HWP, HWPX는 원본 HWPX)에 대해 실행한다. HWP를 변환 HWPX로 다시 렌더하지 않는다. 이유는 페이지네이션이 원본과 같아야 하고 rhwp가 HWP를 직접 읽기 때문이다. ⑥은 identity가 증명된 원본 HWPX에만 source XML top-level ordinal을 `(section, paraIndex)`로 연결한다. HWP를 변환한 HWPX에는 ordinal crosswalk를 가정하지 않고, 비어 있지 않은 paragraph·table-cell FULL text가 `export-text`의 정확히 한 페이지에 정확히 한 번 나타날 때만 `page_text`로 연결하며 `para_index`는 null로 둔다.

각 rhwp 호출은 기존 `_run_limited_subprocess`로 실행한다. 네 native 호출의 JSON stdout에는 호출별 1 MiB(1,048,576 B) cap을 적용하고 초과는 `output_size_limit`으로 실패한다. 문서당 shared deadline 하나와 `max_output_bytes` per-artifact cap은 별도로 유지하며, stdout을 무제한으로 열거나 파일 출력으로 우회하지 않는다. `preexec_fn=_resource_limiter(max_output_bytes)`를 사용하고, rhwp는 단일 프로세스라 Chromium 예외(AS/DATA 해제, FSIZE 4배)가 필요 없다.

### 2.3 페이지 텍스트와 대응표

- 페이지 텍스트 정본은 `export-text --json`이다. Poppler `pdftotext`는 원본 PDF 첨부에만 쓴다. 검증으로 `pdfinfo` 페이지 수와 `export-pdf`의 `pageCount`, `export-text`의 `pageCount`, `dump-pages`의 `pageCount`가 모두 같아야 한다.
- 대응표 identity는 항상 `(section, paraIndex)`이며 `dump-pages`의 `pages[].columns[].items[]`와 `extras[]`에서 `kind`, `paraIndex`, `section`, `pageIndex`를 읽어 `(section, paraIndex) → {page_first, page_last}`를 만든다(문단이 페이지를 넘으면 범위). 원본 HWPX는 extractor identity가 증명된 경우에만 source XML top-level ordinal을 이 identity에 연결하고, rendered block list ordinal을 맹목적으로 쓰지 않는다. HWP 변환 HWPX의 비어 있지 않은 paragraph·table-cell과 원본 HWPX의 table-cell은 FULL text의 exact occurrence가 정확히 한 export-text 페이지에 한 번일 때만 `match="page_text"`로 연결하며, 이 경우 `para_index`는 null이다. 빈 블록·그 밖의 미확인 블록은 `unmapped`다. prefix·LCS·whitespace correction·fuzzy matching·인접 페이지 상속·다중 페이지 추정은 사용하지 않는다. `textPreview`는 정렬 identity를 만들거나 보정하는 데 쓰지 않고 저장하지 않는다.
- 대응표는 `bidops.para-page-map.v1` JSON으로 `structure` namespace에 저장하고 snapshot 행이 object id·hash로 가리킨다.

### 2.4 데이터 모델

기존 `prespec_v4_pdf_snapshot`(0021)은 유지하고 새 snapshot 계약을 추가한다. renderer 값은 별도 DB 열이 아니라 `pdf_metadata_jsonb.renderer`와 `renderer_jsonb`에 있다. Canvas 이력은 그대로 두고 native 신규 행은 `rhwp-svg-pdf`를 기록한다. 열 추가는 nullable로만 한다.

| 열(신규) | 뜻 |
|---|---|
| `hwpx_content_object_id`, `hwpx_location_id` | 변환 HWPX 객체(원본이 HWP일 때만) |
| `hwpx_verify_jsonb` | `export-hwpx --json`의 `verify`·`verifyPages` 결과 |
| `structure_id`, `structure_location_id` | 같은 원본의 `document_structure` 행과 payload의 정확한 객체 버전 |
| `para_page_map_content_object_id`, `para_page_map_location_id`, `para_page_map_sha256` | 대응표 객체·정확한 버전·SHA-256 |
| `rhwp_binary_sha256`, `rhwp_version` | renderer provenance(기존 `renderer_jsonb`에도 기록) |

`renderer_digest = sha256(canonical_json(renderer_jsonb))`다. 기존 identity의
`font_digest`·`config_sha256`도 함께 비교하므로 바이너리·폰트·옵션 변경은 다른 캐시다.
HWPX 해시는 참조된 `content_object.sha256`에 있으며 중복 hash 열을 만들지 않는다.

`document_structure.document_version_id`의 UNIQUE는 유지한다. 기존 구조가 있으면
원본 해시·MIME·pages·blocks가 native 결과와 정확히 같은 경우에만 재사용하고,
차이는 `structure_binding_mismatch`로 거부한다. ID·생성 시각·extractor 표식 차이만
비교에서 제외한다. 구조를 새로 만들 때는 기존 materialization과 같은 block·segment
저장 함수를 쓴다. 이전 리뷰나 구조를 수정하지 않는다.

`0023_rhwp_snapshot`은 위 열과 `prespec_v4_attempt.validation_warnings`(nullable
JSONB)를 추가한다. 경고 열은 이후 WP-3 결과의 저장 자리이며 현재 모델 검증기를
변경하지 않는다. attempt의 허용 상태 전이에서만 경고를 쓸 수 있고 terminal 행은
여전히 불변이다. native 자료나 경고가 하나라도 있으면 downgrade를 거부한다.

### 2.5 소비자 연결

- v4 페이지 개요·회사 핏·page-overview API·근거 PDF endpoint: snapshot의 PDF·페이지 텍스트를 지금과 같은 필드로 읽는다. 변경은 renderer 이름과 page-text 출처뿐이다.
- 심층 검토·`document_segments`: 구조 JSON을 지금처럼 쓰고, `GET /api/document-structures/{id}/segments` 응답에 `page_range`(대응표 유래, 없으면 `null`)를 추가한다. 화면은 페이지가 있으면 PDF 링크를 붙인다.
- 범위 선택: heading selector와 후보는 자동 제안일 뿐이다. 조회 v2는 자동 ready target도 포함하고 후보 상태(`complete|partial|unavailable`), 전체/반환 개수, 경고, 현재 선택 쪽, 확정 가능 여부를 함께 반환한다. 담당자는 후보와 무관하게 PDF의 `first_page`~`last_page`를 직접 지정할 수 있다. 부분·읽기 불가 후보의 index 선택과 LLM 보조는 차단한다.
- 안전한 열람: 완료 review용 PDF와 별도로 attempt PDF, target PDF endpoint가 있다. target endpoint는 attempt가 없거나 안전한 과거 document에 결속돼도 동작하며 exact object와 최신 clean scan을 다시 검사한다. current document 조건은 범위 확정에만 적용한다.
- 현재성: 확정은 같은 snapshot에서 새 `human_confirmed` target을 append한다. enqueue와 같은 notice 잠금으로 queued/running 경합을 닫고, 새 target 뒤 과거 결과는 저장된 이력으로만 남긴다. current와 회사 핏은 옛 target 결과를 사용하지 않는다.

## 3. 격리·자원·감사

- worker: `network_mode none`, non-root UID, `cap_drop ALL`, `no-new-privileges`, `mem_limit 1g`. R0 실측은 `pids_limit 128`에서 컨테이너 최대 4 pids였고, 이 경계와 60초 조건을 통과했다.
- 네 native 호출의 JSON stdout cap은 각 1 MiB이며 R0에서 관측된 최대는 747,110 B다. per-artifact output cap과 문서당 shared deadline은 별도 경계로 유지한다.
- rhwp stdout JSON의 `untrustedContent=true` 필드는 원문 유래다. 로그·감사·프롬프트에 넣지 않는다. 오류 메시지는 rhwp의 한국어 오류 문자열을 그대로 저장하지 않고 안전 코드로 바꾼다(Spec §5).
- 준비 실패 코드는 converter가 낸 안전 코드를 attempt `error_code`에 `pdf_preparation_failed:<code>` 형태로 남긴다(64자 한도 안). 감사 `safe_metadata`에도 같은 코드를 둔다.

## 4. LLM 경계

| 역할 | 입력 | 출력·검증 | 상태 |
|---|---|---|---|
| 개요 해석(v4) | 선택 페이지 텍스트 블록 `{pdf_page, text}` | `bidops.prespec-overview-page-review.v3`, validator v3(페이지·숫자·영문 대조) | 구현됨, 페이지 출처만 rhwp로 교체 |
| 범위 선택 보조 | `digest --sections` 절 목록(제목·쪽·글자수)과 결정적 선택기의 후보 | 절 인덱스 집합. 사람 확인 뒤에만 target 동결 | 신규, 마지막 단계 |
| 심층 검토 역할별 분석 | segment별 구조 블록 + 승인 프로필 projection | deep-review-v2 §5 계약, 결정적 검증 | 보류 유지, 이 작업에서 입력 계약(페이지 부착)만 준비 |

모델은 파일·경로·바이너리 산출물을 받지 않는다. rhwp `armor`는 후보로만 기록한다.

현재 개요 policy v5는 초안 주장과 별도 의미 검토의 두 단계를 사용한다. 정상은 2회, 초안 형식 재생성을 포함한 최대는 3회이고 의미 검토는 최대 1회다. 각 호출 전에 실제 SDK 요청(system/user/correction/strict schema/generation/timeout)의 canonical UTF-8 byte 수를 입력 token 상계로 삼고 chat template 1,024토큰과 출력 16,384토큰을 더해 `min(확인된 served max_model_len, policy ceiling 262,144)`과 대조한다. stage별 24,000자 상한도 별도로 유지한다. 확인 불가·초과는 authorization과 HTTP 전에 `failed/input_capacity_exceeded`로 끝나므로 내용 검증 실패가 아니며, 의미 단계에서 막힌 경우 이미 받은 초안 호출 이력은 보존한다. 자동 절단·요약·분할이나 C-1 context 재사용은 없다.

2026-09-11 09:08~09:13 KST 참조 실행은 744·749·759·761에 초안 stage만 각 1회 전송해 응답 4회를 받았다. 결정적 검증 실패 시 의미 호출과 게시를 생략하는 계약에 따라 모두 `needs_human_review`로 종료했고 semantic dispatch, 형식 재생성, result 생성은 각 0건이다. 이는 OFF/늦은 응답 차단을 실제로 재현한 실행과는 구분한다. 모델은 `qwen3.8-27B`, 선언 revision은 `5fa804ff0ecc0de9167f8b63127c42e1d421a9451662922ace8622d0b01b824e`, 확인 context는 262,144이며 정책·payload·호출 상한과 원문·검증 게이트는 변경하지 않았다. 결과 표식은 `unmeasured_reference`로 유지한다.

## 5. 마이그레이션과 호환

- 역사: 0022 뒤 0023 migration에 nullable 열과 `renderer` 값, worker INSERT 권한을 추가했다. 현재 head는 0025이고 2026-09-11 MVP 보완에서는 새 migration이 없다.
- 기존 35/59/142 snapshot·result·current는 그대로 둔다. 새 renderer로 세 표본을 다시 준비하면 새 snapshot·target이 생기고 `current`는 새 attempt 기준으로 바뀐다. 옛 결과의 PDF 링크는 옛 snapshot PDF를 계속 가리킨다.
- 제거 대상: `vendor/rhwp/rhwp.js`, `rhwp_bg.wasm`, `rhwp_convert.mjs`, `rhwp_render_canvas.mjs`, Canvas HTML builder, receipt 검사, Chromium/Node 지문, Dockerfile의 chromium·chromium-sandbox·nodejs 설치, compose의 Chromium용 완화. 제거는 새 경로가 세 표본 인수를 통과한 단계 뒤에 한다.

## 6. 실패 처리

| 실패 | 처리 |
|---|---|
| `export-hwpx` verify 불일치(exit 3/4) | `hwpx_verify_failed`, 원본 보존, 사람 확인 |
| 암호 문서(`passwordProtected`) | `encrypted_document`, 사람 확인 |
| 페이지 수 불일치(pdf·text·pages) | `pdf_page_mismatch` |
| 전부 빈 페이지 텍스트 | `pdf_empty_text` |
| 정렬 실패 블록 | 대응표에 `unmapped`, 문서는 성공. 매핑률을 snapshot에 기록 |
| rhwp 비정상 종료·timeout·출력 한도 | `conversion_required`·`timeout`·`output_size_limit`(호출별 JSON stdout 1 MiB cap 또는 per-artifact cap 초과; 기존 코드 유지) |
| 바이너리 hash·폰트 manifest 불일치 | `renderer_binding_invalid`·`font_binding_invalid`(기존) |

2026-09-11 MVP에서 보조 `digest --sections`는 core 생성/검증 뒤에 실행한다. 정상
`outline|clause|page`, 전체/반환 개수와 `truncated`/`candidates_truncated`를 v2 sidecar에
기록하며 후보의 부재·bounded 실행·해석 실패는 unavailable 경고, 부분 반환은 incomplete
경고와 수동 쪽 선택으로 연결한다. unavailable 경고가 있으면 scratch sidecar descriptor와 snapshot의 세 후보 참조는 null을 허용하되, 경고 없는 누락과 존재하는 후보의 canonical bytes·hash 불일치는 차단한다. v1 reader는 과거 산출물을 계속 읽는다. 이 분리는 후보에만
적용하며 표의 core 안전·무결성 실패는 유지한다. 같은 줄 복수 장 제목과 선택된 장의
정규화 제목이 정확히 `제안개요`인 작성 양식은 `ambiguous_scope_boundary`로 닫는다.
새 테이블·변환기·범용 목차 해석기는 추가하지 않는다.

페이지 선택 manifest는 선택한 모든 쪽의 원문 text, 선택 text hash와 source page text hash를
그대로 유지한다. 유효 본문이 하나라도 있으면 공백 쪽도 삭제하거나 번호를 당기지 않는다.
전체 쪽이 공백이면 runner가 `manifest_invalid`로 호출 전에 닫는다. 초안이 반환된 뒤에는 claim
결정적 검증이 원문에서 정확히 대응하는 비어 있지 않은 quote를 요구하므로 공백 쪽을 사실 근거로 승격시킬 수 없다.

## 7. 검증 전략

- 단위: rhwp JSON 파서(필드·untrusted 처리), 정렬기(정상·페이지 걸침·빈 문단·표 셀·미매핑), 계약 스키마.
- 통합(격리 worker 이미지): 세 표본으로 F1~F6, 금액·ID 보존, 페이지 수 일치, 재실행 시 HWPX·텍스트·대응표 바이트 동일. PDF 바이트 동일성은 같은 검증 이미지에서 실행한 세 표본의 관측에만 한정하고 보편적 보증으로 취급하지 않는다.
- 운영 인수: 세 표본 새 snapshot 준비, page-overview API·PDF 링크, segments의 `page_range`, 1280×800·1440×900 화면.
- 위 표본 인수와 전체 스위트 1회는 2026-09-10 rhwp 도입 당시의 검증 범위다. 현재 MVP는 변경 경로의 필요한 검사만 수행하며, 통과한 표본·화면·전체 스위트를 반복하지 않는다.
