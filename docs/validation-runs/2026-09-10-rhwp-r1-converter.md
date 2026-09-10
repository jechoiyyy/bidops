# rhwp R1 변환기 검증

실행일: 2026-09-10 KST. 범위는 R1 변환기와 직접 영향받은 계약 검사뿐이며 전체 backend
suite, DB·sidecar·서비스·UI, 배포·활성화·모델 호출은 수행하지 않았다.

## 구현·호환 경계

- `ProcessorOptions.renderer`는 `rhwp-canvas-chromium|rhwp-svg-pdf`만 허용한다. 기본값은
  기존 Canvas이므로 기존 caller는 동작이 바뀌지 않고, native 실패도 Canvas로 fallback하지 않는다.
- native HWP는 검증된 변환 HWPX로 기존 stdlib 구조를 만들되 PDF·page text·dump는 원본
  HWP에서 만든다. 원본 HWPX는 archive 안전 검사를 먼저 통과한다. 원본 PDF는 기존 Poppler
  준비 경로를 그대로 사용한다.
- public mapping은 `bidops.document-structure.v1` 그대로다. canonical HWPX bytes, PDF,
  page text, sanitized dump, verify·provenance는 `ProcessedDocument` 속성에만 둔다.
- native 네 JSON stdout은 호출별 1 MiB cap, 모든 호출은 문서 shared deadline과 일반
  CPU/AS/DATA/FSIZE/NOFILE/CORE limiter를 쓴다. `textPreview`는 파싱 직후 제거하고 원문
  page text는 로그가 아니라 out-of-band source artifact로만 유지한다.

## 검사

```text
cd web/backend && /home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest tests/deep_review/test_document_mcp.py -q --tb=short
54 passed in 3.83s

cd web/backend && /home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest tests/deep_review/test_document_mcp.py::test_native_manifests_accept_actual_v086_types_and_strip_preview -q --tb=short
1 passed in 0.12s

cd web/backend && /home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest tests/deep_review/test_document_mcp.py::test_native_manifests_accept_actual_v086_types_and_strip_preview tests/deep_review/test_document_mcp.py::test_native_renderer_requires_explicit_validated_selection -q --tb=short
2 passed in 0.33s

cd web/backend && /home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest tests/deep_review/test_document_mcp.py::test_native_dump_rejects_duplicate_missing_and_out_of_range_page_ids tests/deep_review/test_document_mcp.py::test_native_manifest_rejects_wrong_schema_size_and_magic -q --tb=short
4 passed in 0.12s

cd web/backend && /home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest tests/deep_review/test_document_mcp.py::test_native_artifact_reader_rejects_symlink -q --tb=short
1 passed in 0.13s

cd web/backend && /home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest tests/deep_review/test_document_mcp.py::test_native_page_text_rejects_empty_duplicate_missing_truncated_and_wrong_types tests/deep_review/test_document_mcp.py::test_native_manifests_accept_actual_v086_types_and_strip_preview -q --tb=short
7 passed in 0.04s
```

첫 full focused 실행 뒤에는 변경된 검사만 실행했다. `python3 -m py_compile`로 변경 Python
파일을 확인했고 `git diff --check`도 통과했다. 호스트 venv는 이 worktree에 없어서 주 checkout의
검증 venv를 사용했으며 실행 코드는 이 worktree였다.

실제 검증은 이미지 `bidops-rdp-r0:20260910`(ID는 metrics JSON)에 현재 worktree를 read-only로
bind mount하고 `network none`, non-root 1000:1000, memory 1 GiB, pids 128, cap-drop ALL,
no-new-privileges로 실행했다. 각 processor는 deadline 300초, artifact 64 MiB, PDF object
100,000 한도를 사용했다. 안전한 결과는 [metrics JSON](2026-09-10-rhwp-r1-converter.metrics.json)에 있다.

preflight 첫 표본은 `dump-pages.pageNumber`도 물리 순번이라고 추가로 가정해
`rhwp_manifest_invalid`로 중단됐다. 실제 안전 metadata에서 이 값은 문서 표시 번호라
재시작할 수 있고, Spec §1의 연속 identity는 `pageIndex`뿐이다. 계약을 완화한 것이 아니라
명세 밖의 잘못된 추가 조건을 제거했으며, pageNumber의 integer type 검사는 유지했다. 수정 뒤
보관된 세 R0 manifest를 엄격 parser로 확인하고 세 표본 processor 경로를 통과시켰다.

## 게이트

세 표본은 79·53·31쪽으로 PDF manifest·render count·pdfinfo·page text·dump가 일치했다.
HWP 두 건은 verify diff 0과 53=53·31=31을 만족했고 요구사항 ID 50개 및 알려진 숫자·기간의
page text/구조 양쪽 보존이 확인됐다. 모든 PDF magic, 구조 schema, sanitized dump의
`textPreview` 부재가 확인돼 R1 worker 게이트는 통과했다. R2 정렬·R3 저장 연결과
`displayPage` 화면 병기 결정은 이번 범위 밖이며 coordinator 수락 전에는 다음 단계를 열지 않는다.

## R1 경계 회귀 보강 (2026-09-10)

샘플 재실행·build·서비스 기동은 하지 않고, 이번 리뷰에서 바뀐 parser/options 경계와
직접 영향받은 native seam만 synthetic fixture로 확인했다.

```text
cd web/backend && /home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest tests/deep_review/test_document_mcp.py::test_native_page_text_defaults_missing_top_level_truncated_but_keeps_required_omitted_count tests/deep_review/test_document_mcp.py::test_native_page_text_rejects_lone_unicode_surrogate_safely tests/deep_review/test_document_mcp.py::test_native_renderer_rejects_non_string_selection_without_type_error tests/deep_review/test_document_mcp.py::test_native_dump_drops_endnote_separator_and_rejects_unknown_or_malformed_items tests/deep_review/test_document_mcp.py::test_native_page_text_budget_is_checked_after_display_metadata_enrichment tests/deep_review/test_document_mcp.py::test_native_manifests_accept_actual_v086_types_and_strip_preview tests/deep_review/test_document_mcp.py::test_native_page_text_rejects_empty_duplicate_missing_truncated_and_wrong_types tests/deep_review/test_document_mcp.py::test_native_renderer_requires_explicit_validated_selection -q --tb=short
................                                                         [100%]
16 passed in 0.34s

git diff --check && python3 -m py_compile web/backend/app/deep_review/document_mcp/native.py web/backend/app/deep_review/document_mcp/safety.py web/backend/tests/deep_review/test_document_mcp.py
(no output; exit 0)
```

The fixes now classify non-string renderer options as `invalid_options`, default only an absent
export-text top-level `truncated` to false while requiring `omittedCount`, accept and drop the
pinned `endnoteSeparator` marker while keeping strict paragraph-kind fields, cap page text after
`display_page`/`section` enrichment, and classify lone Unicode surrogates as
`rhwp_manifest_invalid` without exposing encoding details.
