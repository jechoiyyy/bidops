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
Chromium에 공유한다. print HTML은 로컬 inline style/data image만 허용하는 CSP를
사용한다.

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

## SVG 선행 결과

완전한 HWP fixture인 `web/backend/tests/fixtures/documents/labor_template.hwp`를
입력으로 다음을 실행했다. 입력은 read-only mount였고 출력 디렉터리는 요청 임시
디렉터리였다.

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
    python -c "from pathlib import Path; from app.deep_review.document_mcp.processor import DocumentProcessor; p=DocumentProcessor(clamav_checker=lambda _: True).process(Path(\"$d/labor_template.hwpx\").read_bytes(), \"application/hwp+zip\", {\"ocr\": False, \"prepare_pdf\": True, \"timeout_seconds\": 45, \"max_output_bytes\": 20*1024*1024}); Path(\"/out/labor_template-exported.pdf\").write_bytes(p.converted_pdf_bytes); print(p.pdf_metadata)"
  '
```

export exit 0, HWPX size `16,786` bytes, member count `11`, and
`Contents/content.hpf` present. PDF preparation also exit 0: 3 physical A4 pages,
`1,145,294` bytes, and page text SHA-256 values
`a5b485d3d33a43b19d1a8b300fa9ab3947fb19d4797f417ae26b9861fdd949a8`,
`3bc2260f50f02f297a00aa598ee59717ff3373ddfc196c54ba6ddaade5db8465`,
`e3d64150a8c8f24ea872b896e41953725efbb32093a0ba4b75c22aa224520497`였다.
HWPX SHA-256은 `fb27256db4058debd0cec62a57137307734f9cc968e1f2fb5ea510c63c7bdd84`다.
HWP 원본은 2페이지이고 export HWPX는 3페이지이므로 이 결과는 정상 HWPX
렌더 경로 통과를 뜻하며, 두 형식의 동일 bytes/page count 증명은 아니다.

이 export PDF를 `application/pdf` 원본 입력 경로로 다시 처리했다. PDF 안의
` obj` marker/regex object count는 `8,593`, legacy 기본 `max_pdf_objects`는
`4,096`이다. 따라서 기본 옵션에서는 `pdf_object_limit`로 차단하고, v4
`prepare_pdf=True`에서만 고정된 bounded `max_pdf_objects=10,000`을 적용한다.
이 한도는 생성 PDF와 PDF 입력 경로에 동일하며, object limit를 Poppler fallback으로
우회하지 않는다. 명시 `max_pdf_objects`가 10,000을 초과하면 invalid options로
거절한다. 한도 10,000에서 PDF 입력은 3 pages, `594.96×841.92` points,
page text SHA가 위 HWPX 결과와 일치했고, `pdftotext` aggregate SHA-256은
`4dc0c28f5ce434935c659ab57febff76ef3492c8f0707d448f76752cc285ba16`였다.

## 실제 PDF 인쇄 결과

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
     'max_output_bytes': 20 * 1024 * 1024},
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
PDF dimensions는 각각 `594.96×841.92` points이며 SVG page 순서와 1:1 대응한다.
페이지 text SHA-256은 순서대로
`f9b5285fc01dfd9cfb57275b541dcd541b347fbe2c5f5d3e0f61f9bf77056a18`,
`407a53d99d5cfad9d23f7563fa3718a8f73d3b900f9a7f044fff1804ef060ade`였다. 한글,
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
`hwp-rhwp-svg-chromium-pdf`, 같은 safe warnings를 반환했다. 현재 worker
`convert_one` scratch result는 `dict(processed)`만 JSON으로 기록하므로
`converted_pdf_bytes`와 `pdf_metadata`는 결과 파일에 포함되지 않는다
(`sidecar_pdf_present_in_result=false`). PDF 파일/metadata를 immutable sidecar로
저장하는 연결은 다음 단계이며, 이 단계에서 성공으로 표시하지 않는다.

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
# 34 passed in 3.65s
.venv/bin/pytest tests/deep_review/test_document_worker_protocol.py -q --tb=short
# 4 passed in 1.00s
.venv/bin/pytest tests/app/test_runtime_contract.py -q --tb=short
# 13 passed in 0.29s
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
다음 단계에서 만든다. 현재 DB revision은 `0019_prespec_page_overview`이며,
연결에 필요한 migration `0020`는 다음 단계 배포 계획에서만 검토한다.

현재 실제 PDF 선행 pass는 `labor_template.hwp`에 한정된다. 완전한 HWPX와 위
RFP의 실제 PDF snapshot, scratch sidecar 영속화, v4 정규 실행은 아직 검증하지
않았다.
