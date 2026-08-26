# 외부 인터페이스 계약 (Lean v1)

## 공통 REST 규약

기본 경로는 `/api`다. 신규 Lean v1은 승인된 API 정확히 14개(#1-7 document/bundle, #8-10 deep review, #11-14 report/evidence)를 등록한다. 기존 legacy API는 호환성을 위해 유지하지만 새 계약의 common error shape는 다음과 같다.

```json
{"error":{"code":"bundle_not_ready","message":"ready document bundle이 필요합니다","details":null},"request_id":"..."}
```

조회는 허용하지만 mutation은 claimed-name boundary와 idempotency/request fence를 통과해야 한다. 이름 입력은 인증/권한 부여가 아니다.

`X-BidOps-Actor-Name`의 printable ASCII 값은 wire value를 그대로 사용한다. 표준 라이브러리 기반
인수 CLI는 비ASCII 이름만 `UTF-8''` 뒤에 canonical UTF-8 percent encoding을 붙이고
`X-BidOps-Actor-Name-Format: utf-8-percent-v1`을 함께 보낸다. 서버는 이 명시적 형식 헤더가 있을
때만 비ASCII 값을 복원한다. 형식 헤더가 없으면 prefix나 percent 문자열처럼 보이는 기존 ASCII 이름도
변경하지 않으며, unknown format과 malformed·ASCII-only·제어문자 encoding은 `actor_name_invalid`로
거부한다.

## Lean API 경로

| 번호 | 호출 |
|---:|---|
| 1 | `GET /api/notices/{notice_id}/document-bundles` |
| 2 | `POST /api/notices/{notice_id}/document-bundles` |
| 3 | `POST /api/document-bundles/{bundle_id}/documents` |
| 4 | `PATCH /api/document-versions/{document_version_id}` |
| 5 | `POST /api/document-bundles/{bundle_id}/confirm` |
| 6 | `GET /api/document-structures/{structure_id}` |
| 7 | `GET /api/document-structures/{structure_id}/pages/{page}` |
| 8 | `POST /api/notices/{notice_id}/deep-reviews` |
| 9 | `GET /api/deep-reviews/{deep_review_id}` |
| 10 | `POST /api/deep-reviews/{deep_review_id}/attempts` |
| 11 | `GET /api/deep-reviews/{deep_review_id}/report` |
| 12 | `POST /api/deep-reviews/{deep_review_id}/report-revisions` |
| 13 | `POST /api/deep-reviews/{deep_review_id}/final-opinions` |
| 14 | `GET /api/evidence/{evidence_id}` |

## 상태와 재현성

bundle confirmation은 ready/safe/structure snapshot을 고정한다. attempt는 `requirements_and_evaluation`, `delivery_risk_economics`, `synthesis_and_validation` 3 stage만 허용한다. analysis/report는 live attachment/document projection을 reread하지 않고 fixed snapshot/hash를 사용한다. Qwen local endpoint와 policy/model version은 audit-safe metadata/hash로만 기록한다.

세 stage persist 이후 machine report materializer가 report, validation, evidence joins, audit를 만들고 같은 fenced transaction 안에서 finish한다. report revision/final opinion은 append-only이며 validation 실패를 자동 통과로 바꾸지 않는다.

## 배포 입력

PostgreSQL 17.11 `bidops` schema가 canonical이며 SQLite는 one-time import only다. `docker-compose.t7.yml`은 현재 worktree 전용 template이고 `COMPOSE_PROJECT_NAME=bidops-deep-review-t7`를 지정해서 사용한다. credentials는 `.env.example`의 placeholder를 참고해 외부 secret manager에서 주입한다.
