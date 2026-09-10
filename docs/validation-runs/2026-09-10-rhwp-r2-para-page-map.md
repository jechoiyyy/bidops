# rhwp R2 문단·페이지 대응표 검증

2026-09-10 KST. `41eaef5`에서 시작한 `feat/rdp-r2-para-page-map`,
worktree `/home/jechoi/orca/workspaces/bidops/rdp-r2-para-page-map`에서 직접 구현했다.
R2 범위는 정렬기·계약 검증·native processor 산출물 연결이다. DB·scratch sidecar·REST·UI
저장 연결은 R3 이후이며, 미커밋·미병합 상태다.

## 구현과 검증 경계

- 기존 구조 JSON·block_key·page·text는 유지한다. extractor가 같은 XML 순회에서 별도
  identity를 만든다. `content.hpf`의 구역 manifest·spine 순서와 직접 자식 `p`를 사용하고,
  dump의 구역별 전체 인덱스 집합과 source 집합이 일치해야 exact 대응을 연다.
- pinned upstream `cac9b4f7c`의 `src/parser/hwpx/content.rs:99`,
  `src/parser/hwpx/mod.rs:493`, `src/parser/hwpx/section.rs:64`를 확인했다.
  extractor의 중첩 문단·구역 정렬이 본문 ordinal과 다를 수 있는 경우를 synthetic fixture로 검사했다.
- HWP paragraph·모든 table_cell은 FULL text가 한 페이지에 한 번 나타나는 경우만 연결한다.
  겹치는 occurrence도 중복으로 처리한다. 빈 블록·불일치·중복·페이지 걸침을 추정 보정하지 않는다.
- 대응표는 닫힌 schema, 페이지 범위, section·para_index, 전체 블록 분할, 집계, 출력 상한과
  shared deadline을 검사한다. `ProcessedDocument` 속성에만 두므로 기존 JSON에는 섞이지 않는다.

## 관련 검사

```bash
cd /home/jechoi/orca/workspaces/bidops/rdp-r2-para-page-map/web/backend
/home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest \
  tests/deep_review/test_para_page_map.py tests/deep_review/test_document_mcp.py -q --tb=short
# 135 passed in 3.77s
```

그 뒤 명시적 ProcessorOptions의 page/block 상한 전달, native 결과의 필수 속성 조회,
동일 개수·다른 인덱스와 XML 특이 구조 회귀를 보강했다. 변경된 경로만 다시 검사했다.

```bash
/home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest \
  tests/deep_review/test_para_page_map.py tests/deep_review/test_document_mcp.py \
  -k 'para_page_map or native or hwpx' -q --tb=short
# 101 passed, 38 deselected in 0.87s
```

## 세 표본 실측

R0의 고정 입력 사본을 읽기 전용으로 마운트하고, R0 이미지에 이번 worktree를 읽기 전용으로
덮어 실제 `DocumentProcessor`를 표본마다 한 번 실행했다. 이어서 그 실행의 HWPX·sanitized
dump·page text로 구조 추출·정렬을 새로 수행해 두 대응표의 바이트를 비교했다. PDF를 두 번
렌더한 실험이 아니며 PDF 결정성의 추가 근거로 사용하지 않는다.

```bash
mkdir -p /tmp/bidops-rhwp-r2-20260910
docker run --rm --network none --user 1000:1000 --memory 1g --pids-limit 128 \
  --cap-drop=ALL --security-opt no-new-privileges \
  -v /home/jechoi/orca/workspaces/bidops/rdp-r2-para-page-map:/app:ro \
  -v /tmp/bidops-rhwp-r0-task38/input:/input:ro \
  -v /tmp/bidops-rhwp-r2-20260910:/out:rw \
  --workdir /app/web/backend --entrypoint /usr/local/bin/python \
  bidops-rdp-r0:20260910 /app/scripts/validation/rhwp_r2_probe.py
```

원본 사본이 없으면 [R0의 표본 취득·검증 기록](2026-09-10-rhwp-r0-baseline.md)과
[계획의 고정 object version](../rhwp-document-pipeline/Plan.md#3-자주-쓰는-명령)을 따른다.
`/input` 파일명은 `notice-142.hwpx`, `notice-10-rfp.hwp`, `notice-10-sow.hwp`다.
원문 hash, 이미지 ID, 옵션·격리 조건, 대응표 hash는 [안전 지표](2026-09-10-rhwp-r2-para-page-map.metrics.json)에 있다.
산출물 전문·첨부·페이지 텍스트는 이 기록에 저장하지 않았다. 별도 ClamAV 판정은 수행하지
않았으므로 이 변환 검사를 운영 clean 판정으로 취급하지 않는다.

| 표본 | PDF 쪽 | mapped / 전체 블록 | 매핑률 | exact / page_text | 대응표 크기 | 처리 시간 |
|---|---:|---:|---:|---:|---:|---:|
| notice 142 HWPX | 79 | 940 / 2,561 | 36.70% | 760 / 180 | 227,837 B | 23.161초 |
| notice 10 제안요청서 HWP | 53 | 481 / 2,493 | 19.29% | 0 / 481 | 149,705 B | 20.697초 |
| notice 10 과업지시서 HWP | 31 | 209 / 1,353 | 15.45% | 0 / 209 | 74,203 B | 12.486초 |

세 표본 모두 대응표 재생성 바이트 동일, 기존 구조 블록 동일, 원본 불변, 미매핑을 포함한
문서 처리 성공을 확인했다. 재추출·정렬 시간은 각각 0.177·0.199·0.099초였다.
HWPX의 비어 있지 않은 본문 문단은 760개 모두 exact로 연결됐다. 매핑률 분모에는 빈 문단,
빈 표 control, 빈 셀도 포함한다. HWP의 낮은 매핑률은 ordinal을 추정하지 않는 승인된
보수적 규칙의 결과이며, 매핑률 임계값이나 모델 품질 판정으로 사용하지 않는다.

실측 이후 필수 속성 조회 보강은 위 native seam 회귀로 확인했으며 재변환은 반복하지 않았다.
`git diff --check`를 확인했다. 전체 backend·화면 검사, 이미지 재빌드, 운영 DB·객체 저장,
배포·활성화·모델 호출은 수행하지 않았다. R2 구현 게이트는 충족했으며 다음 단계는 계획의
단계 검토 뒤에 연다.
