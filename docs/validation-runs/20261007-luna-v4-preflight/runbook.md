# Luna v4 운영 선검증 runbook — 준비본

이 문서는 `DEMO-00-luna-preflight` STEP-003/004를 운영 호스트에서 사람이 한 단계씩 실행하기 위한 준비본이다. 이 문서를 작성하면서 배포, 백업, 정책 import, 환경 변경, 모델 호출은 수행하지 않았다.

현재 실행 차단 조건은 STEP-002의 T1·T2·T3·T6·T7 검증과 리더 리뷰가 끝나고 그 변경이 운영 호스트의 배포 대상 소스에 반영되는 것이다. 그 전에는 아래 읽기 전용 사전 확인까지만 한다. v4 파일이나 코드가 있다는 사실만으로 이 차단 조건이 해소되지는 않는다.

운영 변경은 아래 번호별로 바로 직전에 사용자 확인을 새로 받는다. 앞 단계 확인을 다음 단계에 재사용하거나 전체 절차를 한 스크립트로 묶어 실행하지 않는다. `migration`은 없으며 `migrate` 서비스를 실행하지 않는다. 기존 Luna v1·v2·v3 정책 행, 실패 실행, 승인 기록은 수정하거나 삭제하지 않는다.

## 0. 읽기 전용 사전 확인

운영 checkout 루트의 Bash에서 시작한다. 실제 비밀값, 전체 환경 파일, 전체 Compose config, prompt·응답·회사자료는 화면이나 실행 기록에 출력하지 않는다.

```bash
set -euo pipefail
export COMPOSE_PROJECT_NAME=bidops

policy_host_path=web/backend/app/deep_review/policies/analysis-policy-luna-v4.json
policy_container_path=/app/web/backend/app/deep_review/policies/analysis-policy-luna-v4.json
test -f "$policy_host_path" && test -r "$policy_host_path"
test -f .env && test -f env/model.env && test -f env/prespec-attachment.env
test -f env/c2.env && test -f env/luna.env

luna_compose=(docker compose
  --env-file .env
  --env-file env/model.env
  --env-file env/prespec-attachment.env
  --env-file env/c2.env
  --env-file env/luna.env
  -f docker-compose.yml
  -f docker-compose.edge.yml
  -f docker-compose.model-egress.yml
  -f docker-compose.prespec-attachment.yml
  -f docker-compose.c2-order-plan.yml
  -f docker-compose.luna.yml
  --profile prespec
  --profile luna)

"${luna_compose[@]}" config --quiet
"${luna_compose[@]}" ps web analysis-worker codex-runner
curl --fail --silent --show-error \
  "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health" >/dev/null
"${luna_compose[@]}" exec -T web \
  python -m app.deep_review.cli close-deep-review --list-active
```

`close-deep-review --list-active`가 빈 배열이 아니면 중단한다. `running`은 끝날 때까지 기다리고, `queued`도 이 절차에서 자동으로 닫지 않는다. 큐 중단은 별도 사람 판단과 감사 명령이 필요한 변경이다.

정책 파일은 canonical JSON이어야 한다. T1과 독립 리뷰가 승인한 불변 digest는
`51b1723051e92299ef53e650f9faf851c8e6777fe75c59b814639d38be887877`이다. 다음 명령은
운영 호스트 파일의 hash를 동적으로 계산한 뒤 이 승인값과 일치시킨다. checkout 자체에서 계산한
값만으로 승인본 여부를 판단하지 않는다.

```bash
approved_policy_sha256=51b1723051e92299ef53e650f9faf851c8e6777fe75c59b814639d38be887877
policy_sha256="$(POLICY_PATH="$policy_host_path" python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

path = Path(os.environ["POLICY_PATH"])
raw = path.read_bytes()
value = json.loads(raw.decode("utf-8"))
canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
if raw != canonical:
    raise SystemExit("v4 policy is not canonical JSON; stop before build")
print(hashlib.sha256(raw).hexdigest())
PY
)"
[[ "$policy_sha256" =~ ^[0-9a-f]{64}$ ]]
test "$policy_sha256" = "$approved_policy_sha256"
printf 'approved v4 policy sha256=%s\n' "$approved_policy_sha256"
```

STEP-002 검증 결과와 리더 리뷰가 아직 없거나 배포 대상 소스에 반영되지 않았다면 여기서 멈춘다.

## 1. 전체 백업과 롤백 기준점

**실행 직전 확인 1:** 사용자에게 지금 DB 전체 백업, 객체 전 version 백업, 현재 환경·이미지 보존, `before-luna-v4-<날짜>` 태그 생성을 진행해도 되는지 확인한다. 확인 전에는 아래 명령을 실행하지 않는다.

태그는 `HEAD`만 보존한다. `git status --short`가 비어 있지 않으면 태그가 배포 대상을 재현하지 못하므로 중단하고 배포 소스 범위를 다시 정한다.

```bash
git status --short
test -z "$(git status --short)"

release_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
release_date="$(date +%Y%m%d)"
rollback_tag="before-luna-v4-${release_date}"
ops_dir="backups/operations/luna-v4-${release_stamp}"
object_backup_dir="backups/objects/luna-v4-${release_stamp}"
install -d -m 700 "$ops_dir" "$object_backup_dir"
git rev-parse HEAD >"$ops_dir/source-head.txt"
git rev-parse -q --verify "refs/tags/$rollback_tag" >/dev/null && {
  printf 'rollback tag already exists: %s\n' "$rollback_tag" >&2
  false
}

web_cid="$("${luna_compose[@]}" ps -q web)"
analysis_cid="$("${luna_compose[@]}" ps -q analysis-worker)"
test -n "$web_cid" && test -n "$analysis_cid"
web_image_id_before="$(docker inspect --format '{{.Image}}' "$web_cid")"
analysis_image_id_before="$(docker inspect --format '{{.Image}}' "$analysis_cid")"
web_image_ref_before="$(docker inspect --format '{{.Config.Image}}' "$web_cid")"
analysis_image_ref_before="$(docker inspect --format '{{.Config.Image}}' "$analysis_cid")"
printf '%s\t%s\n' "$web_image_ref_before" "$web_image_id_before" >"$ops_dir/images.before.tsv"
printf '%s\t%s\n' "$analysis_image_ref_before" "$analysis_image_id_before" >>"$ops_dir/images.before.tsv"
docker image tag "$web_image_id_before" "bidops-rollback/web:luna-v4-${release_stamp}"
docker image tag "$analysis_image_id_before" "bidops-rollback/analysis-worker:luna-v4-${release_stamp}"
install -m 600 env/luna.env "$ops_dir/luna.env.before"

backup_marker="$ops_dir/postgres-backup.started"
touch "$backup_marker"
"${luna_compose[@]}" --profile backup run --rm ro-backup
mapfile -t new_dumps < <(find backups/postgres/full -type f -name '*.dump' -newer "$backup_marker" -print)
test "${#new_dumps[@]}" -eq 1
test -s "${new_dumps[0]}"
pg_restore --list "${new_dumps[0]}" >/dev/null
sha256sum "${new_dumps[0]}" >"$ops_dir/postgres-dump.sha256"

MINIO_ALIAS="${MINIO_ALIAS:?approved MinIO alias required}" \
OBJECT_BACKUP_DIR="$object_backup_dir" \
  ./scripts/backup-objects.sh
test -s "$object_backup_dir/object-versions.tsv"
sha256sum "$object_backup_dir/object-versions.tsv" >"$ops_dir/object-manifest.sha256"

git tag "$rollback_tag" HEAD
git show-ref --verify "refs/tags/$rollback_tag"
```

DB dump exit, 비어 있지 않은 dump, `pg_restore --list`, 객체 manifest, 두 SHA 파일, 보호된 이전 `luna.env`, 이전 image ID가 모두 확인되지 않으면 다음 단계로 가지 않는다. 이 검사는 실제 빈 대상 복구 훈련을 대신하지 않는다.

## 2. 후보 이미지 빌드

**실행 직전 확인 2:** 사용자에게 검토된 배포 대상 소스로 `web`과 `analysis-worker` 이미지를 빌드해도 되는지 확인한다. 빌드는 실행 컨테이너를 교체하지 않지만 서비스 image tag를 갱신하므로 백업 단계 뒤에만 한다.

```bash
"${luna_compose[@]}" build web analysis-worker

image_policy_sha256="$("${luna_compose[@]}" run --rm --no-deps web \
  sha256sum "$policy_container_path" | awk '{print $1}')"
test "$image_policy_sha256" = "$approved_policy_sha256"
printf 'candidate image policy sha256=%s\n' "$image_policy_sha256"
```

hash가 다르거나 image 안에 v4 파일이 없으면 중단한다. `codex-runner` 계약은 STEP-002에서 바뀌지 않으므로 이 단계에서 재빌드하거나 교체하지 않는다.

## 3. 코드 배포 — Luna 요청 차단 상태 유지

**실행 직전 확인 3:** 사용자에게 Luna 신규 요청을 계속 차단한 상태로 `web`·`analysis-worker`만 교체해도 되는지 확인한다.

먼저 `env/luna.env`에 `BIDOPS_LUNA_DEEP_REVIEW_ENABLED=false`가 설정돼 있는지 편집기로 확인한다. 전체 파일을 출력하지 않는다. Compose가 렌더한 안전한 세 값만 검사한다.

```bash
"${luna_compose[@]}" config --format json | EXPECTED_LUNA=false python3 -c '
import json, os, sys
cfg = json.load(sys.stdin)
for name in ("web", "analysis-worker"):
    env = cfg["services"][name].get("environment", {})
    shown = {key: env.get(key) for key in (
        "BIDOPS_LUNA_DEEP_REVIEW_ENABLED",
        "BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED",
        "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID",
    )}
    if str(shown["BIDOPS_LUNA_DEEP_REVIEW_ENABLED"]).lower() != os.environ["EXPECTED_LUNA"]:
        raise SystemExit(f"{name}: Luna flag mismatch")
    if str(shown["BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED"]).lower() != "false":
        raise SystemExit(f"{name}: auto-start must stay false")
    print(name, json.dumps(shown, ensure_ascii=False, sort_keys=True))
'

"${luna_compose[@]}" up -d --no-deps --no-build --force-recreate \
  web analysis-worker
curl --fail --silent --show-error \
  "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health" >/dev/null
"${luna_compose[@]}" ps web analysis-worker codex-runner
```

실행 컨테이너에서도 안전한 네 값만 확인한다. 다음 함수는 Docker inspect 전체를 pipe로 읽지만 출력은 선택한 flag뿐이다. expected policy/reference 인자를 주면 값까지 일치시킨다.

```bash
verify_running_flags() {
  local expected_luna="$1" expected_policy_id="${2:-}" expected_reference="${3:-}"
  local service cid
  for service in web analysis-worker; do
    cid="$("${luna_compose[@]}" ps -q "$service")"
    test -n "$cid"
    docker inspect "$cid" | SERVICE="$service" EXPECTED_LUNA="$expected_luna" \
      EXPECTED_POLICY_ID="$expected_policy_id" EXPECTED_REFERENCE="$expected_reference" \
      python3 -c '
import json, os, sys
row = json.load(sys.stdin)[0]
env = dict(item.split("=", 1) for item in row["Config"]["Env"] if "=" in item)
service = os.environ["SERVICE"]
shown = {key: env.get(key) for key in (
    "BIDOPS_LUNA_DEEP_REVIEW_ENABLED",
    "BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED",
    "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID",
    "BIDOPS_REFERENCE_WORKFLOW_MODE",
)}
if str(shown["BIDOPS_LUNA_DEEP_REVIEW_ENABLED"]).lower() != os.environ["EXPECTED_LUNA"]:
    raise SystemExit(f"{service}: Luna flag mismatch")
if str(shown["BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED"]).lower() != "false":
    raise SystemExit(f"{service}: auto-start must stay false")
if os.environ["EXPECTED_POLICY_ID"] and shown["BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID"] != os.environ["EXPECTED_POLICY_ID"]:
    raise SystemExit(f"{service}: active policy mismatch")
if os.environ["EXPECTED_REFERENCE"] and str(shown["BIDOPS_REFERENCE_WORKFLOW_MODE"]).lower() != os.environ["EXPECTED_REFERENCE"]:
    raise SystemExit(f"{service}: reference mode mismatch")
print(service, json.dumps(shown, ensure_ascii=False, sort_keys=True))
'
  done
}

verify_running_flags false
```

health 실패, worker 미기동, 자동 시작 `true`, Luna `true`이면 중단하고 롤백 절을 따른다.

## 4. v4 불변 정책 import

**실행 직전 확인 4:** 사용자에게 host·image hash가 독립 승인 digest와 일치한 v4 정책을 append-only DB 행으로 import해도 되는지 확인한다. 이 단계는 active ID를 바꾸지 않는다.

먼저 v1·v2·v3의 안전한 식별 정보만 저장한다.

```bash
"${luna_compose[@]}" exec -T web python -c '
import json
from sqlalchemy import select
from app.core.db import SessionLocal
from app.deep_review.models import AnalysisPolicyVersion
labels = ("analysis-policy-luna-v1", "analysis-policy-luna-v2", "analysis-policy-luna-v3")
with SessionLocal() as session:
    rows = session.scalars(select(AnalysisPolicyVersion).where(AnalysisPolicyVersion.label.in_(labels)).order_by(AnalysisPolicyVersion.version, AnalysisPolicyVersion.id)).all()
    if not set(labels).issubset({row.label for row in rows}):
        raise SystemExit("one or more v1-v3 policy rows are missing")
    print(json.dumps([{"id": str(r.id), "version": r.version, "label": r.label, "policy_sha256": r.policy_sha256} for r in rows], sort_keys=True))
' >"$ops_dir/policies-v1-v3.before.json"

active_profile_id="$("${luna_compose[@]}" config --format json | python3 -c '
import json, sys
value = json.load(sys.stdin)["services"]["web"].get("environment", {}).get("BIDOPS_ACTIVE_PROFILE_VERSION_ID", "")
if not value:
    raise SystemExit("active profile ID is empty")
print(value)
')"

read -r -p '감사 기록에 남길 담당자 이름: ' operator_name
test -n "${operator_name//[[:space:]]/}"
import_json="$("${luna_compose[@]}" run --rm --no-deps web \
  python -m app.deep_review.cli import-profile-policy \
  --actor "$operator_name" \
  --label analysis-policy-luna-v4 \
  --policy "$policy_container_path" \
  --expected-policy-sha256 "$approved_policy_sha256")"
printf '%s\n' "$import_json" >"$ops_dir/v4-import.json"

policy_version_id="$(IMPORT_JSON="$import_json" EXPECTED_SHA="$approved_policy_sha256" EXPECTED_PROFILE_ID="$active_profile_id" python3 -c '
import json, os, re
row = json.loads(os.environ["IMPORT_JSON"])
if row.get("active_configuration_changed") is not False:
    raise SystemExit("import unexpectedly changed active configuration")
if row.get("policy_sha256") != os.environ["EXPECTED_SHA"]:
    raise SystemExit("imported policy hash mismatch")
if row.get("profile_version_id") != os.environ["EXPECTED_PROFILE_ID"]:
    raise SystemExit("import selected a different profile version; stop")
value = row.get("policy_version_id", "")
if not re.fullmatch(r"[0-9a-fA-F-]{36}", value):
    raise SystemExit("invalid policy UUID")
print(value)
')"
printf 'policy_version_id=%s\npolicy_sha256=%s\n' "$policy_version_id" "$approved_policy_sha256"

"${luna_compose[@]}" exec -T web python -c '
import json
from sqlalchemy import select
from app.core.db import SessionLocal
from app.deep_review.models import AnalysisPolicyVersion
labels = ("analysis-policy-luna-v1", "analysis-policy-luna-v2", "analysis-policy-luna-v3")
with SessionLocal() as session:
    rows = session.scalars(select(AnalysisPolicyVersion).where(AnalysisPolicyVersion.label.in_(labels)).order_by(AnalysisPolicyVersion.version, AnalysisPolicyVersion.id)).all()
    if not set(labels).issubset({row.label for row in rows}):
        raise SystemExit("one or more v1-v3 policy rows are missing")
    print(json.dumps([{"id": str(r.id), "version": r.version, "label": r.label, "policy_sha256": r.policy_sha256} for r in rows], sort_keys=True))
' >"$ops_dir/policies-v1-v3.after.json"
cmp "$ops_dir/policies-v1-v3.before.json" "$ops_dir/policies-v1-v3.after.json"

"${luna_compose[@]}" exec -T web python - "$policy_version_id" "$approved_policy_sha256" <<'PY'
import sys
from uuid import UUID
from app.core.db import SessionLocal
from app.deep_review.models import AnalysisPolicyVersion

with SessionLocal() as session:
    row = session.get(AnalysisPolicyVersion, UUID(sys.argv[1]))
    if row is None or row.label != "analysis-policy-luna-v4" or row.policy_sha256 != sys.argv[2]:
        raise SystemExit("persisted v4 policy identity mismatch")
    print(f"v4 policy row verified: version={row.version} id={row.id} sha256={row.policy_sha256}")
PY
```

CLI가 `import failed:*`로 끝나거나 반환 hash가 다르거나 `active_configuration_changed`가 `false`가 아니거나 v1–v3 snapshot이 달라졌으면 중단한다. SQL로 보정하거나 기존 행을 수정하지 않는다.

## 5. v4 active ID 반영 — Luna 요청은 계속 차단

다음 함수는 허용한 비밀 아닌 키 하나만 `env/luna.env`에서 바꾸며 파일 내용을 출력하지 않는다. 같은 키가 중복되면 fail closed한다.

```bash
set_luna_env() {
  local key="$1" value="$2"
  KEY="$key" VALUE="$value" python3 - <<'PY'
import os
import re
import stat
import tempfile
from pathlib import Path

path = Path("env/luna.env")
key = os.environ["KEY"]
value = os.environ["VALUE"]
allowed = {
    "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID",
    "BIDOPS_LUNA_DEEP_REVIEW_ENABLED",
    "BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED",
    "BIDOPS_REFERENCE_WORKFLOW_MODE",
}
if key not in allowed or "\n" in value or "\r" in value:
    raise SystemExit("refusing unsafe env update")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
pattern = re.compile(rf"^{re.escape(key)}=")
matches = [index for index, line in enumerate(lines) if pattern.match(line)]
if len(matches) > 1:
    raise SystemExit(f"duplicate env key: {key}")
replacement = f"{key}={value}\n"
if matches:
    lines[matches[0]] = replacement
else:
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += "\n"
    lines.append(replacement)
mode = stat.S_IMODE(path.stat().st_mode)
fd, temporary = tempfile.mkstemp(prefix=".luna.env.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
        stream.writelines(lines)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
except BaseException:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    raise
PY
}
```

**실행 직전 확인 5:** 사용자에게 active analysis policy를 반환된 v4 UUID로 바꾸고, 참조 workflow를 켜되 Luna 요청과 자동 시작은 끈 상태로 `web`·`analysis-worker`를 다시 생성해도 되는지 확인한다.

```bash
set_luna_env BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID "$policy_version_id"
set_luna_env BIDOPS_REFERENCE_WORKFLOW_MODE true
set_luna_env BIDOPS_LUNA_DEEP_REVIEW_ENABLED false
set_luna_env BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED false

"${luna_compose[@]}" config --format json | EXPECTED_POLICY_ID="$policy_version_id" EXPECTED_LUNA=false python3 -c '
import json, os, sys
cfg = json.load(sys.stdin)
expected = {
    "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID": os.environ["EXPECTED_POLICY_ID"],
    "BIDOPS_REFERENCE_WORKFLOW_MODE": "true",
    "BIDOPS_LUNA_DEEP_REVIEW_ENABLED": os.environ["EXPECTED_LUNA"],
    "BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED": "false",
}
for name in ("web", "analysis-worker"):
    env = cfg["services"][name].get("environment", {})
    shown = {key: str(env.get(key, "")).lower() if key != "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID" else env.get(key) for key in expected}
    if shown != expected:
        raise SystemExit(f"{name}: safe flag mismatch: {shown}")
    print(name, json.dumps(shown, ensure_ascii=False, sort_keys=True))
'

"${luna_compose[@]}" up -d --no-deps --no-build --force-recreate \
  web analysis-worker
curl --fail --silent --show-error \
  "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health" >/dev/null
"${luna_compose[@]}" ps web analysis-worker codex-runner
```

```bash
verify_running_flags false "$policy_version_id" true
```

두 서비스의 active ID가 `$policy_version_id`, reference mode가 `true`, Luna와 auto-start가 `false`인지 확인한다. 확인 전에는 다음 단계로 가지 않는다.

## 6. 단일 요청 창 열기

**실행 직전 확인 6:** 사용자에게 1489번 미리보기 한 건만 만들기 위해 Luna 신규 요청 토글을 켜고 `web`·`analysis-worker`를 재생성해도 되는지 확인한다. 이 확인은 실제 payload 전송 승인이 아니다.

```bash
"${luna_compose[@]}" exec -T web \
  python -m app.deep_review.cli close-deep-review --list-active
# 반드시 []인지 사람이 확인한다.

set_luna_env BIDOPS_LUNA_DEEP_REVIEW_ENABLED true

"${luna_compose[@]}" config --format json | EXPECTED_POLICY_ID="$policy_version_id" EXPECTED_LUNA=true python3 -c '
import json, os, sys
cfg = json.load(sys.stdin)
expected = {
    "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID": os.environ["EXPECTED_POLICY_ID"],
    "BIDOPS_REFERENCE_WORKFLOW_MODE": "true",
    "BIDOPS_LUNA_DEEP_REVIEW_ENABLED": os.environ["EXPECTED_LUNA"],
    "BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED": "false",
}
for name in ("web", "analysis-worker"):
    env = cfg["services"][name].get("environment", {})
    shown = {key: str(env.get(key, "")).lower() if key != "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID" else env.get(key) for key in expected}
    if shown != expected:
        raise SystemExit(f"{name}: safe flag mismatch: {shown}")
    print(name, json.dumps(shown, ensure_ascii=False, sort_keys=True))
'

"${luna_compose[@]}" up -d --no-deps --no-build --force-recreate \
  web analysis-worker
curl --fail --silent --show-error \
  "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health" >/dev/null
"${luna_compose[@]}" ps web analysis-worker codex-runner
```

```bash
verify_running_flags true "$policy_version_id" true
```

active ID, reference mode, Luna `true`, auto-start `false`가 두 서비스에서 정확히 일치하지 않으면 요청 창을 열지 않는다.

## 7. 1489 미리보기와 건별 사용자 승인

**실행 직전 확인 7:** 운영 화면에서 사용자가 payload 전체를 직접 읽은 뒤, 해당 preview/input hash의 외부 전송과 Luna 호출을 승인하는지 다시 확인한다. 토글을 켰다는 사실은 이 승인을 대신하지 않는다.

1. 운영 화면 `/pre-specs/1489`를 연다. 기존 v1–v3 실패 검토의 재시도 버튼을 사용하지 않는다.
2. 담당자 이름을 입력하고 확정된 기존 문서 묶음을 선택한다. `원문 대조 사용`을 유지한다.
3. `전송 내용 미리보기`를 누른다. 이 동작은 preview를 저장하지만 아직 모델을 호출하지 않는다.
4. 화면에서 provider/model/effort가 `codex-exec` / `gpt-5.6-luna` / `xhigh`, 품질이 `미측정`, 원문 대조가 `사용`인지 확인한다.
5. 펼친 전송 입력에서 notice 1489, 선택 문서, 회사자료, 정책의 `policy_identity=analysis-policy-luna-v4`, `execution.review_timeout_seconds=18000`, `execution.validation_repair_attempts=1`을 확인하고 `validation.result_checks`가 `disabled_reference_v1`이 아님을 직접 확인한다. preview 본문은 일반 로그나 Git 문서로 복사하지 않는다.
6. 화면의 `preview_id`와 `input_sha256`을 보호된 운영 기록에 적는다.
7. 이 시점에 **실제 전송·호출 직전 사용자 확인**을 받는다. 확인을 받은 뒤에만 `전송 승인하고 심층검토 요청`을 한 번 누른다. 중복 클릭하거나 API로 반복 제출하지 않는다.
8. 생성 응답의 새 `review_id`, 새 `attempt_id`, `preview_id`, `input_sha256`, 시작 시각을 적는다. 기존 검토나 기존 attempt를 덮어쓰지 않는다.

정책이 허용하는 자동 동작은 1·2단계 각 slice의 결정적 검증 실패에 대한 같은 동결 입력 1회 교정 재요청뿐이다. operator 재요청, 새 preview 자동 생성, 전체 review 자동 재시작, Qwen/hosted OpenAI fallback은 없다.

## 8. 관측과 결과 요약

`review_id`를 실제 생성 응답의 UUID로 입력한다. 장시간 실행은 이미 분리된 `analysis-worker`가 수행하므로 별도 foreground 호출을 만들지 않는다. 아래 읽기 전용 snapshot을 필요할 때 한 번씩 실행하며, 조용한 로그를 성공으로 해석하지 않는다.

```bash
read -r -p '새 review UUID: ' review_id
[[ "$review_id" =~ ^[0-9a-fA-F-]{36}$ ]]

curl --fail --silent --show-error \
  "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/deep-reviews/${review_id}" |
  python3 -c '
import json, sys
row = json.load(sys.stdin)
attempt = row.get("current_attempt") or {}
print(json.dumps({
    "review_id": row.get("id"),
    "notice_id": row.get("notice_id"),
    "status": row.get("status"),
    "quality_status": row.get("quality_status"),
    "attempt_id": attempt.get("id"),
    "attempt_status": attempt.get("status"),
    "preview_id": attempt.get("preview_id"),
    "started_at": attempt.get("started_at"),
    "completed_at": attempt.get("completed_at"),
    "stages": [{
        "stage": stage.get("stage"),
        "status": stage.get("status"),
        "started_at": stage.get("started_at"),
        "completed_at": stage.get("completed_at"),
        "last_error_code": stage.get("last_error_code"),
    } for stage in attempt.get("stages", [])],
}, ensure_ascii=False, sort_keys=True, indent=2))
'
```

종료 뒤 slice별 안전한 호출 메타데이터를 DB에서 읽는다. 이 명령은 prompt·응답·회사자료·object key를 출력하지 않는다.

```bash
"${luna_compose[@]}" exec -T web python - "$review_id" <<'PY'
import json
import sys
from uuid import UUID
from sqlalchemy import select
from app.core.db import SessionLocal
from app.deep_review.models import AnalysisPolicyVersion, DeepReview, DeepReviewAttempt, DeepReviewStage

review_id = UUID(sys.argv[1])
with SessionLocal() as session:
    review = session.get(DeepReview, review_id)
    if review is None:
        raise SystemExit("review not found")
    attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
    policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
    stages = session.scalars(
        select(DeepReviewStage)
        .where(DeepReviewStage.attempt_id == attempt.id)
        .order_by(DeepReviewStage.sequence)
    ).all()
    stage_rows = []
    for stage in stages:
        invocations = stage.invocation_metadata if isinstance(stage.invocation_metadata, list) else []
        safe_invocations = []
        for item in invocations:
            if not isinstance(item, dict):
                continue
            safe_invocations.append({key: item.get(key) for key in (
                "slice_index", "validation_repair_attempt", "status",
                "error_code", "latency_ms",
            )})
        stage_rows.append({
            "stage": stage.stage,
            "status": stage.status,
            "started_at": stage.started_at.isoformat() if stage.started_at else None,
            "completed_at": stage.completed_at.isoformat() if stage.completed_at else None,
            "invocations": safe_invocations,
        })
    total_seconds = None
    if attempt.started_at and attempt.completed_at:
        total_seconds = (attempt.completed_at - attempt.started_at).total_seconds()
    print(json.dumps({
        "review_id": str(review.id),
        "notice_id": review.notice_id,
        "review_status": review.status,
        "attempt_id": str(attempt.id),
        "attempt_status": attempt.status,
        "policy_version_id": str(policy.id),
        "policy_sha256": policy.policy_sha256,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
        "total_seconds": total_seconds,
        "stages": stage_rows,
    }, ensure_ascii=False, sort_keys=True, indent=2))
PY
```

`completed`이면 보고서 API에서 본문을 출력하지 않고 검증 요약만 확인한다.

```bash
curl --fail --silent --show-error \
  "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/deep-reviews/${review_id}/report" |
  python3 -c '
import json, sys
row = json.load(sys.stdin)
report = row["report"]
validation = row["validation"]
print(json.dumps({
    "deep_review_id": row["deep_review_id"],
    "report_revision_id": row["current_revision_id"],
    "quality_status": report.get("quality_status"),
    "report_validation_summary": report.get("validation_summary"),
    "validation_run_id": validation.get("validation_run_id"),
    "validation_status": validation.get("status"),
    "failed_checks": sum(check.get("status") == "failed" for check in validation.get("checks", [])),
    "warning_checks": sum(check.get("status") == "warning" for check in validation.get("checks", [])),
}, ensure_ascii=False, sort_keys=True, indent=2))
'
```

`failed`이면 report GET 성공을 기대하지 않는다. review/attempt/stage의 종료 상태, 최초 실패 code, 처리된 slice 수, 교정 재요청 횟수, 총 소요 시간을 기록하고 원응답은 암호화 객체 저장소에 그대로 둔다. `completed`여도 `quality_status=unmeasured_reference`는 운영 완료·모델 품질·DEMO 정책 활성화 근거가 아니다. 같은 정책 재실행이나 DEMO-01 진행은 사용자가 별도로 결정한다.

## 9. 결과 확인 뒤 요청 토글 끄기

review와 attempt가 `completed` 또는 `failed`로 종결되기 전에는 worker를 재생성하지 않는다. 장시간 `queued`/`running`에 머물러도 강제 중지나 토글 변경으로 해결하지 않고 상태와 lease를 별도로 판단한다.

**실행 직전 확인 8:** 종결 결과를 사용자에게 보여 준 뒤, 신규 Luna 요청 토글을 `false`로 돌리고 `web`·`analysis-worker`를 재생성해도 되는지 확인한다.

```bash
set_luna_env BIDOPS_LUNA_DEEP_REVIEW_ENABLED false

"${luna_compose[@]}" config --format json | EXPECTED_POLICY_ID="$policy_version_id" EXPECTED_LUNA=false python3 -c '
import json, os, sys
cfg = json.load(sys.stdin)
expected = {
    "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID": os.environ["EXPECTED_POLICY_ID"],
    "BIDOPS_REFERENCE_WORKFLOW_MODE": "true",
    "BIDOPS_LUNA_DEEP_REVIEW_ENABLED": os.environ["EXPECTED_LUNA"],
    "BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED": "false",
}
for name in ("web", "analysis-worker"):
    env = cfg["services"][name].get("environment", {})
    shown = {key: str(env.get(key, "")).lower() if key != "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID" else env.get(key) for key in expected}
    if shown != expected:
        raise SystemExit(f"{name}: safe flag mismatch: {shown}")
    print(name, json.dumps(shown, ensure_ascii=False, sort_keys=True))
'

"${luna_compose[@]}" up -d --no-deps --no-build --force-recreate \
  web analysis-worker
curl --fail --silent --show-error \
  "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health" >/dev/null
"${luna_compose[@]}" ps web analysis-worker codex-runner
```

```bash
verify_running_flags false "$policy_version_id" true
```

두 서비스의 Luna `false`, auto-start `false`를 확인한다. v4 active ID를 유지할지 이전 ID로 돌릴지는 실행 결과를 본 사용자의 별도 결정이다. 이 단계에서 임의로 v3를 재활성화하지 않는다.

## 차단과 롤백

- 정책 import 뒤 문제가 나도 v4 행을 삭제하거나 v1–v3 행을 수정하지 않는다. import·preview·approval·attempt 감사 이력은 append-only로 보존한다.
- 실제 요청 전 배포 문제가 있으면 먼저 Luna가 `false`인지 확인한다. 이전 환경과 이미지를 되돌리는 재배포도 별도 직전 사용자 확인 대상이다.
- rollback 확인을 받은 뒤, 보호한 `luna.env.before`를 복원하고 보존한 image ID를 원래 Compose image ref로 다시 tag한 다음 `web`·`analysis-worker`만 `--no-deps --no-build --force-recreate`한다. 전체 DB 복구는 다른 사람의 이후 변경을 잃을 수 있으므로 이 runbook에서 자동 수행하지 않는다.
- 실제 attempt가 `running`이면 image rollback이나 worker 재생성을 하지 않는다. 종결을 기다리거나 별도 장애 판단을 받는다.
- `docker compose down -v`, volume 삭제, schema downgrade, SQL UPDATE/DELETE, 원응답 삭제, hosted OpenAI fallback은 사용하지 않는다.

롤백 명령의 대상은 1단계에서 저장한 값으로만 정한다.

```bash
# 별도 롤백 확인을 받은 뒤에만 실행
install -m 600 "$ops_dir/luna.env.before" env/luna.env
docker image tag "bidops-rollback/web:luna-v4-${release_stamp}" "$web_image_ref_before"
docker image tag "bidops-rollback/analysis-worker:luna-v4-${release_stamp}" "$analysis_image_ref_before"
"${luna_compose[@]}" config --quiet
"${luna_compose[@]}" up -d --no-deps --no-build --force-recreate \
  web analysis-worker
curl --fail --silent --show-error \
  "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health" >/dev/null
"${luna_compose[@]}" ps web analysis-worker codex-runner
```

롤백 뒤에도 안전한 flag 네 개만 Compose와 컨테이너에서 확인하며 전체 env/config를 출력하지 않는다.
