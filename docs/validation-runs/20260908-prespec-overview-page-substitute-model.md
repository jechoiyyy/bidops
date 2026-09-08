# 사전규격 개요 검토 — 승인 프롬프트 v4, 대체 모델 참조 실행

기준일: 2026-09-08 · `quality_status=unmeasured_reference` · 운영 결과 아님

승인된 vLLM `qwen3.8:27b`를 쓸 수 없는 상태에서, 승인 프롬프트
`prespec-overview-page-review-reference-v4`가 이미 수집된 회차의 실제 사전규격 문서에
어떤 출력을 내는지 화면에서 확인하기 위한 참조 실행이다. **모델 품질 근거·운영 완료·정책
활성화 근거로 쓰지 않는다.**

## 모델 대체 사실

- 실행 모델은 `claude-opus-5`(Claude Code 세션)이며 승인 vLLM 배포가 아니다.
- 정책 사본은 승인 v4 policy에서 `model_name`·`model_endpoint_ref`만 바꿨다. 프롬프트
  바이트는 동일하며, notice 614의 `prompt_sha256`이 2026-09-07 Qwen v4 단일 실행과
  같은 `47de553eddf40320d29d73c59a7ac3fe8c4baf823281b489d4f4fed9f0ae7bc9`로 일치한다.
- `model_digest`는 weight digest가 없어 모델 식별 문자열의 sha256을 넣었고, manifest에
  `model_digest_basis`와 `model_substitution`으로 명시했다.
- 원응답 암호화 저장은 하지 않았다(`raw_response_stored: false`). 전송 계층을 거친 실행이
  아니므로 응답 객체가 없다.

## 입력

2026-09-03~09-07 회차에서 2026-09-07 v3 실행이 동결해 둔 입력 6건을 그대로 썼다.
원문 HWP/HWPX와 참조 변환 PDF의 해시, `document_version_id`, 선택 페이지가 모두 같다.

| notice | 제목 | 검토 페이지 | PDF 총 페이지 |
|---|---|---|---|
| 137 | 국세청 AI 시스템 구축 ISMP 수립 | 4–7 | 174 |
| 143 | 전기통신금융사기 통합대응단 시스템 고도화 감리 | 4–7 | 36 |
| 159 | 2026년 HRD4U 정보시스템 고도화 사업 감리용역 | 3–5 | 37 |
| 171 | 멀티미디어 방송 통합시스템 유지관리 | 3–8 | 86 |
| 610 | 2026년 노후 정보화 인프라 개선 | 4–6 | 62 |
| 614 | RCMS 연계모듈 전환 및 통합 Ezbaro 연계모듈 구축 | 3–6 | 100 |

동결 실행 디렉터리는 `.dryforge/pipeline-20260903-20260907/overview-pdf-v4-claude-6`이며
Git에 넣지 않는다.

## 실행과 결과

```bash
docker compose build web && docker compose run --rm migrate   # 0019_prespec_page_overview 적용
docker compose cp <run-dir> web:/scratch/page-overview-claude-6
docker compose exec -e BIDOPS_DATABASE_URL=<worker> web \
  python -m app.deep_review.cli import-page-overview \
    --run-dir /scratch/page-overview-claude-6 --notice-id <id> --actor jechoi
```

6건 모두 `validation_status=passed`, `evidence_check_status=passed`,
`validator_version=pdf-page-evidence.v2`, `model_calls: 0`. 근거 검사는 참조 PDF에서
`pdftotext`로 추출한 실제 페이지 본문과 대조했다.

2026-09-07 Qwen v4 단일 실행이 614에서 낸 `fact_number_not_on_cited_pages`·
`latin_term_not_on_cited_pages`는 이번 실행에서 나오지 않았다. 원인은 모델 성능이 아니라
문장 끝의 `(PDF n페이지)` 표기를 넣지 않은 것이다. **두 실행의 요약 품질을 비교한 결과가
아니다.**

기존 `prespec_overview_review`(123행, completed 18) · `prespec_overview_attempt`(37) ·
`prespec_overview_result`(19) · `deep_review`(0)는 변하지 않았다.

## 화면 확인

`/pre-specs/<id>` 상세의 "개요 검토 결과" 구역에서 6건을 laptop 1280×800과
desktop 1440×900으로 확인했다. 두 폭 모두 가로 스크롤이 없고, 품질 배지는
"참조 실행 · 품질 미측정", 실행 정보에 `claude-opus-5 ·
prespec-overview-page-review-reference-v4`가 표시된다. 사실 문단마다 "PDF n페이지 ↗"
링크가 붙고 근거 PDF가 열린다.

## 이번 실행에서 고친 결함

`web/backend/app/deep_review/routers/deep_reviews.py`의 근거 PDF 응답이
`object_store(namespaces=(), read_namespaces=("source",))`로 store를 만들어
`read_namespaces`가 `namespaces`의 읽기 전용 변형이라는 계약과 어긋났다. client가 하나도
생성되지 않아 이 endpoint는 항상 `503 pdf_unavailable`이었다. `assets.py`의 기존 방식대로
`namespaces=("source",), read_namespaces=("source",)`로 고쳤고, 이후 614 근거 PDF가
200 · `application/pdf` · 2,133,043 bytes로 원본 참조 PDF 크기와 같게 나온다.
`source`에는 별도 읽기 전용 자격증명이 없어 `structure`와 달리 같은 자격증명을 쓴다.

## 남은 항목

- 권한 실패로 중단된 초기 import 시도 6건이 MinIO `source`·`structure`에 참조되지 않는
  객체를 남겼다. object store에 delete 경로가 없어 그대로 두었다.
- 이 실행 중 `web`을 base compose 파일만으로 재생성하면서 18787 publish가 사라졌다.
  Docker 결함이 아니라 `web`이 internal network에만 붙어 있었기 때문이며, Docker는 internal
  전용 컨테이너의 포트를 publish하지 않고 에러도 내지 않는다. 실측으로 확인했다: internal
  network에 붙인 컨테이너는 `-p`를 줘도 listener가 생기지 않고, non-internal bridge에 붙이면
  즉시 생긴다. `docker-compose.edge.yml` overlay를 추가해 복구했고 절차는 `operations.md`의
  "화면 노출과 edge overlay"에 적었다. 확인 중 임시로 띄웠던 호스트 forward는 더 이상
  필요 없어 내렸다.
