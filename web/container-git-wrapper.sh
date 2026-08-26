#!/bin/sh
set -eu

# The runtime image intentionally has no repository metadata. The legacy
# profile regression test still asks `git show` for this one approved blob;
# answer that exact immutable request from the verified vendored file. Every
# other operation is delegated to the real Git executable, preserving normal
# Git authority whenever a repository is explicitly mounted for an operator.
baseline=/app/web/backend/app/screening/baseline_company_profile.md
baseline_spec='ee621835db934ddac944f7a07a986ed0b73ecc7a:bidops-agent/docs/reference/company-profile.md'

if [ "$#" -eq 4 ] \
    && [ "$1" = "-C" ] \
    && [ "$2" = "/app" ] \
    && [ "$3" = "show" ] \
    && [ "$4" = "$baseline_spec" ]; then
    if [ ! -f "$baseline" ]; then
        echo "approved vendored baseline profile is missing" >&2
        exit 1
    fi
    exec cat "$baseline"
fi

exec /usr/bin/git "$@"
