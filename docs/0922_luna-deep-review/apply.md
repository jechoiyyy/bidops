# Luna 운영 적용 절차 — 실행 전 사람 확인 필요

> 2026-09-23 후속: 운영 0032·서비스·Luna 정책 적용 및 실제 모델 연결 확인 완료. 1489번 실제 호출은 주장 참조 검증 실패로 종결, 완성 보고서 인수 미완료. [운영 기록](../validation-runs/20260922-luna-deep-review/live-validation.md).
2026-09-23 작성. 아래는 재현 가능한 적용 절차다. 2026-09-23 실제 수행 범위는 위 운영 기록을 따른다. 구현·격리 검증과
실제 인증·모델 접근·실자료 품질은 별개다. 기존 사용자 변경이 함께 있는 트리이므로
릴리스 이미지에는 검토한 변경 집합을 명시한다. push는 요청 범위에 포함하지 않는다.

## 고정 값과 준비

- migration: `0031_prespec_preliminary_assessment` → `0032_luna_deep_review`.
- 정책: `web/backend/app/deep_review/policies/analysis-policy-luna-v1.json`.
- SHA-256: `e9fc6b929c80479ef81de48f1936f163bb32d7509d3793ed96f4c4b9c6b069d9`.
- provider/model/effort: `codex-exec` / `gpt-5.6-luna` / `xhigh`.
- CLI: 0.155.1. 모델 artifact revision은 미확인이다.
- 호출당 900초, 검토 전체 7200초. 자동 재호출·resume·Qwen fallback 없음.

전용 계정의 auth.json을 저장소 밖에서 준비한다. 파일은 runner UID 1000이 읽을 수
있는 소유권과 최소 읽기 권한으로 제공한다. 다른 서비스에는 마운트하지 않는다. 호스트의 Codex 홈 전체를 복사하거나
마운트하지 않는다. `env/luna.env`(gitignore)에 전용 secret 경로와 신규 요청 토글을
넣는다. 인증 확인을 위한 실제 호출도 별도 승인 대상이다. runner CLI help/version
검사는 모델 접근 가능성을 증명하지 않는다.

```dotenv
BIDOPS_CODEX_AUTH_FILE=/approved/secret/location/auth.json
BIDOPS_LUNA_DEEP_REVIEW_ENABLED=false
BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=false
```

운영 Compose 조합은 아래 배열 하나를 사용한다. `env/luna.env`는 마지막에 두어
명시적인 신규 요청 차단 값을 적용한다. 실제 비밀값을 명령 출력에 남기지 않는다.

```bash
export COMPOSE_PROJECT_NAME=bidops
luna_compose=(docker compose --env-file .env --env-file env/model.env
  --env-file env/prespec-attachment.env --env-file env/c2.env --env-file env/luna.env
  -f docker-compose.yml -f docker-compose.edge.yml -f docker-compose.model-egress.yml
  -f docker-compose.prespec-attachment.yml -f docker-compose.c2-order-plan.yml
  -f docker-compose.luna.yml --profile prespec --profile luna)
"${luna_compose[@]}" config --quiet
# 준비만 수행: 운영 서비스 교체·migration·모델 호출 없음
"${luna_compose[@]}" build web migrate analysis-worker prespec-attachment-worker codex-runner
```

운영 egress firewall은 runner의 실제 인증 방식에 필요한 OpenAI/ChatGPT 통신만
허용하도록 별도 점검한다. Compose egress network 자체는 host allowlist가 아니다.
web은 runner 내부망에도 외부망에도 추가하지 않는다. runner에는 DB·MinIO·원문
volume이 없어야 한다. 컨테이너의 non-root, read-only, cap_drop, tmpfs, secret 단일
마운트를 검사한다. 이 호스트의 방화벽 allow/deny는 실제 인수 전에 확인해야 한다.

## 기존 작업 배수와 백업

신규 요청을 받지 않는 작업 창을 잡고 현재 활성 작업을 조회한다. 새 CLI가 아직
운영 이미지에 없으면 준비한 새 이미지의 일회성 CLI 컨테이너를 사용한다(모델 실행 없음).

```bash
"${luna_compose[@]}" run --rm --no-deps web python -m app.deep_review.cli close-deep-review --list-active
```

running 작업은 끝날 때까지 기다린다. queued 작업은 **각 중단 직전 확인 후** 다음
명령으로 닫는다. running이나 종결 작업은 이 명령이 거부한다. SQL UPDATE나 provider
변경은 금지한다. 중단은 `deep_review.operator_close` 감사와 실패 이력을 남긴다.

```bash
"${luna_compose[@]}" run --rm --no-deps web python -m app.deep_review.cli close-deep-review \
  --review-id '<queued review UUID>' --actor-name '<담당자>'
```

[운영 백업 절차](../operations.md#백업과-복구)에 따라 DB와 객체 version 전체를 같은
복구 지점으로 백업한다. dump exit·크기·해시·`pg_restore --list`, 객체 manifest와
암호화 key 복구 위치를 확인한다. 백업 파일은 기존 파일을 덮지 않는다.

```bash
"${luna_compose[@]}" --profile backup run --rm ro-backup
./scripts/backup-objects.sh
# 릴리스 적용 직전, 롤백 태그가 없음을 확인한 후 생성한다.
git tag before-luna-deep-review-20260923 HEAD
```

태그는 현재 HEAD만 보존하므로 기존 미커밋 사용자 변경의 백업을 대신하지 않는다.
운영 이미지 digest와 현재 환경 파일을 별도로 보존하고, 사용자 변경은 그대로 둔다.

## migration — 직전 확인

실행 중인 작업이 없고 전체 백업이 유효한 상태에서만 진행한다. 관련 write 서비스와
cron 유입을 작업 창에서 멈춘 뒤 migration/권한 적용을 수행한다. 멈춘 cron의 원래
내용은 보존하고 임의로 설치하거나 변경하지 않는다.

```bash
"${luna_compose[@]}" stop web analysis-worker prespec-attachment-worker
"${luna_compose[@]}" run --rm migrate
```

migration service는 새 코드 이미지로 준비해야 한다. head가 `0032_luna_deep_review`인지,
app은 두 표의 SELECT/INSERT만, worker는 SELECT만 갖는지 확인한다. 승인 기록이 있으면
schema downgrade는 금지된다. 다른 표의 원본·보고서·의견은 수정하지 않는다.

## 재배포 — migration과 별도 직전 확인

검토한 소스로 web·analysis-worker·첨부 worker·runner 이미지를 먼저 빌드한다.
새 모델 요청은 계속 false로 둔다. 자동 준비를 호출하는 모든 서비스가 새 기본값을
읽게 web·analysis-worker·prespec-attachment-worker를 함께 교체한다.

```bash
# 위 준비 단계에서 만든 이미지로 재배포 직전 확인
"${luna_compose[@]}" up -d --no-deps --no-build --force-recreate \
  web analysis-worker prespec-attachment-worker codex-runner
```

health, 기존 목록·보고서, 문서 준비·개요 처리를 확인한다. 렌더된 설정은 비밀값 전체
출력 대신 필요한 flag만 확인한다. 기본 내부망과 기존 수집·개요 설정은 유지한다.

## 정책 적용 — 별도 직전 확인

새 불변 정책을 등록한다. 기존 승인 profile 원문은 새 값을 추정하지 않고 기존 기준선을
재검증한다. profile 복구 옵션은 자동으로 붙이지 않는다.

```bash
"${luna_compose[@]}" run --rm --no-deps web python -m app.deep_review.cli import-profile-policy \
  --actor '<담당자>' --label analysis-policy-luna-v1 \
  --policy /app/web/backend/app/deep_review/policies/analysis-policy-luna-v1.json \
  --expected-policy-sha256 e9fc6b929c80479ef81de48f1936f163bb32d7509d3793ed96f4c4b9c6b069d9
```

반환된 실제 profile/policy UUID를 `env/luna.env`의
`BIDOPS_ACTIVE_PROFILE_VERSION_ID`·`BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID`에 넣고
`BIDOPS_REFERENCE_WORKFLOW_MODE=true`, `BIDOPS_LUNA_DEEP_REVIEW_ENABLED=true`를 설정한다.
Qwen 정책 행을 수정하지 않는다. 환경 적용을 위한 서비스 교체는 다시 직전 확인을 받는다.
문서만 바꿔 활성화됐다고 기록하지 않는다.

## 실제 표본 — 별도 전송·모델 호출 직전 확인

1. 승인된 사전규격 1건의 개요 완료·확정 묶음·회사 프로필과 모델 접근 준비를 확인한다.
2. 실제 상세 화면에서 미리보기의 문서·회사자료 범위와 원문 대조 설정을 읽는다.
3. 담당자가 전송 승인을 제출한다. 202, preview/input hash, attempt UUID를 기록한다.
4. Luna 실행 중 두 번째 승인 표본을 요청하고 queued 유지→순차 실행을 확인한다.
5. 실행 출처·참조 표식·3단계·원응답 암호화 참조·보고서·원문 근거와 사람이 대조한
   결과를 기록한다. 개요 대기가 해소된 뒤 실제 개요 처리도 확인한다.
6. 실패하면 안전 코드를 확인하며 자동 fallback·재전송하지 않는다. 원인 해결 후 새
   미리보기·승인·attempt로 재요청한다. 의미 품질은 별도 미측정으로 남긴다.

## 차단과 롤백

신규 요청을 막으려면 `BIDOPS_LUNA_DEEP_REVIEW_ENABLED=false`로 돌리고 서비스 교체
직전 확인을 받는다. 실행 중 호출은 정상 종료를 기다리며 강제 중지는 별도 판단이다.
조회·수집·개요는 유지한다. 이전 이미지/환경으로 되돌릴 때도 별도 재배포 확인을 받는다.
append-only 입력·승인·완료 보고서는 남긴다. 이미 승인된 행이 있으면 migration
다운그레이드하지 않는다. DB 자체 복구가 필요하면 객체→DB 순서의 기존 복구 절차와
전체 백업을 사용하며 다른 사람의 이후 변경을 잃는 복구는 별도 승인 없이는 하지 않는다.
