# rhwp 문서 변환 파이프라인 요구사항

작업명: rhwp-document-pipeline · 기준일: 2026-09-10 · 상태: 진행 중 (R0 계약 종결, 다음 R1은 coordinator acceptance 대기)
결정의 근거는 [ADR.md](ADR.md), 구조는 [Design.md](Design.md), 계약·단계는 [Spec.md](Spec.md)에 있다.

## 1. 목표

사전규격 첨부(HWP·HWPX·PDF)를 운영 서버의 프로그램(rhwp)만으로 변환하고, 한 문서 버전에 대해 HWPX·구조·PDF·페이지 텍스트·문단↔페이지 대응표를 한 번에 만들어 불변 저장한다. LLM은 변환에 관여하지 않고 개요 해석, 필요 범위 선택 보조, 심층 검토 역할별 분석만 맡는다.

## 2. 비목표

- 발주계획 C-2 선별, 추적 승인, 최종 Go/No-Go는 바꾸지 않는다.
- LLM으로 문서를 파싱하거나 요구사항 표를 레코드로 바꾸지 않는다.
- OCR, 이미지화된 PDF 보정, XML 보정, 원문 추정 보정은 하지 않는다.
- 암호 문서·HML·ZIP 첨부 지원은 범위 밖이다. 지금처럼 `needs_human_review`·`unsupported_media`로 남긴다.
- 원본 PDF 첨부의 재렌더는 하지 않는다(Poppler 텍스트 경로 유지).
- 기존 완료된 개요·리뷰·snapshot 행을 덮어쓰거나 자동 재실행하지 않는다.

## 3. 기능 요구

| ID | 요구 | 수용 기준 |
|---|---|---|
| F1 | HWP 입력은 rhwp `export-hwpx --verify --verify-pages --json`으로 HWPX를 만들고, `verify.identical=true`·`verifyPages.identical=true`인 결과만 정본으로 쓴다 | 표본 3건에서 통과. 불일치는 `hwpx_verify_failed`로 준비 실패 |
| F2 | HWPX(원본 또는 변환본)에서 기존 stdlib 추출기로 구조 JSON(`bidops.document-structure.v1`, paragraph·table·table_cell 블록)을 만든다 | 블록 계약·block_key 규칙 불변. 기존 `document_segments`·심층 검토 v1 locator가 그대로 동작 |
| F3 | HWP/HWPX에서 rhwp `export-pdf --json`으로 PDF를 만들고 `pageCount == renderedCount`이며 `pdfinfo` 페이지 수와 같을 때만 저장한다 | 표본 3건 통과(79·53·31쪽). 불일치는 `pdf_page_mismatch` |
| F4 | 같은 실행에서 rhwp `export-text --json`으로 페이지별 텍스트를 만들고 페이지 수가 F3와 같아야 한다 | 페이지별 `text_sha256`을 snapshot에 기록. 전부 빈 텍스트면 `pdf_empty_text` |
| F5 | 같은 실행에서 rhwp `dump-pages --json`으로 문단↔페이지 대응표를 만들고 F2 블록에 결정적으로 정렬한다 | identity는 항상 `(section, paraIndex)`이며 `extras`도 포함한다. extractor identity가 증명된 원본 HWPX만 source XML top-level ordinal을 사용하고, HWP 변환 HWPX의 paragraph·table-cell과 원본 HWPX의 table-cell은 비어 있지 않은 FULL text가 정확히 한 export-text 페이지에 정확히 한 번 나타날 때만 `page_text`로 매핑한다. 빈 블록과 그 밖의 미확인 블록은 `unmapped`로 남기고 문서 전체를 실패시키지 않는다. prefix/LCS/whitespace correction/fuzzy matching/인접 페이지 상속/다중 페이지 추정은 사용하지 않는다. 매핑률은 정보성으로 기록한다. |
| F6 | 산출물 ①~⑥(ADR-RDP-003)을 versioned object로 저장하고 원본 hash·바이너리 hash·폰트 manifest·옵션 hash로 결속한다 | 같은 (원본 version, 바이너리 hash, 폰트 digest, 옵션 hash)면 재변환 없이 재사용. 재사용 시 object version·etag·최신 ClamAV clean 재확인(현행 규칙) |
| F7 | v4 페이지 개요·회사 핏·화면 PDF 링크는 rhwp PDF의 물리 페이지를 쓴다 | `GET /api/pre-specs/{id}/overview-pages`와 근거 PDF endpoint가 새 snapshot을 서빙 |
| F8 | 심층 검토·segment·inventory는 HWPX 구조를 입력으로 쓰고 대응표로 페이지를 붙여 화면에 표시한다 | segment 목록에 페이지 범위가 보인다. 매핑 없는 segment는 "페이지 미확인" 표시 |
| F9 | 필요 범위 선택은 결정적 heading 규칙을 먼저 쓰고, 경계를 못 정할 때만 rhwp `digest --sections --json`의 절 목록을 LLM에 후보로 준다. 선택 결과는 사람이 확인한다 | LLM 선택은 `needs_human_review` 상태로 저장되고 자동 실행을 열지 않는다 |
| F10 | Canvas+Chromium 경로와 vendored WASM·Node adapter·인쇄 receipt 검증을 제거한다 | 이미지에서 chromium·chromium-sandbox·node 관련 의존성이 빠지고 관련 테스트가 rhwp 계약으로 대체된다 |
| F11 | 기존 35/59/142 snapshot과 결과는 이력으로 보존한다. 새 renderer로 세 표본을 다시 준비해 인수한다 | 기존 행 미변경, 새 snapshot 3건 + UI 페이지 링크 확인 |

## 4. 비기능 요구

| ID | 요구 | 기준 |
|---|---|---|
| N1 | 격리 | worker는 `network_mode none`, non-root, `cap_drop ALL`, `no-new-privileges` 유지. rhwp 자식은 기존 `_run_limited_subprocess` rlimit(CPU 60초, AS/DATA, FSIZE, NOFILE 256, CORE 0) 아래에서 실행 |
| N2 | 자원 | 85쪽급 문서를 1 GiB·`pids_limit 128` 이하에서 60초 안에 처리. 실측 기준선은 12.8초·RSS 128 MB. Chromium 제거 뒤 pids 상한 재측정 |
| N3 | 시간 | 문서당 준비 deadline 300초 유지(ProcessorOptions 상한). rhwp 4호출이 하나의 deadline을 공유 |
| N4 | 재현성 | 같은 입력·바이너리·폰트·옵션에서 HWPX·페이지 텍스트·대응표는 바이트 동일. PDF 바이트 동일성은 같은 검증 이미지에서 실행한 세 표본의 측정 증거에만 한정하며 보편적 보증으로 취급하지 않는다 |
| N5 | 보안 | rhwp JSON의 `untrustedContent`·`untrustedFields`(예: `textPreview`)는 원문 유래 데이터로 취급하고 로그·감사·프롬프트 지시로 쓰지 않는다. 경로·자격증명·원문은 감사와 오류 메시지에 넣지 않는다 |
| N6 | 감사 | 준비 실패는 converter가 돌려준 안전 코드를 attempt `error_code`와 감사 `safe_metadata`에 함께 남긴다(현재 `pdf_preparation_failed`로 감춰지는 문제 해소) |
| N7 | 호환 | `bidops.document-structure.v1`, `bidops.prespec-overview-page-review.v3`, page-overview REST, `document-segments.v1` 계약을 깨지 않는다. snapshot 계약은 새 버전(`bidops.rhwp-pdf-snapshot.v1`)으로 추가한다 |
| N8 | 운영 | 기본 비활성·scheduler 비활성·hosted fallback 금지·참조 실행 표식(`unmeasured_reference`) 규칙 유지 |

## 5. 제약과 강제 게이트(기존 규칙 재확인)

- 미확인 값은 `unknown`·`null`로 보존하고 추정 보정하지 않는다.
- 모델 근거는 원문 위치와 연결되고 결정적 검증을 통과해야 한다. 실패는 사람 검토로 보낸다.
- 외부 모델에는 승인 payload만 건별 전송한다. rhwp가 만든 산출물도 텍스트 블록만 모델에 들어간다.
- 변환 실패 HWP를 모델에 직접 넣지 않는다(ADR-0010).

## 6. 표본과 측정 기준선

| 표본 | 형식 | rhwp PDF | HWP→HWPX verify | 구조 블록(변환 HWPX 기준) |
|---|---|---|---|---|
| notice 142 `R26BD00271191` 별첨.제안요청서 | HWPX 840,114 B | 79쪽, 4,754,740 B, 12.8초 | 해당 없음 | 기존 구조 유지 |
| notice 10 제안요청서(`docs/design/(공고 2026-25) 제안요청서.hwp`) | HWP 178,176 B | 53쪽, 2,943,696 B, 10.5초 | diff 0, 53=53, 0.23초 | 2,493블록(빈 890), ID 50 |
| notice 10 과업지시서(`docs/design/(공고 2026-25) 과업지시서.hwp`) | HWP 127,488 B | 31쪽, 1,731,063 B, 4.4초 | diff 0, 31=31, 0.11초 | 1,353블록(빈 314), ID 50 |

인수 기준: 위 세 표본이 F1~F8을 새 코드 경로에서 통과하고, 142의 p4·p5 금액·기간·인력 수치(`298,735,350원`, `365일`, `189MD`, `13,225,835,150원`, `12개월`)가 페이지 텍스트에서 확인되며, 개요 v4 선택 범위(142: 감리 개요 장)가 새 페이지 번호로 다시 고정된다.

R0 기준선의 stdout 측정은 같은 검증 이미지에서 세 표본을 두 번 실행한 결과다. 네 native 호출별 JSON stdout cap은 1 MiB(1,048,576 B)로 고정하고, 관측된 최대는 747,110 B다. 이 cap은 `max_output_bytes` per-artifact 상한과 문서당 shared deadline을 대체하지 않으며, 무제한 stdout이나 파일 출력 우회는 허용하지 않는다.

## 7. 열린 질문

- R0에서 `paraIndex`는 표 셀 문단을 포함하지 않는 section별 최상위 본문 문단 공간으로 확정했다. HWP ordinal crosswalk 부재는 추가 실험을 요구하지 않는 보수적 지원 동작이며, exact FULL text 단일 페이지 매치 외에는 `unmapped`로 둔다.
- pids 상한은 R0 실측에서 `pids_limit 128`·컨테이너 최대 4 pids로 통과했으며, 이후 운영 재조정은 해당 단계의 별도 인수 범위로 남긴다.
- 인쇄 쪽수(`displayPage`)를 화면에 병기할지 정하지 않았다.
