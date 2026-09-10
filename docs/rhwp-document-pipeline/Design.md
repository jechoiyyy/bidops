# rhwp 문서 변환 파이프라인 설계

작업명: rhwp-document-pipeline · 기준일: 2026-09-10 · 상태: 진행 중
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

③~⑤는 같은 입력 파일(HWP는 원본 HWP, HWPX는 원본 HWPX)에 대해 실행한다. HWP를 변환 HWPX로 다시 렌더하지 않는다. 이유는 페이지네이션이 원본과 같아야 하고 rhwp가 HWP를 직접 읽기 때문이다. 단, ⑥의 정렬은 ②의 블록(변환 HWPX 기준)과 ⑤의 `paraIndex`(원본 HWP 기준)를 맞추므로, HWP→HWPX 변환이 문단 순서를 보존한다는 F1의 `verify` 결과에 의존한다.

각 rhwp 호출은 기존 `_run_limited_subprocess`로 실행한다. 공유 deadline 하나, `output_limit` 256 KiB(stdout JSON은 작음, 파일 산출물은 경로로), `preexec_fn=_resource_limiter(max_output_bytes)`. rhwp는 단일 프로세스라 Chromium 예외(AS/DATA 해제, FSIZE 4배)가 필요 없다.

### 2.3 페이지 텍스트와 대응표

- 페이지 텍스트 정본은 `export-text --json`이다. Poppler `pdftotext`는 원본 PDF 첨부에만 쓴다. 검증으로 `pdfinfo` 페이지 수와 `export-pdf`의 `pageCount`, `export-text`의 `pageCount`, `dump-pages`의 `pageCount`가 모두 같아야 한다.
- 대응표는 `dump-pages`의 `pages[].columns[].items[]`에서 `kind`, `paraIndex`, `pageIndex`를 읽어 `paraIndex → {page_first, page_last}`를 만든다(문단이 페이지를 넘으면 범위). 그 다음 구조 블록을 `paraIndex`에 정렬한다(Spec §4). `textPreview`는 정렬 검증에만 쓰고 저장하지 않는다.
- 대응표는 `bidops.para-page-map.v1` JSON으로 `structure` namespace에 저장하고 snapshot 행이 object id·hash로 가리킨다.

### 2.4 데이터 모델

기존 `prespec_v4_pdf_snapshot`(0021)은 유지하고 새 snapshot 계약을 추가한다. 옛 행은 `renderer='rhwp-canvas-chromium'`으로 이력이 되고, 새 행은 `renderer='rhwp-svg-pdf'`다. 열 추가는 nullable로만 한다.

| 열(신규) | 뜻 |
|---|---|
| `hwpx_content_object_id`, `hwpx_location_id` | 변환 HWPX 객체(원본이 HWP일 때만) |
| `hwpx_verify_jsonb` | `export-hwpx --json`의 `verify`·`verifyPages` 결과 |
| `structure_id` | 이 준비에서 만든 `document_structure` 행 |
| `para_page_map_content_object_id`, `para_page_map_sha256` | 대응표 객체 |
| `rhwp_binary_sha256`, `rhwp_version` | renderer provenance(기존 `renderer_jsonb`에도 기록) |

`renderer_digest`는 (바이너리 sha, 폰트 manifest sha, 옵션 sha)의 결합이라 바이너리·폰트 교체 시 캐시가 무효화된다.

### 2.5 소비자 연결

- v4 페이지 개요·회사 핏·page-overview API·근거 PDF endpoint: snapshot의 PDF·페이지 텍스트를 지금과 같은 필드로 읽는다. 변경은 renderer 이름과 page-text 출처뿐이다.
- 심층 검토·`document_segments`: 구조 JSON을 지금처럼 쓰고, `GET /api/document-structures/{id}/segments` 응답에 `page_range`(대응표 유래, 없으면 `null`)를 추가한다. 화면은 페이지가 있으면 PDF 링크를 붙인다.
- 범위 선택: 기존 heading selector가 `unknown`이면 `digest --sections --json`의 `sections[].{title,page}`를 후보로 만들고, F9대로 LLM 보조 선택을 `needs_human_review`로 저장한다. 이 부분은 이번 구현의 마지막 단계다.

## 3. 격리·자원·감사

- worker: `network_mode none`, non-root UID, `cap_drop ALL`, `no-new-privileges`, `mem_limit 1g`. `pids_limit`은 rhwp 실측 뒤 128으로 되돌리는 것을 기본 후보로 둔다(Chromium 스레드 문제가 사라지므로).
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
| rhwp 비정상 종료·timeout·출력 한도 | `conversion_required`·`timeout`·`output_size_limit`(기존 코드 유지) |
| 바이너리 hash·폰트 manifest 불일치 | `renderer_binding_invalid`·`font_binding_invalid`(기존) |

## 7. 검증 전략

- 단위: rhwp JSON 파서(필드·untrusted 처리), 정렬기(정상·페이지 걸침·빈 문단·표 셀·미매핑), 계약 스키마.
- 통합(격리 worker 이미지): 세 표본으로 F1~F6, 금액·ID 보존, 페이지 수 일치, 재실행 시 HWPX·텍스트·대응표 바이트 동일.
- 운영 인수: 세 표본 새 snapshot 준비, page-overview API·PDF 링크, segments의 `page_range`, 1280×800·1440×900 화면.
- 검증은 변경 경로에 한정하고 전체 스위트는 최종 트리에서 1회만 돌린다.
