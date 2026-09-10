# rhwp R0 격리 기준선

실행일: 2026-09-10 KST
범위: `docs/rhwp-document-pipeline/Plan.md` R0만 수행. migration·DB 쓰기·정책 활성화·
모델 호출·운영 worker 재생성은 수행하지 않았다.

## 입력·바이너리·이미지

- native CLI는 upstream `https://github.com/edwardkim/rhwp`의 정확한 커밋
  `cac9b4f7cc743535cd7c00fe4f286abd67e7145b`, 출력 버전 `rhwp v0.8.6`, 바이너리
  SHA-256 `c82684971756d58ba7391cd08c38c93bb4280ab9ebf0e21c0936574a0084fc8c`다.
- Linux x86_64 ELF 24,469,664 B를 변경 없이 vendor에 복사했다. 빌드 host·toolchain과
  동적 링크 경계는 `vendor/PROVENANCE.md`에 기록했다.
- notice 142는 Plan §3의 object name과 version ID를 그대로 사용해 현재 web 컨테이너의
  MinIO client로 **GET만** 수행했다. DB·객체·컨테이너 설정은 바꾸지 않았다. 두 HWP는
  주 checkout의 기존 untracked 표본을 읽기 전용 입력 디렉터리에 복사했다.
- 입력 크기/SHA-256은 metrics JSON에만 기록했다. 원문, 사용자 파일명, object key,
  자격증명, stderr 본문은 이 기록에 넣지 않았다.
- 검증 이미지는 `bidops-rdp-r0:20260910`, image ID
  `sha256:84f5cd7f2fff935f4d3502c092607ad3a796e494a47041e976369d3ad249655e`,
  linux/amd64, 595,349,142 B다. Docker Engine은 29.7.2였다.
- 이미지 안에서 native CLI mode `0555`, UID:GID `1000:1000`, NanumGothic·
  NanumMyeongjo·NanumGothicCoding 해석을 확인했다. 설치 폰트 바이트 manifest SHA-256은
  `92e5dc4ff6e83ab2008e636169bf0b24df0cb404214af33946a73f010f1650a9`다.

## 실행 경계와 방법

각 표본은 같은 입력 경로에서 두 번만 실행했다. HWP는 `export-hwpx --verify
--verify-pages --json`, `export-pdf`, `export-text`, `dump-pages` 네 호출, HWPX는 변환을
제외한 세 호출이다. probe는 10 ms 간격으로 `/proc`의 rhwp 프로세스 트리 RSS와 컨테이너
PID 수를 읽고, 원문 대신 stdout·산출물의 byte 수와 SHA-256 및 허용 JSON 수치만 남겼다.

```bash
docker build --file web/Dockerfile --tag bidops-rdp-r0:20260910 .
docker run --rm --network none --user 1000:1000 --memory 1g --pids-limit 128 \
  --cap-drop=ALL --security-opt no-new-privileges \
  -v <version-pinned-sample-dir>:/input:ro -v <empty-output-dir>:/out:rw \
  -v "$PWD/scripts/validation/rhwp_r0_probe.py:/probe.py:ro" \
  --workdir /app/web/backend --entrypoint python \
  bidops-rdp-r0:20260910 /probe.py
```

cgroup은 `memory.max=1073741824`, `pids.max=128`이었고 프로세스의 `CapEff=0`,
`NoNewPrivs=1`을 별도 확인했다. 모든 rhwp 자식은 한 PID였으며 probe를 포함한 컨테이너
관측 최대는 4 PID였다.

## 안전 지표 요약

| 표본 | 두 실행 합계 | PDF(쪽·bytes) | 최대 rhwp RSS | 최대 container pids | `dump-pages` stdout | 결정성 |
|---|---:|---:|---:|---:|---:|---|
| notice 142 HWPX | 22.384 / 22.443초 | 79 · 4,829,134 | 162,840 KiB | 4 | 747,110 B | PDF·text·pages 동일 |
| notice 10 RFP HWP | 18.531 / 17.905초 | 53 · 2,874,883 | 160,536 KiB | 4 | 432,607 B | HWPX·PDF·text·pages 동일 |
| notice 10 SOW HWP | 10.281 / 10.418초 | 31 · 1,616,896 | 128,240 KiB | 4 | 221,095 B | HWPX·PDF·text·pages 동일 |

두 HWP의 HWPX verify는 각각 diff 0, 53=53과 31=31이었다. 모든 PDF에서 rhwp
`pageCount`, `renderedCount`, `pdfinfo Pages`가 일치했고 `export-text`는
`omittedCount=0`, `truncated=false`였다. notice 142의 PDF/text 성공 호출 네 건의 stderr는 같은
SHA-256을 가진 877 B/8줄이었으나 원문 유래 가능성 때문에 본문을 열거나 기록하지 않았다.
전체 실행별 시간·RSS·PID·stdout·artifact hash는
[metrics JSON](2026-09-10-rhwp-r0-baseline.metrics.json)에 있다.

## `paraIndex` 근거

upstream `src/document_core/queries/rendering.rs`의 `dump_page_items_json`은 구역별
`paragraphs.get(para_index)`를 사용한다. `fullParagraph`·`partialParagraph`는 본문 문단,
`table`·`partialTable`·`shape`는 그 control의 host 문단 인덱스를 내며 cell paragraph를
독립 item으로 내지 않는다. `extras`도 같은 인덱스 공간이다.

실측도 이를 확인했다.

| 표본 | 변환/원본 HWPX 최상위 문단 | 셀 문단 | dump items 고유 인덱스 | extras 고유 인덱스 | 합집합 |
|---|---:|---:|---:|---:|---:|
| notice 142 | 1,112 | 1,775 | 1,107 | 5 | 1,112(정확히 일치) |
| notice 10 RFP | 709 | 2,060 | 658 | 11 | 669 |
| notice 10 SOW | 351 | 1,158 | 336 | 11 | 347 |

따라서 identity는 `(section, paraIndex)`이고 cell paragraph는 포함하지 않는다. 동시에
HWP 원본 dump 인덱스와 변환 HWPX 구조 ordinal이 같다는 가정은 두 HWP에서 틀렸다.
IR diff 0·페이지 수 일치는 crosswalk 증거가 아니므로 Spec §4에서 자동 LCS·앞 페이지
상속을 제거하고 HWP crosswalk 미정은 `unmapped`로 보존했다.

## 검사와 게이트

```text
pytest test_vendored_sha256_manifest_is_deterministic_and_complete
       test_runtime_image_installs_native_rhwp_and_pinned_fallback_fonts
       test_worker_network_and_command_boundaries_are_explicit -q
... [100%]
3 passed in 0.38s
```

R0의 60초·1 GiB·pids 128·두 실행 byte 결정성·vendor manifest 조건은 통과했다. 그러나
formal gate는 아직 열지 않는다. `dump-pages` stdout이 설계의 256 KiB를 notice 142와 RFP에서
넘고, HWP→HWPX paragraph crosswalk가 미정이기 때문이다. R1 전에 최소 747,110 B를 수용할
명시적 stdout 상한(후보 1 MiB) 또는 bounded file-output 계약을 선택해야 하고, R2 전에
원본 HWP→변환 HWPX의 결정적 paragraph crosswalk를 정의하거나 HWP를 변환 HWPX 기준으로
page dump할 수 있는지 별도 증거로 결정해야 한다.
