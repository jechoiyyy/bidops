# rhwp 문서 변환 파이프라인 설계

작업명: rhwp-document-pipeline · 기준일: 2026-09-10 · 상태: 진행 중 (R0 계약 종결, 다음 R1은 coordinator acceptance 대기)
요구는 [Requirements.md](Requirements.md), 결정은 [ADR.md](ADR.md), 세부 계약과 단계는 [Spec.md](Spec.md)에 있다.

## 1. 현재 구조와 바뀌는 지점

```text
[현재]
attachment fetch ─ quarantine ─ ClamAV ─ DocumentProcessor(prepare_pdf=False)
                                            ├─ HWP ─ node rhwp_convert.mjs(WASM exportHwpx) ─┐
                                            └─ HWPX ────────────────────────────────────────┴─ extract_hwpx ─ 구조 JSON(page=구역)
v4 prepare ──────────────────── DocumentProcessor(prepare_pdf=True)
                                            ├─ node rhwp_render_canvas.mjs(geometry)
                                            ├─ Canvas print HTML + Chromium --print-to-pdf
                                            ├─ pdfinfo receipt, stdlib PDF limit, pdftotext
                                            └─ PDF + 페이지 텍스트 (구조와 미연결)

[목표]
attachment fetch ─ quarantine ─ ClamAV ─ DocumentProcessor(rhwp)
                                            ├─ HWP:  rhwp export-hwpx --verify --verify-pages --json ─ HWPX(검증)
                                            ├─ HWPX: extract_hwpx ─ 구조 JSON (계약 불변)
                                            ├─ rhwp export-pdf --json ─ PDF
                                            ├─ rhwp export-text --json ─ 페이지 텍스트
                                            ├─ rhwp dump-pages --json ─ 문단↔페이지
                                            └─ 정렬기: 구조 블록 ↔ paraIndex ↔ 페이지  →  대응표
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
- 범위 선택: 기존 heading selector가 `unknown`이면 `digest --sections --json`의 `sections[].{title,page}`를 후보로 만들고, F9대로 LLM 보조 선택을 `needs_human_review`로 저장한다. 이 부분은 이번 구현의 마지막 단계다.

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

## 5. 마이그레이션과 호환

- Alembic: 0022 뒤 migration 하나. nullable 열 추가와 `renderer` 값 확장만. 기존 행·trigger·권한 allowlist는 유지하고 새 열의 worker INSERT 권한만 추가한다.
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

## 7. 검증 전략

- 단위: rhwp JSON 파서(필드·untrusted 처리), 정렬기(정상·페이지 걸침·빈 문단·표 셀·미매핑), 계약 스키마.
- 통합(격리 worker 이미지): 세 표본으로 F1~F6, 금액·ID 보존, 페이지 수 일치, 재실행 시 HWPX·텍스트·대응표 바이트 동일. PDF 바이트 동일성은 같은 검증 이미지에서 실행한 세 표본의 관측에만 한정하고 보편적 보증으로 취급하지 않는다.
- 운영 인수: 세 표본 새 snapshot 준비, page-overview API·PDF 링크, segments의 `page_range`, 1280×800·1440×900 화면.
- 검증은 변경 경로에 한정하고 전체 스위트는 최종 트리에서 1회만 돌린다.
