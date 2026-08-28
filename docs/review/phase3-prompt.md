# 3단계 착수 프롬프트 (cold session용)

아래 블록 전체를 새 세션 첫 메시지로 붙여넣는다.

---

BidOps 개발 3단계를 진행한다. 0~2단계는 이미 끝났고 커밋되지 않은 채 작업 트리에 있다.

## 먼저 읽을 것

이 순서로 읽고 시작한다.

1. `CLAUDE.md` — 최상위 불변 조건과 문제 보고 경로
2. `docs/review/phase0-2/plan.md` — 0~2단계에서 무엇을 왜 했는지, 실행 결과
3. `docs/review/phase0-2/spec.md` — 작업 명세를 어느 정도 해상도로 쓰는지 (3단계 명세의 본보기)
4. `docs/review/2026-08-27-web-review.md` — 코드 리뷰 원본. 3단계는 여기 BLOCKER 2다
5. `docs/review/workflow-io-map.md` — 단계 B의 입출력과 끊어진 연결
6. `docs/business-rules.md` — 등급·준비 상태·심층 검토 단계 규칙
7. `docs/contracts.md` — REST 응답 계약
8. `docs/security.md` — 첨부 업로드·격리·외부 전송 경계
9. `web/frontend/AGENTS.md`, `web/backend/AGENTS.md`

## 3단계 목표

**브라우저만으로 공고 → 문서 번들 준비 → 심층 검토 → 최종 의견까지 도달한다.**

지금은 백엔드 엔드포인트가 다 있는데 프런트엔드에 대응 함수가 없어서, 심층 검토를
시작하려면 curl이나 CLI를 써야 한다. `NoticeDetailPage`는 "문서 준비가 완료된 ready
bundle이 있어야 심층 검토를 시작할 수 있습니다"만 띄우고, 그 bundle을 만들 UI가 없다.

### 이미 있는 백엔드 (구현 불필요, 연결만)

`web/backend/app/routers/document_bundles.py`

| 메서드 | 경로 |
|---|---|
| GET | `/notices/{notice_id}/document-bundles` |
| POST | `/notices/{notice_id}/document-bundles` |
| POST | `/document-bundles/{bundle_id}/documents` |
| PATCH | `/document-versions/{document_version_id}` |
| POST | `/document-bundles/{bundle_id}/confirm` |
| GET | `/document-structures/{structure_id}` |
| GET | `/document-structures/{structure_id}/pages/{page}` |

`web/backend/app/routers/deep_reviews.py`

| 메서드 | 경로 |
|---|---|
| POST | `/notices/{notice_id}/deep-reviews` |
| GET | `/deep-reviews/{deep_review_id}` |
| POST | `/deep-reviews/{deep_review_id}/attempts` |

### 프런트엔드 현황

`web/frontend/src/components/deep-review/api.ts`에 7개만 있다:
`getDeepReview`, `getDocumentBundles`, `createDeepReview`, `getReport`, `getEvidence`,
`saveRevision`, `saveFinalOpinion`.

**빠진 것: bundle 생성, 문서 업로드, 문서 분류(PATCH), bundle 확정(confirm),
구조 조회, 재시도(attempts).** 이 여섯 개가 3단계의 핵심이다.

업로드 UI는 `web/frontend/src/pages/AttachmentsPage.tsx`의 기존 패턴을 재사용한다.
진입점은 `web/frontend/src/pages/NoticeDetailPage.tsx`의 심층 검토 섹션이다.

### 반드시 확인할 게이트

- `create_bundle`은 `effective_grade == "우선 검토"`가 아니면 403이다
  (`web/backend/app/services/document_bundles.py`). UI가 이 상태를 사용자에게
  설명해야 하고, 403을 숨기거나 우회해서는 안 된다.
- 심층 검토 생성은 `BIDOPS_ACTIVE_PROFILE_VERSION_ID`와
  `BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID`가 모두 설정되어야 열린다. 기본은 fail closed다.

## 작업 방식

0~2단계와 동일하게 한다.

1. **먼저 `docs/review/phase3/plan.md`와 `docs/review/phase3/spec.md`를 쓴다.**
   `docs/review/phase0-2/spec.md`와 같은 해상도로 — 파일별로 무엇을 바꾸는지,
   완료 기준이 무엇인지까지.
2. 각 작업을 codex exec에 위임한다:
   ```bash
   codex exec -m gpt-5.6-luna -c model_reasoning_effort=max \
     -C /home/jechoi/projects/bidops -s workspace-write \
     -o <요약파일> "<작업 지시>"
   ```
   지시문에는 항상 spec.md의 해당 절, `docs/standards.md`,
   `docs/engineering-notes.md`, 대상 모듈 `AGENTS.md`를 읽으라는 요구를 넣는다.
   커밋 금지와 git 이력 조작 금지도 명시한다.
3. **작업이 끝날 때마다 diff를 직접 읽고 리뷰한다.** codex 보고서를 그대로 믿지 않는다.
   0~2단계에서 codex 산출물의 유출 경로 3건과 설계 오류 1건을 리뷰에서 잡았다.
   수정할 게 있으면 고친 뒤 다음 작업으로 넘어간다.
4. 모든 작업이 끝나면 최종 리뷰를 하고, 문제는 즉시 해결한 뒤 보고한다.

codex exec는 10분을 넘길 수 있다. Bash 도구 타임아웃 상한이 10분이므로
출력을 파일로 리다이렉트하고 백그라운드로 돌리거나, 작업을 잘게 쪼갠다.

## 검증

**호스트에 pip/venv가 없다. 도커가 유일한 실행 수단이다.**

백엔드 테스트는 `web/run-web-tests.sh`와 같은 환경을 컨테이너 안에서 재현해야 한다.
`bidops-review:local` 이미지에 저장소를 `/src`로 마운트하고 일회용 postgres를 붙인다.
필요한 환경변수: `BIDOPS_ROOT=/src`, `BIDOPS_DATA_DIR`, `BIDOPS_ATTACHMENTS_DIR`,
`BIDOPS_OLLAMA_BASE_URL=http://127.0.0.1:9`, `BIDOPS_SCHEDULER_ENABLED=false`,
`BIDOPS_LIVE_OLLAMA_TEST=false`, `BIDOPS_TEST_POSTGRES_URL`,
`BIDOPS_DATABASE_URL`(= 같은 admin URL). pytest 전에 `alembic upgrade head`를 돌린다.

**현재 기준선: 741 passed, 5 skipped, 2 failed.**
실패 2건(`test_profile_snapshot*`)은 승인된 git blob `ee621835…`가 이 저장소 이력에
없어서 생기는 환경 아티팩트다. 코드 결함이 아니므로 고치려 하지 말고, 그 2건 외에
새 실패가 없는지만 본다.

프런트엔드는 `web/frontend`에서 `npm run build`(`tsc -b && vite build`)가 검증이다.
유닛 테스트는 없고 `test:visual`(playwright)만 있다.

스택 기동:

```bash
export COMPOSE_PROJECT_NAME=bidops-deep-review-t7
docker compose -f docker-compose.t7.yml up -d postgres minio clamav
for s in postgres-init migrate minio-init; do
  docker compose -f docker-compose.t7.yml run --rm $s
done
docker compose -f docker-compose.t7.yml -f docker-compose.t7.mock-reference.yml \
  up -d web document-worker analysis-worker
curl -fsS http://127.0.0.1:18787/api/health   # {"status":"ok"}
```

3단계는 실제 vLLM 없이 **`docker-compose.t7.mock-reference.yml` 오버레이로 먼저**
개발한다. mock 경로는 이미 T7 E2E를 통과한 기록이 있다. 실제 vLLM 연결은 UI가
완성된 뒤다.

## 주의: 정리해야 할 것

`bidops-deep-review-t7_postgres-data` volume에 0~2단계 검증에 쓴 임시 비밀번호로
역할이 만들어져 있다. 실제 `.env`로 처음 기동하기 전에 **그 volume을 삭제한다.**

```bash
docker volume rm bidops-deep-review-t7_postgres-data
```

사용자의 `.env`에는 `BIDOPS_G2B_API_KEY`만 들어 있다. T7 스택을 띄우려면 비밀번호
5개, MinIO 키 10개, 암호화 키 2개가 더 필요하다. `.env`를 덮어쓰기 전에 사용자에게 확인한다.

## 지켜야 할 경계

`CLAUDE.md`의 불변 조건이 그대로 적용된다. 특히 3단계에서 걸리기 쉬운 것:

- 확인되지 않은 사실을 추정해 채우지 않는다. `unknown`은 결함이 아니라 검증 대기 상태다.
- 1차 등급과 참여 준비 상태를 섞지 않는다.
- 시스템은 입찰 제출·발주처 연락·최종 Go/No-Go를 자동 실행하지 않는다.
  UI가 "참여 확정" 같은 버튼을 만들지 않는다.
- 첨부 원문이 프로젝트 경로를 벗어나거나, API 키·회사자료가 로그·응답에 노출되거나,
  승인 없는 OpenAI 전송이 생기거나, 회차 원본·기존 리뷰가 덮어써지면
  **작업을 멈추고 사용자에게 즉시 알린다.**
- 업로드 파일의 사용자 제공 경로·파일명을 로그에 넣지 않는다. `sha256`과 크기만 남긴다.
  로깅 규칙은 `web/backend/app/logging_setup.py`의 `SAFE_KEYS`가 강제한다.
  새 키가 필요하면 그 목록에 추가하고 왜 안전한 식별자인지 근거를 남긴다.

## 먼저 할 일

`docs/review/phase3/plan.md`와 `docs/review/phase3/spec.md`를 작성하고,
작업 분해와 순서를 보고한 뒤 위임을 시작한다.
