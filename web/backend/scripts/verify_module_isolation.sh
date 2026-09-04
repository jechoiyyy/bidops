#!/usr/bin/env bash
#
# 명세 §2 완료 기준 6 / §13 검증 스크립트.
#
#   "네 모듈 모두(lifecycle 포함) 자기 테스트가 형제 도메인 모듈 폴더(app과 tests
#    양쪽) 없이 수집·통과한다. core는 항상 있고, lifecycle은 screening·deep_review의
#    전제이므로 있어도 된다."
#
# 그래서 세 조합을 돌린다.
#
#   lifecycle    : screening·deep_review 없이 `tests/lifecycle`
#   screening    : deep_review 없이 `tests/screening`   (lifecycle은 전제라 남긴다)
#   deep_review  : screening 없이 `tests/deep_review`   (lifecycle은 전제라 남긴다)
#
# 원본 트리는 절대 건드리지 않는다. 조합마다 임시 디렉터리로 복사한 뒤 그 복사본
# 에서만 지우고, 끝나면 임시 디렉터리를 지운다. `.venv`는 symlink 그대로 복사되어
# 재사용된다(재설치하지 않는다).
#
# 형제 모듈에서 `app/<module>/models.py` **한 파일만** 남긴다. 명세 §3이 유일한
# 예외로 열거한 대로 `alembic/env.py`와 모든 migration revision이 네 모듈의
# `models`를 import해 `Base.metadata`를 완성하기 때문이다. `__init__.py`는 지우므로
# `app.screening`은 namespace package가 되어 `from ...screening import current_judgment`
# 같은 공개 표면 접근은 그대로 실패한다 — 즉 격리의 강도는 줄지 않고, PostgreSQL
# harness의 alembic migration만 살아난다.
#
# PostgreSQL: 모듈 테스트 폴더만 지정하면 harness가 뜨지 않아 postgres 표시 테스트가
# 조용히 skip된다(`tests/postgres.py:postgres_harness_requested`). 그래서 이 스크립트는
# 폐기 가능한 PostgreSQL 17 컨테이너를 직접 띄워 `BIDOPS_TEST_POSTGRES_URL`로 넘긴다.
# Docker가 없거나 `--no-postgres`를 주면 postgres 없이 돌리고, **어떤 테스트가 왜
# skip됐는지 조합마다 출력한다**(조용한 skip을 만들지 않는다).
#
# 사용법:
#   web/backend/scripts/verify_module_isolation.sh [--no-postgres] [--keep]
#
# 종료 코드: 세 조합이 모두 통과하면 0, 하나라도 실패하면 1.
#
set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${BACKEND_ROOT}/../.." && pwd)"

USE_POSTGRES=1
KEEP_TREES=0
for arg in "$@"; do
    case "$arg" in
        --no-postgres) USE_POSTGRES=0 ;;
        --keep) KEEP_TREES=1 ;;
        -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "알 수 없는 인자: $arg" >&2; exit 2 ;;
    esac
done

# 조합 정의: "<모듈>:<지울 형제들(콤마)>"
COMBINATIONS=(
    "lifecycle:screening,deep_review"
    "screening:deep_review"
    "deep_review:screening"
)

# 이주 이전부터 있던 기존 결함. 회귀가 아니므로 조합 판정에서 제외하되 **항상
# 출력한다**. 여기 없는 실패가 하나라도 있으면 그 조합은 실패다.
# 2026-09-04 전체 suite(`2 failed, 1240 passed, 5 skipped`)의 그 2건과 같다.
# 둘 다 `'실패' == '부분 성공'` 단언이며 이주와 무관하다.
KNOWN_FAILURES=(
    "tests/screening/test_screening_orchestrator.py::test_full_run_continues_after_one_notice_failure_and_publishes_partial"
    "tests/screening/test_screening_orchestrator.py::test_partial_rejudgment_retains_prior_projection_and_revision"
)

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/bidops-module-isolation.XXXXXX")"
PG_CONTAINER=""

cleanup() {
    if [ -n "$PG_CONTAINER" ]; then
        docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
    fi
    if [ "$KEEP_TREES" -eq 0 ]; then
        rm -rf "$WORKDIR"
    else
        echo "임시 트리를 남긴다: $WORKDIR"
    fi
}
trap cleanup EXIT INT TERM

start_postgres() {
    if [ -n "${BIDOPS_TEST_POSTGRES_URL:-}" ]; then
        echo "PostgreSQL: 호출자가 준 BIDOPS_TEST_POSTGRES_URL을 쓴다"
        return 0
    fi
    if ! command -v docker >/dev/null 2>&1; then
        echo "PostgreSQL: docker가 없다 → postgres 표시 테스트는 skip된다"
        return 1
    fi
    local password port cid
    password="$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    cid="$(docker run -d --rm -e POSTGRES_PASSWORD="$password" \
        -p 127.0.0.1:0:5432 postgres:17.11 2>/dev/null)" || return 1
    PG_CONTAINER="$cid"
    port="$(docker port "$cid" 5432/tcp 2>/dev/null | head -1 | sed 's/.*://')"
    if [ -z "$port" ]; then
        echo "PostgreSQL: 포트를 얻지 못했다 → postgres 표시 테스트는 skip된다"
        return 1
    fi
    local i
    for i in $(seq 1 60); do
        docker exec "$cid" pg_isready -U postgres >/dev/null 2>&1 && break
        sleep 1
    done
    if ! docker exec "$cid" pg_isready -U postgres >/dev/null 2>&1; then
        echo "PostgreSQL: 컨테이너가 준비되지 않았다 → postgres 표시 테스트는 skip된다"
        return 1
    fi
    export BIDOPS_TEST_POSTGRES_URL="postgresql+psycopg://postgres:${password}@127.0.0.1:${port}/postgres"
    echo "PostgreSQL: 폐기 가능한 postgres:17.11 컨테이너 ${cid:0:12} (127.0.0.1:${port})"
    return 0
}

if [ "$USE_POSTGRES" -eq 1 ]; then
    start_postgres || echo "PostgreSQL 없이 계속한다."
else
    unset BIDOPS_TEST_POSTGRES_URL || true
    echo "PostgreSQL: --no-postgres → postgres 표시 테스트는 skip된다"
fi
echo

echo "기존 결함으로 허용하는 실패 (조합 판정에서 제외):"
for known in "${KNOWN_FAILURES[@]}"; do
    echo "  - $known"
done
echo

overall=0
declare -a SUMMARY_LINES=()

for entry in "${COMBINATIONS[@]}"; do
    module="${entry%%:*}"
    siblings="${entry#*:}"

    echo "================================================================"
    echo "조합: ${module} (지우는 형제 모듈: ${siblings//,/, })"
    echo "================================================================"

    tree="${WORKDIR}/${module}"
    mkdir -p "$tree"
    # `.git`은 빼되 gitignore된 파일은 모두 가져온다. `experiments/order-plan-screening/
    # review-inputs/{company,prompts}/`가 gitignore되어 있고 선별 테스트가 그것을 읽는다.
    rsync -a \
        --exclude '.git' \
        --exclude '__pycache__' \
        --exclude '.pytest_cache' \
        --exclude 'node_modules' \
        "${REPO_ROOT}/" "${tree}/" || { echo "복사 실패"; overall=1; continue; }

    backend="${tree}/web/backend"
    for sibling in ${siblings//,/ }; do
        # app/<sibling>: models.py 한 파일만 남긴다 (§3 alembic 예외).
        find "${backend}/app/${sibling}" -mindepth 1 -maxdepth 1 \
            ! -name 'models.py' -exec rm -rf {} + || true
        # tests/<sibling>: 통째로 지운다.
        rm -rf "${backend}/tests/${sibling}"
        echo "  지웠다: app/${sibling}/* (models.py 제외), tests/${sibling}/"
    done
    echo "  남은 app/ 도메인 폴더:"
    for candidate in core lifecycle screening deep_review; do
        printf '    app/%-12s %s\n' "$candidate" "$(ls "${backend}/app/${candidate}" 2>/dev/null | tr '\n' ' ' | cut -c1-70)"
    done
    echo "  남은 tests/ 도메인 폴더: $(ls -d "${backend}"/tests/*/ 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ')"
    echo

    log="${WORKDIR}/${module}.log"
    (
        cd "$backend" && \
        .venv/bin/python -m pytest "tests/${module}" -q -p no:cacheprovider -rfEs
    ) > "$log" 2>&1
    pytest_exit=$?

    # pytest -q의 마지막 집계 줄("... in 12.34s"). 없으면 마지막 비어 있지 않은 줄.
    summary="$(grep -E 'in [0-9]+\.[0-9]+s' "$log" | tail -1)"
    [ -z "$summary" ] && summary="$(grep -v '^[[:space:]]*$' "$log" | tail -1)"
    [ -z "$summary" ] && summary="(요약 줄 없음)"

    echo "--- skip 내역 (조용한 skip을 만들지 않는다) ---"
    if grep -q '^SKIPPED' "$log"; then
        grep '^SKIPPED' "$log"
    else
        echo "  skip 없음"
    fi
    echo

    echo "--- 실패 내역 ---"
    mapfile -t failures < <(grep -E '^(FAILED|ERROR) ' "$log" || true)
    if [ "${#failures[@]}" -eq 0 ]; then
        echo "  실패 없음"
    else
        printf '  %s\n' "${failures[@]}"
    fi

    unexpected=0
    for line in "${failures[@]}"; do
        node="${line#FAILED }"; node="${node#ERROR }"; node="${node%% *}"
        allowed=0
        for known in "${KNOWN_FAILURES[@]}"; do
            [ "$node" = "$known" ] && allowed=1 && break
        done
        if [ "$allowed" -eq 0 ]; then
            echo "  ↑ 회귀: $node"
            unexpected=$((unexpected + 1))
        else
            echo "  ↑ 기존 결함으로 허용: $node"
        fi
    done
    echo

    if [ "$unexpected" -eq 0 ] && grep -qE '(passed|no tests ran)' "$log"; then
        verdict="PASS"
    else
        verdict="FAIL"
        overall=1
    fi

    echo "조합 ${module}: ${verdict} (pytest exit=${pytest_exit})"
    echo "  요약: ${summary}"
    echo
    SUMMARY_LINES+=("${verdict}  ${module}  pytest exit=${pytest_exit}  ${summary}")
done

echo "================================================================"
echo "기준 6 결과"
echo "================================================================"
for line in "${SUMMARY_LINES[@]}"; do
    echo "  $line"
done
echo
if [ "$overall" -eq 0 ]; then
    echo "전체: PASS"
else
    echo "전체: FAIL"
fi
exit "$overall"
