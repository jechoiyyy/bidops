# rhwp 문서 변환 파이프라인 결정 기록

작업명: rhwp-document-pipeline
기준일: 2026-09-11
상태: native 변환·MVP 보완 구현과 승인된 운영 배포·6건 source-only 재준비, Qwen 참조 실행 4건 사람 검토 대기 종결. 이 폴더의 다섯 문서(ADR·Requirements·Design·Spec·Plan)가 이 작업의 정본이며, 작업 중 바뀌거나 추가되는 결정은 여기에 덧붙인다.

관련 정본: [docs/ARCHITECTURE.md](../ARCHITECTURE.md), [ADR-0010 HWPX 분석 정본](../tracking/decisions/0010-hwpx-canonical-input.md), [ADR-0051 deep-review-v2 결정적 부분](../tracking/decisions/0051-deep-review-v2-deterministic-subset.md), [deep-review-v2 §7 HWPX·PDF 처리 방향](../deep-review-v2/document-analysis-design.md), [사전규격 v4 구현 계획](../tracking/prespec-v4-implementation-plan.md).

## 배경 요약

2026-09-09 분석에서 확인한 사실이다.

- 사전규격 첨부는 HWP 95, HWPX 54, PDF 16건(현재 문서 165건)이며 HWP가 과반이다.
- 당시 코드에는 두 변환 계약이 있었다. 기본 경로는 HWP를 vendored WASM(rhwp 파생 `claw-hwp` 빌드)으로 HWPX로 바꾼 뒤 stdlib XML 추출기로 문단·표·셀 블록을 만들었다. 이 경로의 `page`는 물리 페이지가 아니라 XML 구역 순번이었다. v4 경로는 같은 WASM의 Canvas 렌더를 Chromium으로 인쇄해 PDF를 만들고 Poppler로 페이지 텍스트를 뽑았다.
- v4 경로는 Chromium 때문에 실행 비용과 검증 단계가 많다. notice 142(85쪽 HWPX)는 `pids_limit 128`과 출력 예산 20 MiB 때문에 실패했고 2026-09-10에야 준비가 끝났다([findings](../tracking/findings.md)).
- 변환된 HWPX 바이트는 저장되지 않아 재추출·감사가 불가능하고, HWPX 구조와 PDF 페이지는 별도 테이블에 저장돼 서로 연결되지 않는다.
- 모델에는 어느 경로든 텍스트만 들어간다. PDF가 필요한 이유는 근거를 물리 페이지로 가리키는 계약 때문이지 모델 때문이 아니다.

네이티브 rhwp CLI(`edwardkim/rhwp` v0.8.6, Rust)를 2026-09-10 실측했다.

| 항목 | rhwp `export-pdf` (svg backend) | 당시 Canvas+Chromium |
|---|---|---|
| 142 HWPX (840 KB) | 12.8초, 79쪽, 4.7 MB, RSS 128 MB | 20.8초, 85쪽, 11.0 MB, pids 512 필요 |
| 제안요청서 HWP (178 KB) | 10.5초, 53쪽, 2.9 MB | 16.6초, 54쪽, 7.6 MB |
| 과업지시서 HWP (127 KB) | 4.4초, 31쪽, 1.7 MB | 9.7초, 31쪽, 4.3 MB |
| HWP→HWPX | `export-hwpx --verify --verify-pages` 0.2초, IR diff 0, 페이지 53=53 | WASM `exportHwpx`, 검증 없음 |
| 페이지별 텍스트 | `export-text --json -p N` 내장 | Poppler `pdftotext` 별도 |
| 문단↔페이지 | `dump-pages --json`의 `paraIndex` 내장 | 없음 |

세 표본 모두 금액(`13,225,835,150원`, `319,000,000원`), 기간, 요구사항 ID 50개가 PDF 텍스트와 HWPX 구조 양쪽에 보존됐다. 이전 SVG adapter가 놓쳤던 142 p5 파란 표의 사업명·사업비·기간도 rhwp PDF에 보인다.

## ADR-RDP-001 rhwp 네이티브 CLI를 유일한 문서 변환 엔진으로 채택하고 Canvas+Chromium 경로를 제거한다

- 상태: 채택 (2026-09-10)
- 결정: HWP/HWPX의 HWPX 변환, PDF 렌더, 페이지 텍스트, 문단↔페이지 대응을 모두 rhwp 하나로 만든다. vendored WASM(`rhwp.js`·`rhwp_bg.wasm`·`rhwp_render_canvas.mjs`), Chromium 인쇄, Node geometry child, Canvas CSP HTML, 인쇄 receipt 검사는 제거한다. 원본 PDF 첨부는 지금처럼 재렌더하지 않고 Poppler 텍스트를 쓴다.
- 이유: 한 엔진이 PDF와 페이지 텍스트와 문단 배치를 같은 페이지네이션으로 내므로 쪽 번호가 서로 어긋날 여지가 없다. 단일 프로세스라 pids·메모리 상한이 작아지고, 30여 개였던 Chromium 결속 검증(receipt, 폰트 바이트 manifest, ELF 지문, 4배 파일 한도)이 바이너리 hash 하나와 폰트 manifest로 줄어든다.
- 대안: rhwp를 기본으로 두고 Chromium을 보조 렌더러로 유지. 두 렌더러의 페이지 수가 다르므로(142: 79 대 85) 근거 페이지가 렌더러에 종속되고 이미지·검증 부담이 두 배라 기각했다.
- 결과: 기존 35/59/142 v4 snapshot은 renderer digest가 달라 이력으로만 남고 새 renderer로 다시 준비한다. 과거 결과와 새 결과의 쪽 번호는 호환되지 않으며 화면은 snapshot별 PDF에만 링크한다. `docs/tracking/decisions/0010`의 "헤드리스 변환기로 HWPX"는 유지되고 변환기만 바뀐다.

## ADR-RDP-002 rhwp는 미리 빌드한 바이너리를 저장소 vendor에 등록해 배포한다

- 상태: 채택 (2026-09-10)
- 결정: `web/backend/app/deep_review/document_mcp/vendor/rhwp/bin/rhwp`(linux x86_64 ELF, 약 24 MB)를 `SHA256SUMS`와 `PROVENANCE.md`(upstream `https://github.com/edwardkim/rhwp`, 태그 `v0.8.6`, 커밋 `cac9b4f7c`, 빌드 host toolchain, 빌드 명령 `cargo build --release`)와 함께 둔다. 이미지는 이 파일을 COPY하고 실행 권한만 준다. 바이너리 SHA-256(현재 `c82684971756d58ba7391cd08c38c93bb4280ab9ebf0e21c0936574a0084fc8c`)을 snapshot의 renderer provenance에 기록한다.
- 이유: 사용자 결정. 이미지 빌드에 Rust toolchain을 넣지 않아 빌드가 빠르고, 기존 vendored SHA256SUMS manifest 검사(`test_vendored_sha256_manifest_is_deterministic_and_complete`)를 그대로 확장할 수 있다.
- 대안: (a) 이미지 multi-stage에서 고정 커밋을 cargo build. 재현성은 높지만 빌드가 길다. (b) 호스트 경로 마운트. 배포 provenance가 호스트 상태에 종속된다. 둘 다 보류.
- 결과: 바이너리 교체는 SHA256SUMS·PROVENANCE 갱신과 renderer digest 변경을 뜻하며, 그때마다 snapshot 재사용 캐시가 자연히 무효화된다. 동적 링크는 `libc`·`libm`·`libgcc_s`뿐이라 Debian 런타임 이미지에서 추가 패키지 없이 실행된다. Git LFS는 쓰지 않는다(24 MB 단일 파일, 교체 빈도 낮음).

## ADR-RDP-003 원본·HWPX·구조·PDF·페이지 텍스트·문단↔페이지 대응표를 모두 저장한다

- 상태: 채택 (2026-09-10)
- 결정: 한 문서 버전에 대해 한 번의 준비에서 다음을 모두 만들고 versioned object로 저장한다. ① 원본(불변, 기존), ② rhwp 변환 HWPX(원본이 HWP일 때, `--verify --verify-pages` 통과분만), ③ HWPX 구조 JSON(기존 stdlib 추출기, 블록 계약 유지), ④ rhwp PDF, ⑤ rhwp 페이지 텍스트 JSON, ⑥ 문단↔페이지 대응표. PDF는 문서 단위로 통째로 저장하고 "필요한 페이지만" 저장하지 않는다. 선택 페이지는 지금처럼 manifest(페이지 번호와 substring)로만 고정한다.
- 트레이드오프:

| 정책 | 장점 | 단점 |
|---|---|---|
| 모두 저장 (채택) | 재변환 없이 재추출·감사·페이지 링크가 가능. 표 셀·요구사항 ID 구조(HWPX)와 물리 페이지 근거(PDF)를 둘 다 가짐. hash 결속이 저장물에 닫힘 | 문서당 저장이 약 2배(142: 원본 0.8 MB + PDF 4.7 MB + 텍스트·구조 수백 KB). 산출물 6종의 결속 검증이 필요 |
| PDF만 저장, HWPX는 필요 시 재변환 | 저장 최소, 정본 하나 | 표 평탄화로 셀·ID locator와 segment·inventory가 약해짐. 재변환 결과가 저장 hash와 같다는 보증이 없어 감사가 약함 |
| HWPX만 저장, PDF는 요청 시 생성 | 구조 보존 | 쪽 번호 근거와 화면 링크가 매번 새로 만든 PDF에 매여 hash 결속이 깨짐. rhwp PDF 바이트 동일성은 같은 검증 이미지의 세 표본에서만 관측됐고 보편적 결정성은 보증하지 않는다 |

- 이유: 사용자 결정. 개요는 페이지 근거(A)를 유지하고 심층 검토는 HWPX 구조를 정본으로 쓰되 페이지 대응표를 붙이는 방향(C)이라 둘 다 필요하다.
- 결과: 저장 용량은 현재 MinIO 규모(문서 165건)에서 문제되지 않는다. ②는 원본이 HWPX·PDF면 생략한다.

## ADR-RDP-004 변환은 프로그램이, 해석·범위 선택 보조·역할별 분석은 LLM이 맡는다

- 상태: 채택 (2026-09-10)
- 결정: LLM은 다음 세 역할만 맡는다. (1) 개요 해석·요약(현재 v4 페이지 개요), (2) 필요 범위 선택 보조(rhwp `digest --sections`의 절 목록을 후보로 주고 결정적 heading 규칙이 경계를 못 정할 때만 호출, 결과는 사람이 확인), (3) 심층 검토 역할별 분석(deep-review-v2 §5, 결정적 segment·inventory 위에서). 문서 변환, 페이지 텍스트 추출, 요구사항 표를 레코드로 바꾸는 파싱은 LLM에 맡기지 않는다.
- 이유: 사용자 결정. 변환·파싱은 결정적으로 검증할 수 있고, LLM 출력은 원문 위치와 숫자·영문 대조 검증을 통과해야만 쓴다는 기존 강제 게이트와 맞다.
- 결과: 모델 payload는 지금처럼 텍스트 블록(페이지 번호 포함)만이다. rhwp `armor`(프롬프트 주입 격벽)는 후보로 두되 이번 범위에서 채택하지 않는다.

## ADR-RDP-005 페이지 정본은 rhwp 페이지네이션이며 한컴 인쇄 쪽수와 같음을 주장하지 않는다

- 상태: 채택 (2026-09-10)
- 결정: PDF 쪽 번호, 페이지 텍스트, 문단↔페이지 대응은 모두 같은 rhwp 실행의 페이지네이션(`pageIndex` 0 기준, 화면·계약은 1 기준 물리 순번)을 따른다. 문서에 인쇄된 쪽수(`displayPage`)는 표시용 부가 정보로만 저장한다. 화면 문구 "표지를 포함한 변환 PDF 순번 기준 · 원본 한컴 쪽 배치와 다를 수 있습니다"는 유지한다.
- 이유: 렌더러마다 쪽수가 다르다(142: rhwp 79, Canvas 85). 근거는 저장된 PDF 자신의 페이지로만 검증 가능하다.

## ADR-RDP-006 폰트는 이미지에 고정하고 manifest hash로 결속한다

- 상태: 채택 (2026-09-10)
- 결정: 런타임 이미지에 `fonts-nanum`(NanumGothic·NanumMyeongjo·NanumGothicCoding)을 추가하고 `export-pdf`에 `--fallback-serif NanumMyeongjo --fallback-sans NanumGothic --fallback-mono NanumGothicCoding`을 고정한다. 기존 `fonts-noto-cjk`는 유지한다. 설치 폰트 파일 바이트 manifest hash(기존 `_font_manifest_sha256`)를 snapshot의 `font_digest`로 계속 기록한다.
- 이유: 사용자가 실측에 쓴 조합이다. 페이지네이션은 폰트에 종속되므로 폰트 변경은 renderer 변경과 같은 무효화 효과를 가져야 한다.
- 결과: 현재 worker 이미지에는 Noto CJK만 있어 이미지 재빌드가 필요하다. 문서 내장 폰트 이름을 rhwp가 어떻게 매핑하는지는 실측으로 확인한다(실측 PDF에는 NotoSansKR·NanumMyeongjo·Unifont 서브셋이 임베드됐다).

## ADR-RDP-007 개요는 PDF 페이지 근거를 유지하고 심층 검토는 HWPX 구조 정본에 페이지 대응표를 붙인다

- 상태: 채택 (2026-09-09 대화, 2026-09-10 기록)
- 결정: v4 페이지 개요와 회사 핏의 근거 단위는 물리 PDF 페이지로 유지한다. 심층 검토의 segment·요구사항 inventory·`table_cell` locator는 HWPX 구조 블록으로 만들고, 사람 확인·화면 링크에는 대응표로 얻은 페이지를 붙인다. 이 결정은 deep-review-v2 §7.1의 "HWPX는 의미 구조 정본, PDF는 시각·locator 보조"를 그대로 따른다.
- 이유: 페이지 텍스트만으로는 표 셀과 요구사항 ID가 평탄화돼 심층 검토 검증기(`table_cell`, 정확 부분문자열)가 만족되지 않고, HWPX만으로는 물리 페이지 근거와 화면 링크가 불가능하다.

## ADR-RDP-008 R0 native stdout과 문단-페이지 대응표 계약을 보수적으로 종결한다 (역사)

- 상태: 2026-09-10 당시 채택·종결(R1 이후 단계도 같은 날 완료)
- 결정: `export-hwpx`, `export-pdf`, `export-text`, `dump-pages` 네 native 호출 각각에 JSON stdout 1 MiB(1,048,576 B) cap을 적용한다. cap 초과는 `output_size_limit`로 실패하며, 무제한 stdout이나 파일 출력 우회는 허용하지 않는다. `max_output_bytes` per-artifact 상한과 문서당 shared deadline은 별도로 유지한다.
- 결정: 대응표 identity는 extras를 포함해 항상 `(section, paraIndex)`다. 원본 HWPX는 extractor identity가 증명된 경우에만 source XML top-level ordinal을 사용하고 rendered block list ordinal을 맹목적으로 사용하지 않는다. HWP에서 변환한 HWPX는 ordinal crosswalk를 가정하지 않으며, 비어 있지 않은 paragraph·table-cell FULL text가 `export-text`의 정확히 한 페이지에서 정확히 한 번만 나타날 때 `match="page_text"`로 연결하고 `para_index`는 `null`로 둔다. 빈 블록은 항상 `unmapped`다.
- 결정: prefix·LCS·whitespace correction·fuzzy matching·인접 페이지 상속·다중 페이지 추정은 사용하지 않는다. exact match가 아니면 `unmapped`로 보존하고, 매핑률은 F5의 정보성 지표로만 기록한다. HWP ordinal crosswalk 부재는 추가 실험을 요구하는 선행조건이 아니라 이 보수적 지원 동작으로 명시한다.
- 근거와 게이트: 기존 R0 격리 측정만 사용한다. 세 표본의 같은 검증 이미지 실행에서 관측된 JSON stdout 최대는 747,110 B였고, pids·시간·자원·산출물 결정성 기준을 충족했다. 따라서 최초 실측 시점의 닫힌 게이트 기록은 역사로 보존하면서 R0 게이트를 통과로 종결했다. 당시 다음 R1은 coordinator acceptance 뒤에 열었다.
- 결정성 범위: PDF 바이트 동일성은 같은 검증 이미지에서 실행한 세 표본의 동일 hash라는 관측에만 한정한다. 이를 모든 입력·이미지·환경에 대한 보편적 결정성 보증으로 해석하지 않는다.

## ADR-RDP-009 PDF·페이지 텍스트 core와 절 후보 digest를 분리한다

- 상태: 채택 (2026-09-11)
- 결정: native PDF, 전체 페이지 텍스트, 문단↔페이지 대응표, renderer·원본 결속을 먼저 검증한 뒤 `digest --sections`를 보조 단계로 실행한다. core의 안전·hash·version·페이지 수 검증 실패는 계속 준비 실패다. digest의 bounded 실행 또는 해석 실패는 `section_candidates_unavailable`, 전체 후보 중 일부만 반환된 경우는 `section_candidates_incomplete` 경고로 남기며 이미 검증한 core를 무효화하지 않는다. scratch·snapshot의 후보 descriptor/참조는 unavailable 경고와 함께일 때만 null일 수 있다. 경고 없는 누락과 존재하는 후보의 canonical bytes·hash·version 오류는 계속 fail closed한다.
- 결정: 현재 생산 계약은 `bidops.section-candidates.v2`다. `mode=outline|clause|page`, `section_count`(전체), `returned_count`(반환), `truncated`(upstream 절단 표식), `candidates_truncated`(반환 수가 전체보다 작음)를 구분한다. 생산자는 v2를 쓰고 reader는 기존 v1을 계속 읽는다. 과거 v1 bytes와 snapshot은 바꾸지 않는다.
- 이유: pinned rhwp는 정상 outline을 반환하며 문서 전체 후보 수와 최대 50개 반환 목록이 다를 수 있다. 보조 목록의 완전성을 PDF·페이지 텍스트의 무결성과 같은 성공 조건으로 묶으면 안전한 문서가 잘못 차단된다.
- 결과: 부분 후보의 index 선택과 `--assist-range`는 차단하고 PDF를 본 사람의 직접 쪽 선택만 허용한다. 후보 목록은 탐색 보조이지 문서 전체 구조나 자동 실행 권한이 아니다.

## ADR-RDP-010 범위 확인은 후보와 독립된 새 target이며 과거 실행을 덮지 않는다

- 상태: 채택 (2026-09-11) → 같은 날 뒤이은 개요 스택 재작성으로 대체됨. `prespec_v4_target`
  테이블과 `overview-pages/targets/{target_id}/pdf`·index 기반 range-confirmations는
  migration 0026에서 삭제됐고, 범위 확인은 `POST .../overview/range-confirmations`(body
  `{page_start, page_end, note?}`)로 단순화됐다([ADR-0054](../tracking/decisions/0054-prespec-overview-mvp-rewrite.md)).
  아래는 그 이전의 결정 기록이다.
- 결정: 담당자는 후보 유무와 관계없이 고정 PDF에서 `first_page`~`last_page`를 직접 선택할 수 있다. 확정은 `human_confirmed` `ready` target과 감사만 추가하며 attempt, activation, 모델 전송, 내용 검증 결과를 만들지 않는다. `attempt_enqueued=false`는 항상 유지한다.
- 결정: queued/running attempt가 있으면 범위 변경을 거부한다. 새 target이 생기면 이전 target의 queued/running/completed 실행은 현재 projection에서 `stale/target_superseded`, `result_id=null`이고 이전 결과·검증·사람 리뷰는 이력으로 보존한다. 이전 target을 다시 enqueue할 수도 없다. 회사 핏 등 후속 소비자는 새 target에 결속되지 않은 과거 완료 결과를 현재 결과로 사용하지 않는다.
- 결정: attempt가 없거나 실패·검토 대기여도 `GET /api/pre-specs/{notice_id}/overview-pages/targets/{target_id}/pdf`로 target PDF를 열 수 있다. 안전한 과거 document에 결속된 target도 열람할 수 있고 current document 조건은 범위 확정에만 적용한다. 조회는 공고/target/document/snapshot 계보, 원본과 PDF의 최신 clean scan, 고정 object version·etag·size·SHA-256을 모두 다시 검사한다. PDF 열람은 전송 승인이나 품질 통과가 아니다.
- 이유: 후보가 부분이거나 모호한 경우에도 사람은 안전한 원문 PDF 자체로 범위를 판단할 수 있어야 하며, 범위 변경이 과거 결과의 불변성과 현재성을 동시에 지켜야 한다.

## ADR-RDP-011 공백 쪽은 원문 그대로 보존하되 근거로 승격하지 않는다

- 상태: 채택 (2026-09-11)
- 결정: 선택 범위에 유효 본문이 하나라도 있으면 공백 쪽도 원래 페이지 번호, text bytes, `text_sha256`, `source_page_text_sha256`를 그대로 manifest와 모델 입력에 보존한다. 전체 선택 범위가 공백이면 호출 전에 `manifest_invalid`로 닫는다. 초안 응답 후 결정적 검증은 비어 있지 않은 quote의 원문 대응을 요구하므로 공백 quote는 claim 근거나 검증된 인용으로 승격하지 않는다.
- 이유: 경계의 공백 쪽을 제거하면 선택 범위와 저장 PDF의 페이지 정합성이 깨진다. 반대로 공백만 있는 입력은 검토할 내용이 없으므로 모델 호출 근거가 없다.

## 현재 구현·운영 경계

- 코드와 runtime 기대 migration head는 `0025_overview_claim_ledger`다. 이 MVP 보완은 새 migration을 추가하지 않았다.
- 개요 policy v5는 초안과 의미 검토의 실제 SDK 요청(system/user/correction/schema/generation 포함)을 canonical UTF-8 byte 상계로 계산한다. 각 생성 요청 전에 `request bytes + chat-template 1,024 + 출력 예약 16,384 <= min(확인된 max_model_len, policy ceiling 262,144)`를 검사한다. 초안 정상 1회 + 의미 1회, 초안 형식 재생성 포함 최대 3회이며 의미는 최대 1회다. `input_capacity_exceeded`는 해당 요청을 보내기 전의 기술적 미실행이고 내용 검증 실패가 아니다.
- 아래 R0~R7 기록은 각 시점의 구현·인수 역사다. 특히 R7의 v1 후보와 당시 운영 결과는 현재 v2 후보·수동 범위·현재성 계약을 대신하지 않는다.
- 2026-09-11 최초 배포 이미지로 web·document-worker를 교체하고 743·745·746·747·754·755를 기존 source로 각 1회 재준비했다. exact source/PDF/page-text와 최신 clean을 검증해 snapshot·target 각 6건을 append했고 기존 행은 바꾸지 않았다. 754·755가 고른 `제안개요`는 사업 개요가 아닌 작성 양식이므로 자동 ready를 입력 준비로 세지 않고 `ambiguous_scope_boundary` 사람 확인으로 보내는 최소 가드를 추가했다. scope 이미지에서 두 v2 API의 저장 target·선택 쪽 불변, warning·`can_confirm=true`, target PDF exact SHA와 no-store·nosniff·CSP sandbox를 확인했다. 이후 optional 후보 scratch/cache 경계를 보정한 최종 이미지 `bidops-prespec-mvp:20260911-advisory-final`(`sha256:223019128c101ea131d855256c950d06f0edda393281556656c1cea1e4c72d9f`)로 web·document-worker를 교체하고 코드 SHA·설정 불변·healthy를 확인했다. 고유 scratch 사례 8건과 selector·조회 4건이 통과했고 기존 API/화면 검사와 성공6건 변환은 반복하지 않았다. 추가 target·모델 실행도 0이다.
- 09:08 KST 참조 실행 직전의 19건 준비 분류는 입력 준비 4, 수동 범위 11, 문서·안전 4였고 안전 PDF 15건을 유지했다. 이 시점의 모델 실행·내용 검증 0건과 source-only activation ON/OFF 기록은 역사로 보존한다.
- 사용자가 추가 sudo chain 조회를 생략하고 현재 기능 실행을 승인한 범위에서 09:08~09:13 KST `qwen3.8-27B`(revision `5fa804ff0ecc0de9167f8b63127c42e1d421a9451662922ace8622d0b01b824e`, context 262,144)로 744·749·759·761의 초안을 각 1회 호출했고 응답 4회가 성공했다. 결정적 검증 기록상 4건 모두 `needs_human_review`(`claim_verification_required`)이며 의미 호출·형식 재생성·최종 개요·내용 통과는 각각 0건이다. 744·749·761은 `main_tasks` 섹션 누락, 모두에서 수치·단위 metadata 확인 실패가 기록됐고 759에는 분석 전제·미확인 사유 검증 문제도 기록됐다. 이는 코드 원인 단정이 아닌 저장된 검증 실패 요약이다.
- 실행 activation `11ada018-0546-4ab1-aece-15678343f6d0`을 종료하고 OFF `a6e96d1b-9c8a-40b6-87f7-d1e177c21222`를 남겨 active attempt 0건을 확인했다. 정책·호출 상한·원문 및 검증 게이트와 기존 방화벽은 바꾸거나 풀지 않았고, 결과는 `unmeasured_reference`로서 운영 품질·정책 활성화 승인이 아니다.

## 관련 결정(이 작업 밖, 참조)

- 2026-09-09 Qwen 전환 준비: 검증 실패 1회 재시도(seed 변경, 고정 보정 지시), 선행 `<think>` 제거, `prompt_rejected` 코드 분리, 검증기 v3 인용 정규화. 브랜치 `feat/p1-wp1-model-client`·`-wp2-validation-retry`·`-wp3-citation-normalize`(미병합). 숫자·영문 대조와 hash 결속은 풀지 않는다.
- Qwen용 프롬프트 변경은 정책 v5로 분리하고 v4 결과·Luna 참조는 이력으로 보존한다.
- 추후 OpenAI API 전환은 코드보다 정책 문제다(literal IP allowlist, 64자 revision, 제안요청서 외부 전송 금지 — ADR-0050 완화 항목 참조). 별도 ADR이 필요하다.

## 미결·추적

- rhwp PDF 바이트는 같은 검증 이미지에서 세 표본의 동일 hash를 관측했지만, 이는 해당 표본·이미지에 한정된 증거다. 모든 입력·이미지·환경에 대한 보편적 결정성은 보증하지 않으며, 캐시 정책은 이 범위를 넘겨 가정하지 않는다.
- 암호 문서(`passwordProtected`)와 HML 입력은 범위 밖이며 `needs_human_review`로 남긴다.
- `--backend direct`는 현재 빌드에 없다(native-skia feature 미포함). svg backend만 사용한다.
