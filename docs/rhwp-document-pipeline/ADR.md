# rhwp 문서 변환 파이프라인 결정 기록

작업명: rhwp-document-pipeline
기준일: 2026-09-10
상태: 진행 중. 이 폴더의 네 문서(ADR·Requirements·Design·Spec)가 이 작업의 정본이며, 작업 중 바뀌거나 추가되는 결정은 여기에 덧붙인다.

관련 정본: [docs/ARCHITECTURE.md](../ARCHITECTURE.md), [ADR-0010 HWPX 분석 정본](../tracking/decisions/0010-hwpx-canonical-input.md), [ADR-0051 deep-review-v2 결정적 부분](../tracking/decisions/0051-deep-review-v2-deterministic-subset.md), [deep-review-v2 §7 HWPX·PDF 처리 방향](../deep-review-v2/document-analysis-design.md), [사전규격 v4 구현 계획](../tracking/prespec-v4-implementation-plan.md).

## 배경 요약

2026-09-09 분석에서 확인한 사실이다.

- 사전규격 첨부는 HWP 95, HWPX 54, PDF 16건(현재 문서 165건)이며 HWP가 과반이다.
- 현재 코드에는 두 변환 계약이 있다. 기본 경로는 HWP를 vendored WASM(rhwp 파생 `claw-hwp` 빌드)으로 HWPX로 바꾼 뒤 stdlib XML 추출기로 문단·표·셀 블록을 만든다. 이 경로의 `page`는 물리 페이지가 아니라 XML 구역 순번이다. v4 경로는 같은 WASM의 Canvas 렌더를 Chromium으로 인쇄해 PDF를 만들고 Poppler로 페이지 텍스트를 뽑는다.
- v4 경로는 Chromium 때문에 실행 비용과 검증 단계가 많다. notice 142(85쪽 HWPX)는 `pids_limit 128`과 출력 예산 20 MiB 때문에 실패했고 2026-09-10에야 준비가 끝났다([findings](../tracking/findings.md)).
- 변환된 HWPX 바이트는 저장되지 않아 재추출·감사가 불가능하고, HWPX 구조와 PDF 페이지는 별도 테이블에 저장돼 서로 연결되지 않는다.
- 모델에는 어느 경로든 텍스트만 들어간다. PDF가 필요한 이유는 근거를 물리 페이지로 가리키는 계약 때문이지 모델 때문이 아니다.

네이티브 rhwp CLI(`edwardkim/rhwp` v0.8.6, Rust)를 2026-09-10 실측했다.

| 항목 | rhwp `export-pdf` (svg backend) | 현재 Canvas+Chromium |
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
| HWPX만 저장, PDF는 요청 시 생성 | 구조 보존 | 쪽 번호 근거와 화면 링크가 매번 새로 만든 PDF에 매여 hash 결속이 깨짐. rhwp PDF 바이트는 결정적일 가능성이 높지만 아직 측정하지 않았다 |

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

## 관련 결정(이 작업 밖, 참조)

- 2026-09-09 Qwen 전환 준비: 검증 실패 1회 재시도(seed 변경, 고정 보정 지시), 선행 `<think>` 제거, `prompt_rejected` 코드 분리, 검증기 v3 인용 정규화. 브랜치 `feat/p1-wp1-model-client`·`-wp2-validation-retry`·`-wp3-citation-normalize`(미병합). 숫자·영문 대조와 hash 결속은 풀지 않는다.
- Qwen용 프롬프트 변경은 정책 v5로 분리하고 v4 결과·Luna 참조는 이력으로 보존한다.
- 추후 OpenAI API 전환은 코드보다 정책 문제다(literal IP allowlist, 64자 revision, `docs/security.md`의 제안요청서 외부 전송 금지). 별도 ADR이 필요하다.

## 미결·추적

- rhwp PDF 바이트의 결정성(같은 입력·폰트·바이너리에서 같은 hash가 나오는지) 미측정. 결정적이면 재변환 캐시 검증이 단순해진다.
- 암호 문서(`passwordProtected`)와 HML 입력은 범위 밖이며 `needs_human_review`로 남긴다.
- `--backend direct`는 현재 빌드에 없다(native-skia feature 미포함). svg backend만 사용한다.
