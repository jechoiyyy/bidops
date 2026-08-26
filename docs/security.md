# 보안 정책 (Lean v1)

## 권위와 신뢰 경계

PostgreSQL 17 `bidops`와 MinIO purpose buckets가 live canonical이다. SQLite는 migration input/격리 테스트만 허용한다. source/structure/quarantine/model-response bucket과 policy는 Compose bootstrap으로 분리되고 backend가 각 namespace를 요청할 때만 해당 credential/client를 구성한다. filesystem object backend는 명시적 isolated pytest boundary에서만 허용한다. actor table은 만들지 않는다.

## API와 claimed name

승인된 mutation API는 `X-BidOps-Actor-Name`을 요구하고 이름은 인증이 아닌 감사용 claimed name이다. 비어 있거나 제어문자·`system`인 이름은 거부한다. worker 이벤트는 `actor_kind=system`과 safe metadata를 사용한다. 비밀번호·token·원문 byte·full prompt·raw model output·개인정보는 로그에 쓰지 않는다.

새 Lean API의 오류는 다음 형태로만 반환한다.

```json
{"error":{"code":"processing_failed","message":"안전한 설명","details":null},"request_id":"..."}
```

내부 exception, filesystem path, credentials, SQL, prompt는 response/log에 포함하지 않는다.

## 런타임 경계

FastAPI web은 PostgreSQL·MinIO·ClamAV restricted networks에서 원문을 먼저 검사하고, clean verdict와 동일 원문 SHA-256을 scratch envelope에 기록한다. web은 source/structure/quarantine만, analysis worker는 structure read와 model-response write/encryption만 사용하며 source/quarantine credential은 받지 않는다. bounded scratch 외의 canonical object는 MinIO에 남고 object key/version/etag가 DB location에 고정된다. credential-free `document-worker` 두 replica는 atomic scratch request/result만 사용하며 `network_mode: none`이다. worker는 Node HWP converter, PDF renderer와 OCR을 실행하되 raw request headers, credentials, DB/object capability를 받지 않는다. analysis worker는 concurrency 1이고 PostgreSQL 및 configured Ollama/internal analysis network만 접근한다. Ollama endpoint는 explicit host allowlist와 `/api/generate` path를 통과해야 하며 redirect/proxy를 허용하지 않는다. OpenAI와 Langfuse는 기본·운영 경로 모두 비활성이다.

## HTTP와 다운로드

FastAPI는 CSP, `X-Content-Type-Options: nosniff`, no-referrer와 API no-store를 설정한다. attachment download는 `default-src 'none'`, nosniff, no-store와 서버 생성 filename을 사용한다. `/api` route 등록 후에만 SPA fallback이 동작하며 API 404가 index로 바뀌지 않는다.

## 문서·객체 안전

허용된 HWP/HWPX/PDF만 서버 생성 이름으로 quarantine에 보관하고, path traversal/symlink 탈출·확장자 위장은 거부한다. source/structure/quarantine object는 routine delete를 허용하지 않는다. active hash verification 없는 object/DB restore는 성공으로 표시하지 않는다.

## 백업·복구

RPO 4h/RTO 8h, daily full+continuous WAL, object version-aware copy <=4h, retention daily14/weekly8/monthly6이다. 복구 순서는 object → DB → active hash 검증이며 pre-prod와 quarterly drill을 별도 기록한다. `docker compose down -v` 등 destructive volume command는 일상 절차가 아니다.
