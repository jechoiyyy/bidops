# 사전규격 v4 PDF 선행 검증

기준일: 2026-09-08

이 기록은 PDF 선행 단계의 안전 경계와 실제 worker 조건 검증만 다룬다. 운영
컨테이너 재시작, DB migration 실행, live 모델 호출, commit/push는 수행하지 않았다.
검증 이미지는 운영 이미지와 같은 `web/Dockerfile`에서 `bidops-v4-pdf-verify:local`
태그로 별도 build했으며, 검증 전용 기능 분기는 두지 않았다.

## 변경과 런타임

`web/Dockerfile`에 `chromium`, `chromium-sandbox`, `fonts-noto-cjk`를 추가했다.
`docker-compose.yml`의 `document-worker`에는 `network_mode: none`, `mem_limit: 1g`,
`pids_limit: 128`을 명시했다. worker는 요청별 임시 디렉터리 안에 Chrome
`--user-data-dir` profile을 만들고, HWP/HWPX의 전체 작업 deadline을 rhwp와
Chromium에 공유한다. print HTML은 nonce가 있는 trusted inline module/style,
`wasm-unsafe-eval`, data image만 허용하는 `default-src 'none'` CSP를 사용하며,
원문 bytes는 base64 data로만 전달하고 text-run은 `textContent`로 삽입한다.

이미지 build와 런타임 의존성 확인:

```bash
docker build --progress=plain --tag bidops-v4-pdf-verify:local --file web/Dockerfile .
docker run --rm --network none --user 1000:1000 --memory 1g --pids-limit 128 \
  --entrypoint /bin/sh bidops-v4-pdf-verify:local -lc \
  'id; chromium --version; node --version; fc-match "Noto Sans CJK KR" | head -n 1; command -v pdftotext; command -v pdfinfo'
```

결과: build 성공. image ID `sha256:724dfd6307ddeb827fd255ce56de0c4711a66e9872039a84a128da3051f7744b`,
size `558903452` bytes. runtime은 uid/gid `1000`, Chromium `152.0.7977.82`, Node
`v22.23.2`, `Noto Sans CJK KR`, `/usr/bin/pdftotext`, `/usr/bin/pdfinfo`를 확인했다.

## 과거 SVG adapter 결과 (내용 인수 실패 기록)

완전한 HWP fixture인 `web/backend/tests/fixtures/documents/labor_template.hwp`를
입력으로 Canvas 교정 전 다음을 실행했다. 입력은 read-only mount였고 출력 디렉터리는
요청 임시 디렉터리였다. 이 adapter는 현재 제거됐으며 결과는 historical evidence다.

```bash
docker run --rm --network none --user 1000:1000 --memory 1g --pids-limit 128 \
  --entrypoint /bin/sh \
  -v /home/jechoi/projects/bidops/web/backend/tests/fixtures/documents/labor_template.hwp:/input/labor_template.hwp:ro \
  bidops-v4-pdf-verify:local -lc '
    d=$(mktemp -d); trap "rm -rf \"$d\"" EXIT
    mkdir "$d/pages"
    node /app/web/backend/app/deep_review/document_mcp/vendor/rhwp_render_pages.mjs \
      --input /input/labor_template.hwp --output-dir "$d/pages" \
      --max-pages 512 --max-output-bytes 20971520
  '
```

safe metadata 결과는 schema `bidops.hwp-page-svg.v1`, 2 pages, 두 페이지 크기
`793.7×1122.5`, aggregate SVG `1,319,668` bytes였다. SVG page hash는 순서대로
`533a07b74467decf9baef5a38a0f9c6f75f71228faf568e3d149165c73952b84`,
`952010b9d3c64ea01b41d012bc3bfef3ce067b6784be855ead8b86d49cbdf4dc`다.

기존 parser 전용 최소 `rfp.hwpx`는 `Contents/content.hpf`가 없어 rhwp에서
거절된다. 이를 렌더 가능한 표본으로 위조하지 않았고, 현재 HWPX PDF 통과로
보고하지 않는다. `prepare_pdf=True` HWPX 경로는 rhwp 호출 전에 기존 `validate_zip`
경계를 재사용한다.

## 정상 HWPX export와 PDF 입력 경로

기존 vendored `rhwp_convert.mjs`의 `exportHwpx()`로 같은
`labor_template.hwp`를 정상 HWPX로 export한 뒤, export bytes를 같은 검증
컨테이너의 `DocumentProcessor(..., "application/hwp+zip", prepare_pdf=True)`에
넣었다. 재현 명령의 핵심은 다음과 같다.

```bash
mkdir -p /tmp/bidops-hwpx-verify-new && chmod 0777 /tmp/bidops-hwpx-verify-new
docker run --rm -i --network none --user 1000:1000 --memory 1g --pids-limit 128 \
  --cap-drop=ALL --security-opt no-new-privileges \
  -v /home/jechoi/projects/bidops/web/backend/tests/fixtures/documents/labor_template.hwp:/input/labor_template.hwp:ro \
  -v /tmp/bidops-hwpx-verify-new:/out:rw \
  --entrypoint /bin/sh bidops-v4-pdf-verify:local -lc '
    d=$(mktemp -d /tmp/bidops-hwpx-render.XXXXXX)
    node /app/web/backend/app/deep_review/document_mcp/vendor/rhwp_convert.mjs \
      /input/labor_template.hwp "$d/labor_template.hwpx"
    cp "$d/labor_template.hwpx" /out/labor_template-exported.hwpx
    python -c "from pathlib import Path; from app.deep_review.document_mcp.processor import DocumentProcessor; p=DocumentProcessor(clamav_checker=lambda _: True).process(Path(\"$d/labor_template.hwpx\").read_bytes(), \"application/hwp+zip\", {\"ocr\": False, \"prepare_pdf\": True, \"timeout_seconds\": 45, \"max_pdf_objects\": 10000, \"max_output_bytes\": 20*1024*1024}); Path(\"/out/labor_template-exported.pdf\").write_bytes(p.converted_pdf_bytes); print(p.pdf_metadata)"
  '
```

export exit 0, HWPX size `16,786` bytes, member count `11`, and
`Contents/content.hpf` present. PDF preparation also exit 0: 3 physical A4 pages,
`513,940` bytes, and current Canvas page text SHA-256 values
`e2cb05cfad270f4a41d669dfae0c1c9f40d8141e2448834fbb645d41235c3417`,
`28d2801db1d33e148f2381edafcbf09a5056b8ae7b57a18ba77d4326b4005d0d`,
`8160165f2cb7473d6ef9057954cf87d40812a049b392831609ee85271211947e`였다.
HWPX SHA-256은 `fb27256db4058debd0cec62a57137307734f9cc968e1f2fb5ea510c63c7bdd84`다.
HWP 원본은 2페이지이고 export HWPX는 3페이지이므로 이 결과는 정상 HWPX
렌더 경로 통과를 뜻하며, 두 형식의 동일 bytes/page count 증명은 아니다.

이 export PDF를 `application/pdf` 원본 입력 경로로 다시 처리했다. PDF 안의
` obj` marker/regex object count는 `679`, legacy 기본 `max_pdf_objects`는
`4,096`이다. 따라서 기본 옵션에서는 `pdf_object_limit`로 차단한다. 이번
검증과 향후 v4 고정 입력 설정은 생성 PDF와 PDF 입력 경로 모두에
`prepare_pdf=True, max_pdf_objects=10,000`을 명시한다. `ProcessorOptions`는
`prepare_pdf` 여부로 기본값을 자동 상향하거나 별도 10,000 상한을 만들지 않고,
기존 `1..100,000` 범위를 그대로 검증한다. object limit를 Poppler fallback으로
우회하지 않는다. 한도 10,000에서 PDF 입력은 3 pages, `594.96×841.92` points,
page text SHA가 위 HWPX 결과와 일치했고, `pdftotext` aggregate SHA-256은
`b320f20c3343763b12ed9360ea39679a3c96fdba274d7dbec811aa848a17d4a9`였다.

## 과거 SVG 실제 PDF 인쇄 결과

다음 명령은 현재 image, `network none`, non-root, memory/pids cgroup, 모든 capability
drop, `no-new-privileges` 조건에서 `DocumentProcessor.prepare_pdf=True`를 실행했다.
`ocr=False`, `timeout_seconds=30`, `max_output_bytes=20 MiB`를 요청했고, 생성물은
`/tmp/bidops-pdf-verify/labor_template.pdf`에 복사했다.

```bash
rm -rf /tmp/bidops-pdf-verify && mkdir -m 0777 /tmp/bidops-pdf-verify
docker run --rm -i --network none --user 1000:1000 --memory 1g --pids-limit 128 \
  --cap-drop=ALL --security-opt no-new-privileges \
  -v /home/jechoi/projects/bidops/web/backend/tests/fixtures/documents/labor_template.hwp:/input/labor_template.hwp:ro \
  -v /tmp/bidops-pdf-verify:/out:rw \
  --entrypoint /usr/local/bin/python bidops-v4-pdf-verify:local - <<'PY'
from pathlib import Path
from app.deep_review.document_mcp.processor import DocumentProcessor

source = Path('/input/labor_template.hwp').read_bytes()
processed = DocumentProcessor(clamav_checker=lambda _content: True).process(
    source,
    'application/x-hwp',
    {'ocr': False, 'prepare_pdf': True, 'timeout_seconds': 30,
     'max_pdf_objects': 10_000, 'max_output_bytes': 20 * 1024 * 1024},
)
pdf = processed.converted_pdf_bytes
assert isinstance(pdf, bytes) and pdf
Path('/out/labor_template.pdf').write_bytes(pdf)
print({
    'pdf_bytes': len(pdf),
    'pdf_metadata': processed.pdf_metadata,
    'warnings': processed.get('warnings', []),
    'extractor': processed.get('extractor'),
})
PY
docker run --rm --network none --user 1000:1000 --memory 1g --pids-limit 128 \
  -v /tmp/bidops-pdf-verify:/out:ro --entrypoint /bin/sh bidops-v4-pdf-verify:local -lc \
  'pdfinfo /out/labor_template.pdf; pdftotext -layout -enc UTF-8 /out/labor_template.pdf -; sha256sum /out/labor_template.pdf'
```

결과는 exit 0, PDF `1,188,616` bytes, physical page count `2`였다. 두 페이지의
PDF dimensions는 각각 `594.96×841.92` points이며 Canvas page 순서와 1:1 대응한다.
이 HWP 실행은 Canvas 교정 전 기록이며, 현재 교정 경로는 아래 Canvas 결과 절에서
별도로 검증했다. 한글,
금액/숫자, 표 형태의 layout text가 각 페이지에서 확인됐고 PDF parser가 계산한
text hash와 page-wise `pdftotext` hash가 일치했다. safe warnings는
`pdf_poppler_fallback`, `pdf_stdlib_text_fallback`이며 원문 stderr는 기록하지
않았다.

PDF bytes SHA-256은 Chromium의 실행 시각 metadata 때문에 실행마다 달라질 수
있다. 이 실행의 hash는 `3d0ee8a5129d6a3228744aa4ce12f26ca4f2a56821eee07f5c7ed049bd6cfb3a`;
root 독립 실행은 `35c590b019ab352da18f5a3179c7121f703a7b77e9706251097a4e00eafe8090`였다.
따라서 이번 단계의 증거는 PDF byte equality가 아니라 원본/config hash, physical
page count, page dimensions, page text hash의 대응이다.

동일 조건으로 `python -m app.deep_review.workers.document --once`도 실행했다.
worker는 exit 0, 상태 `succeeded`, structure page_count `2`, extractor
`hwp-rhwp-svg-chromium-pdf`, 같은 safe warnings를 반환했다. 이 worker 결과는
Canvas 교정 전 기록이며 현재 extractor는 `hwp-rhwp-canvas-chromium-pdf`다. 현재 worker
`convert_one` scratch result는 `dict(processed)`만 JSON으로 기록하므로
`converted_pdf_bytes`와 `pdf_metadata`는 결과 파일에 포함되지 않는다
(`sidecar_pdf_present_in_result=false`). PDF 파일/metadata를 immutable sidecar로
저장하는 연결은 다음 단계이며, 이 단계에서 성공으로 표시하지 않는다.

## Canvas renderer 교정 결과

구형 `rhwp_render_pages.mjs`와 SVG 인쇄는 필수 RFP p5 파란 표의 글자를
누락했으므로 삭제했다. 새 `rhwp_render_canvas.mjs`는 같은 vendored WASM으로
페이지 수·geometry만 bounded JSON으로 확인하고, 실제 렌더는 기존 Chromium의
trusted inline module에서 `initSync`·`renderPageToCanvas(index, canvas, 1)`를
사용한다. 각 페이지에서 render 직후 `getPageTextLayout`을 호출하고, runs의
좌표·글꼴·크기·비율을 검증한 뒤 `textContent`와 `color: transparent` CSS로
검색 가능한 text layer를 만든다. `document.title`은 모든 Canvas/layout/CSP/HTML
검사가 끝난 뒤에만 고정 receipt
`bidops-hwp-canvas-render-complete-v1`로 설정하며, Python은 PDF metadata receipt가
없으면 결과를 거절한다. receipt `pdfinfo` 확인과 생성 PDF의 Poppler text 검사는
최초 HWP/HWPX deadline의 남은 시간만 사용한다. OCR, XML 보정, LLM 보정, 문서별
CSS 보정은 사용하지 않았다.

필수 RFP 재현 명령은 다음과 같다. source는 기존 MinIO version을 복사한 read-only
mount이고, 검증 image는 `network none`, UID 1000, memory 1g, pids 128,
`cap-drop=ALL`, `no-new-privileges`였다.

```bash
OUT_DIR=$(mktemp -d /tmp/bidops-v4-canvas-required-final.XXXXXX)
chmod 0777 "$OUT_DIR"
docker run --rm -i --network none --user 1000:1000 --memory 1g --pids-limit 128 \
  --cap-drop=ALL --security-opt no-new-privileges \
  -v /home/jechoi/projects/bidops:/app:ro \
  -v /tmp/bidops-v4-required-sample.h0vd7q/source.hwpx:/input/source.hwpx:ro \
  -v "$OUT_DIR:/out:rw" --workdir /app/web/backend \
  --entrypoint /usr/local/bin/python bidops-v4-pdf-verify:local - <<'PY'
from pathlib import Path
from app.deep_review.document_mcp.processor import DocumentProcessor
source = Path('/input/source.hwpx').read_bytes()
processed = DocumentProcessor(clamav_checker=lambda _: True).process(
    source, 'application/hwp+zip',
    {'prepare_pdf': True, 'ocr': False, 'timeout_seconds': 300,
     'max_pdf_objects': 100000, 'max_output_bytes': 100 * 1024 * 1024},
)
Path('/out/required-canvas.pdf').write_bytes(processed.converted_pdf_bytes)
print(processed.pdf_metadata)
PY
pdfinfo "$OUT_DIR/required-canvas.pdf"
pdftotext -layout -enc UTF-8 "$OUT_DIR/required-canvas.pdf" "$OUT_DIR/required-canvas.txt"
sha256sum "$OUT_DIR/required-canvas.pdf" "$OUT_DIR/required-canvas.txt"
```

실행 결과: source `840,114` bytes, SHA-256
`7cc3b5f3894d984ce641e9462030990cbb4cfc1d6869b18bc9047899a23f4665`, PDF
`11,041,060` bytes, 85 physical A4 pages, object marker `9,009`, PDF SHA-256
`77fa66fca472a89f2b6a1608602eb6afb0be802068e62998dfec007f539f0010`, 전체
`pdftotext -layout -enc UTF-8` SHA-256
`e58ab1e90fd216005d283417e11991eab177300e2f0f4ed3afbdd0dc837328ef`였다.
모든 페이지 metadata에 page text SHA가 있으며 p4/p5/p7/p8은 각각
`1341d004a455f588072d927ace04c7e2f3f0e00d9d5588075539f0f9b89c519b`,
`f60031f723e7b37f591b08e0672531fa1c32f9095ff3bba3def1797e5e0143c6`,
`4429fb415771843f6024c075746bb4e080070af22b11f6b276fac3b190f8db36`,
`4f26f56c7461f4173aac260f752648b29d6252bfb2f6d643ff63376917d3ab9b`이다.

페이지별 내용 인수도 통과했다. p4 text에는 `298,735,350원`, `365일`, `189MD`,
p5에는 `13,225,835,150원`, `12개월`, `사업개요`, p7~8에는 `감리 방법`,
`감리 과업내용`, `제안 시 고려사항`이 있다. `pdftoppm -f 4 -l 5 -png -r 96`
결과 `/tmp/bidops-v4-canvas-final-pages-vsaucatl/page-04.png`와
`page-05.png`를 눈으로 확인했고, p5 파란 표 안에 사업명·사업비·기간과 하위
문장이 실제로 표시됐다. p4의 감리 예산·기간·투입공수 표도 표시됐다. 이 결과는
이전 SVG PDF `ca77c043...`와 bytes equality를 요구하지 않으며, 원문에 없는
텍스트를 덧붙이지 않았다.

현재 renderer 관련 결과는 `rhwp-canvas-chromium-pdf`와 safe warnings
`pdf_poppler_fallback`, `pdf_stdlib_text_fallback`이다. sidecar 전달 계약은
그대로 사용 가능하지만 실표본 PDF를 DB/MinIO immutable snapshot으로 저장하거나
v4 runner/UI/model에 연결한 것은 아니며, 그 작업은 다음 단계다.

## 장애 진단과 안전 수정

초기 검증 image에서 Chromium은 restricted namespace에서 sandbox/crashpad를
시작하지 못했다. root namespace나 privileged 실행은 사용하지 않고, outer
container의 non-root/network-none/cgroup 경계를 유지한 채 Chromium child에만
`--no-sandbox`를 적용했다. Chromium은 mmap-backed renderer 때문에 기존
`RLIMIT_DATA=512 MiB`와 낮은 file-size limit에서 abort하거나 PDF를 만들지
않았다. Chromium child는 `RLIMIT_DATA`/`RLIMIT_AS`를 별도로 걸지 않고 worker
cgroup을 메모리 경계로 사용하며, intermediate file limit만 `max_output_bytes`
의 bounded 4배로 둔다. Node/rhwp child에는 기존 finite resource limits를
유지한다. timeout을 늘리거나 profile 옵션을 제거하지 않았다.

## 관련 검사

실행한 집중 검사는 다음과 같다.

```bash
cd web/backend
.venv/bin/pytest tests/deep_review/test_document_mcp.py -q --tb=short
# 38 passed (Canvas CSP/text-layer/exact-receipt and object-budget regression)
.venv/bin/pytest tests/deep_review/test_document_worker_protocol.py -q --tb=short
# 14 passed
.venv/bin/pytest tests/app/test_runtime_contract.py -q --tb=short
# 13 passed in 0.29s
.venv/bin/pytest tests/deep_review/test_document_mcp.py \
  tests/deep_review/test_document_worker_protocol.py \
  tests/app/test_runtime_contract.py -q --tb=short
# 65 passed in 4.79s
.venv/bin/pytest tests/deep_review/test_document_mcp.py::test_vendored_sha256_manifest_is_deterministic_and_complete -q --tb=short
# 1 passed in 0.04s
.venv/bin/python -m compileall -q app/deep_review/document_mcp app/deep_review/document_protocol.py \
  app/deep_review/services/document_converter.py app/deep_review/services/prespec_attachments.py
cd ../..
docker compose -f docker-compose.yml config --quiet
git diff --check
```

앞선 bounded 실행의 정확한 기준선 명령은 다음과 같고 `116 passed, 5 skipped,
3 warnings`로 보고됐다. 이 단계에서 archive-boundary 회귀 1개가 추가되어 같은
명령을 무관하게 전체 반복하지 않았다.

```bash
cd web/backend && .venv/bin/python -m pytest \
  tests/deep_review/test_document_mcp.py \
  tests/deep_review/test_document_worker_protocol.py \
  tests/deep_review/test_document_integrity.py \
  tests/deep_review/test_document_segments.py \
  tests/deep_review/test_prespec_attachment_assets.py \
  tests/deep_review/test_prespec_e2e.py \
  tests/app/test_runtime_contract.py -q --tb=short
# 116 passed, 5 skipped, 3 warnings
```

정확한 current focused 결과는 위에 기록했다. root 독립 회귀 기준선은 다음과
같았다.

```bash
cd web/backend && .venv/bin/python -m pytest tests/deep_review/test_document_mcp.py -q --tb=short
# 33 passed in 3.07s
```

## 실표본과 남은 범위

read-only로 확인된 다음 실표본을 snapshot 단계 입력으로 보존한다: notice id
`142`, notice key `pre:R26BD00271191`, RFP `별첨.제안요청서.hwpx`, document version
`59cbc6ef-53f5-421d-84d0-d97c9185ac09`, SHA-256
`7cc3b5f3894d984ce641e9462030990cbb4cfc1d6869b18bc9047899a23f4665`, 상태
`safe/current`, 기존 extractor `hwpx-stdlib`, page_count `1`. 같은 묶음의
`붙임.구매규격 사전공개(안).hwp`도 별도 원본으로 남긴다. 기존 `document_structure`
를 PDF page 구조로 덮어쓰지 않고, 새 immutable PDF snapshot과 sidecar 연결을
다음 단계에서 만든다. 현재 DB revision은 `0019_prespec_page_overview`이고
`0020_prespec_company_fit` 회사 핏 migration은 이미 존재한다. snapshot 연결에
필요한 추가 migration은 다음 단계 배포 계획에서 검토한다.

## scratch PDF sidecar 계약 결과

`prepare_pdf=True` 요청은 `bidops.document-converter-request.v2`로 구분하고,
worker는 `pdf/<request_uuid>.pdf`를 원자적으로 완료한 뒤
`bidops.document-converter-result.v2` metadata를 publish한다. JSON에는 PDF bytes를
넣지 않으며 sidecar metadata의 filename·byte count·SHA-256·기존 `pdf_metadata`를
결속한다. consumer는 bounded stat/read, UUID namespace, no-symlink, hash/media 검사와
trusted-side exact-byte ClamAV 재검사를 통과한 뒤 `ProcessedDocument`의
`converted_pdf_bytes`/`pdf_metadata`로 복원한다. 성공 소비·오류·timeout cleanup은
request 소유 파일만 대상으로 하고, claimed 입력은 worker가 끝내기 전에 삭제하지 않는다.
원본 PDF는 request MIME가 아니라 structure의 검증된 `media_type=application/pdf`로
판별하며, sidecar bytes와 입력 bytes/hash가 exact match여야 한다. 원본의 metadata는
빈 object를 허용하지 않고 physical page count와 페이지별 normalized text SHA-256을
structure와 대조한다.

관련 검사:

```bash
cd web/backend
.venv/bin/pytest tests/deep_review/test_document_worker_protocol.py -q --tb=short
# 14 passed
.venv/bin/python -m compileall -q app/deep_review/document_protocol.py app/deep_review/services/document_converter.py
```

## v4 snapshot·입력 manifest isolated roundtrip

이번 bounded 단계에서는 운영 PostgreSQL/MinIO에 쓰지 않고 기존 filesystem
object-store 경계와 scratch consumer를 격리하여 다음 경로를 검사했다.

`DocumentVersion(current,safe) → ScratchDocumentProcessor → exact PDF scan/hash →
source namespace PDF + structure namespace full-page-text JSON → immutable snapshot
reuse-before-conversion → heading substring manifest → prepared input identity` 순서다.
full page text는 `bidops.prespec-v4-page-text.v1` JSON의 모든 page text와 SHA-256을
별도 versioned `ContentObject/ContentObjectLocation`으로 저장하고, 선택 manifest의
`pages[].text`에는 선택 범위의 정확한 substring만 넣는다. 생성 PDF는 기존 PDF
다운로드 계약과 같은 `source` namespace에 남기고, structure namespace에는 page text와
선택 manifest만 둔다. renderer/font에는 실제 worker runtime·Chromium·font asset
fingerprint를, 배포 image digest가 선언된 경우에만 그 digest를 함께 넣고, config에는
`ProcessorOptions.from_mapping`의 확정 options를 넣어 변환
전에 같은 binding snapshot을 재사용한다. SQL `NULL` unique에 기대지 않고 canonical
identity SHA-256으로 explicit sample 중복도 막는다. 이 row는 정책 적용 대상이나
model attempt가 아니라 준비 완료 input record다.

```bash
cd web/backend
.venv/bin/pytest tests/deep_review/test_prespec_v4_preparation.py -q --tb=short
# 5 passed in 1.80s
.venv/bin/pytest tests/app/test_models.py tests/app/test_mapper_isolation.py \
  tests/app/test_deep_review_migrations.py -q --tb=short
# 26 passed in 8.77s
.venv/bin/python -m compileall -q \
  app/deep_review/models.py app/deep_review/services/prespec_v4.py \
  alembic/versions/0021_prespec_v4_pdf_contract.py
```

실제 Poppler 구조를 DB에 쓰지 않고 selector에 넣은 경계 회귀도 통과했다. notice
142는 p3 `Ⅰ. 감리 개요`부터 p13 `Ⅱ. 제안요청 사항` 직전까지이며 p13 앞장
연속문장을 포함하고 다음 장 제목/목차 잔여를 제외한다. 개발 HWP notice 35는
p4–8에서 `과제보고`를 포함하고 `Ⅱ 과업수행 지침`을 경계로 제외한다. 운영 PDF
notice 59는 p3–5에서 `Ⅱ 과업 내용 > 1. 과업 주요내용`을 포함하고 p6
`2. 세부 과업내용` 직전에서 멈춘다. p12 표의 월 배치는 추정하지 않는다.

운영 migration `0021_prespec_v4_pdf_contract`, 실제 MinIO object version과 snapshot
row, v4 runner/attempt, model/UI 인수는 아직 실행하지 않았다. 기존 legacy
`DocumentStructure`·개요·리뷰는 변경하지 않았다.

## snapshot/cache 및 PostgreSQL 제약 focused 검증

추가 구현은 caller가 제공한 provenance dict만으로 worker를 신뢰하지 않도록 generated
PDF metadata의 실제 vendored runtime·Canvas adapter·processor/CSS, Chromium binary
및 font 파일 바이트 manifest를 대조한다. 배포가 실제 image digest를 선언하지 않으면
`worker_image_digest=null`로 남기고 자산 hash를 image digest로 사용하지 않는다. 원본
PDF sidecar는 `rerendered=false`, 실제 Poppler/stdlib extractor provenance와
`font_provenance=null`을 보존한다. snapshot cache hit는 source/PDF/page-text를 저장된 object
version·etag·size·SHA-256으로 다시 읽고, 최신 `ContentScan` 행이 `clean`인지 확인한다.
더 최신 `infected`/`unavailable` 행은 이전 clean 결과를 재사용하지 않는다. Compose
`document-worker`에는 검증 컨테이너와 같은 `mem_limit: 1g`, `pids_limit: 128`,
`cap_drop: [ALL]`, `no-new-privileges:true`를 기록했다.

```bash
cd web/backend
.venv/bin/pytest tests/deep_review/test_document_mcp.py -q --tb=short
# 41 passed
.venv/bin/pytest tests/deep_review/test_document_worker_protocol.py -q --tb=short
# 14 passed in 1.57s
.venv/bin/pytest tests/deep_review/test_prespec_v4_preparation.py -q --tb=short
# 5 passed in 1.80s
.venv/bin/python -m compileall -q app/deep_review app/core \
  tests/deep_review/test_prespec_v4_preparation.py \
  tests/deep_review/test_prespec_v4_postgres.py
```

provenance 교정 뒤 동일 범위의 마지막 focused 묶음은 다음과 같이 `73 passed`였다.

```bash
.venv/bin/pytest tests/deep_review/test_document_mcp.py \
  tests/deep_review/test_document_worker_protocol.py \
  tests/deep_review/test_prespec_v4_preparation.py \
  tests/app/test_runtime_contract.py -q --tb=short
# 73 passed in 6.50s
```

임시 PostgreSQL 17 컨테이너는 `tests/postgres.py`의
`temporary_postgres_server()`로 만들고 `BIDOPS_TEST_POSTGRES_URL`을 pytest
subprocess에만 전달했다. 운영 URL·DB·MinIO에는 연결하지 않았다.

```bash
.venv/bin/pytest tests/deep_review/test_prespec_v4_postgres.py -q --tb=short
# 1 passed in 3.65s
.venv/bin/pytest \
  tests/app/test_db_migrations.py::test_migration_records_a_deterministic_audit_marker \
  tests/app/test_db_migrations.py::test_downgrade_removes_only_the_screening_runtime \
  tests/app/test_db_migrations.py::test_0018_round_trips_between_the_segment_schema_and_0017 \
  tests/app/test_db_migrations.py::test_0018_downgrade_refuses_to_discard_priority_grade_or_segment_rows \
  tests/app/test_db_migrations.py::test_0018_downgrade_refuses_to_discard_an_unmeasured_completed_attempt \
  -q --tb=short
# 5 passed in 21.48s
```

실제 원본 PDF passthrough도 v2 sidecar 경계에서 확인했다. read-only PDF59
(`sha256=fda9d3e…`, 1,155,772 bytes)를 `media_type=application/octet-stream`,
`prepare_pdf=true`, `max_pdf_objects=10000`, `max_output_bytes=20MiB`,
`timeout_seconds=300`으로 격리 `convert_one`에 넣어 `84` physical pages의
`source_kind=original` sidecar가 성공했다. sidecar metadata는
`rerendered=false`, `font_provenance=null`, `bidops.pdf-text-provenance.v1`,
`pdf-poppler-prepared`, `pdfinfo`/`pdftotext` 실제 binary hash를 포함했고 입력 PDF
bytes를 재렌더하지 않았다. processor provenance hash는 실행 worker의
`processor.py` bytes를 가리키며, 이름/version만으로 parser identity를 대표하지
않는다. temporary scratch만 사용했고 운영 DB/MinIO에는 쓰지 않았다.

같은 실제 PDF59의 sidecar provenance를 source-PDF snapshot binding으로 넘긴
filesystem/SQLite 격리 roundtrip도 확인했다. snapshot은 `source_kind=original`,
84 physical pages, `font_jsonb.font_provenance=null`로 저장됐고 같은 source/config/
processor·Poppler provenance 두 번째 호출은 동일 snapshot을 반환하며 converter
호출 횟수는 1회였다. 이 검사는 운영 DB/MinIO가 아닌 임시 저장소에서 수행했다.

이 검증은 0021 실제 upgrade와 v4 snapshot의 FK, duplicate identity,
append-only trigger 및 audit marker를 확인한다. 운영 migration 적용·snapshot row
생성, MinIO version 저장, v4 runner/attempt/model/UI 인수는 여전히 미완료다.

현재 실제 PDF 선행 pass는 `labor_template.hwp`, vendored export HWPX, export PDF의
`application/pdf` 입력 경로, 그리고 Canvas 교정 후 필수 RFP 전체 내용까지다. 이전
SVG 실행은 p5 `3. 감리대상 사업 > □ 사업개요` 파란 상자가 비어 내용 인수에
실패했지만, Canvas 실행은 같은 표의 사업명·사업비·기간을 시각/텍스트로 보존했다.
실표본 RFP의 운영 DB·MinIO snapshot row와 v4 runner 정규 실행은 아직 검증하지
않았다. PDF59는 sidecar와 격리 snapshot roundtrip까지만 확인했다.
