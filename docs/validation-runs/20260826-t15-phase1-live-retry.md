# T15 Phase 1 generation-bound live retry

검증일: 2026-08-26 (KST)

이 기록은 `20260826-t15-phase1-live-smoke.md`의 실패 증거를 보존한 채, generation binding 수정 후 승인된 단일 live 재검증과 조건부 stop smoke를 별도 기록한다. Phase 2/3 gate, 40건 A/B 평가, policy activation, always-on/scheduler enable은 이 실행에서 수행하지 않았다.

## 결론

- exact Ollama preflight가 통과했다. endpoint는 `http://192.168.0.139:11434`, tag는 `qwen3.8:27b`, `/api/tags` digest는 `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`이다.
- current-profile 단일 실행 `scr-72a1ae87342d4d4485fbb467b0e4d3fa`는 `성공`했다. 7개 logical stage(5 perspectives + counterargument + synthesis)를 충족했고, synthesis는 첫 schema violation 뒤 bounded retry가 성공했다.
- 위 성공 조건을 확인한 뒤 별도 execution `scr-650cd5e1eea04205b8ffffeaa789df7f`에서 stop smoke를 수행했다. 실제 worker가 `counterargument` 호출 중일 때 stop을 한 번 요청했고, 현재 호출 종료 후 새 stage 없이 terminal `중단됨`이 됐다. synthesis span은 생성되지 않았다.
- 두 execution 모두 정확한 generation digest를 DB·input/decision·telemetry에 결합했다. raw DB/artifact/log는 전용 runtime에 그대로 보존했다.

## 범위와 격리

전용 runtime root는 다음으로 고정했다.

`/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase1-retry`

Phase1 DB/data/log는 이 root 아래에만 만들었다. `BIDOPS_ROOT`, `BIDOPS_DATA_DIR`, `BIDOPS_DATABASE_URL`, `BIDOPS_ATTACHMENTS_DIR` 모두 retry root 경계를 가리켰다. 운영/기존 `web/data/bidops.db`는 사용하거나 수정하지 않았다. current profile은 원본을 수정하지 않고 retry root의 read-only `docs/reference/company-profile.md`로 복사했다.

실행 환경의 의미 있는 값은 다음과 같다.

```text
BIDOPS_OLLAMA_BASE_URL=http://192.168.0.139:11434
BIDOPS_OLLAMA_MODEL=qwen3.8:27b
BIDOPS_LIVE_OLLAMA_TEST=true
BIDOPS_SCHEDULER_ENABLED=false
BIDOPS_OLLAMA_CONTEXT_SIZE=16384
BIDOPS_OLLAMA_MAX_OUTPUT_TOKENS=2048
BIDOPS_OLLAMA_SYNTHESIS_MAX_OUTPUT_TOKENS=4096
BIDOPS_SCREEN_MAX_CONCURRENCY=1
```

모델 identity 확인 전에는 모델 호출을 하지 않았다. `think=false`, `stream=false`는 generation config, DB attempts, Ollama telemetry에서 확인했다. OpenAI/vLLM/fake fallback은 사용하지 않았다.

## Preflight, migration, seed, ingest

짧은 간격의 endpoint preflight에서 exact `/api/tags` 응답의 required tag와 64-hex digest를 확인한 뒤에만 live 작업을 진행했다. canonical generation config는 다음이며 digest는 `51f1878845ed282b20e9c074ca29adbb5ce0a208c89ffae51425a2565ad5dfd1`이다.

```json
{"schema_version":"bidops.generation-config.v1","num_ctx":16384,"num_predict":{"perspective":2048,"counterargument":2048,"synthesis":4096},"think":false,"stream":false}
```

fresh SQLite에 Alembic head `0005_generation_config_binding`까지 명시적으로 migrate했다. policy는 actor `t15-validation`으로 명시적으로 seed했고 상태는 `activation_candidate`, version은 `screening-policy.v1.20260825`, content digest는 `954f8275f8737183885d5007597f2d4c785b10d8720031d38015008f4c9c1289`이다. tracked run `20260817-20260823`을 validation input/기준 데이터로 ingest한 DB run ID는 `20260817-20260823--20260824T090927.138116Z`이며 notices 40, historical judgments 40, reviews 0이다.

입력 선택은 임의 데이터가 아닌 frozen validation-set과 collection correspondence가 확인된 첫 notice `bid:R26BK01689645:000`으로 했다. stop smoke에는 같은 tracked run의 다른 deterministic validation notice `bid:R26BK01684997:000`을 사용해 첫 실행과 중복되지 않도록 했다.

입력 원본 SHA-256:

| source | SHA-256 |
|---|---|
| `data/runs/20260817-20260823/validation-set.json` | `2ea6a21e6b121f691195bbc891b8ec7766817f821d6b343c20b12b608f3e47e3` |
| `data/runs/20260817-20260823/screening-decisions.json` | `69a444e5ec9846c592de4b454472817477abaa4a109c97dbe84787dff9c6789d` |
| `data/runs/20260817-20260823/screening-results.json` | `fb9160602771ff057b708d69b197b9fc7e464f9e021615a7ebaa83a94733903b` |
| `data/runs/20260817-20260823/collected-notices.json` | `ec5021f5e09c6c15ccde090998df39b57dfdaf728f7a30a1bf24c8f1f1d98ce0` |
| retry profile snapshot | `96731dd5f77d0183f51d7eae8e4be6c1f5f91b00feed1a7748092db46def053e` |

재현 시에는 다음처럼 전용 root와 validated DB run ID를 사용한다(원문 profile/prompt를 출력하지 않는다).

```bash
cd /home/jechoi/projects/side/bidops-agent/.dryforge/worktrees/T15/bidops-agent
export BIDOPS_ROOT=/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase1-retry
export BIDOPS_DATA_DIR=$BIDOPS_ROOT/data
export BIDOPS_ATTACHMENTS_DIR=$BIDOPS_DATA_DIR/attachments
export BIDOPS_DATABASE_URL=sqlite:////home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase1-retry/phase1-db/bidops.db
export BIDOPS_OLLAMA_BASE_URL=http://192.168.0.139:11434 BIDOPS_OLLAMA_MODEL=qwen3.8:27b
export BIDOPS_LIVE_OLLAMA_TEST=true BIDOPS_SCHEDULER_ENABLED=false
python -m app.screening.cli run-one --run-id 20260817-20260823--20260824T090927.138116Z \
  --notice-id bid:R26BK01689645:000 --policy-version screening-policy.v1.20260825 \
  --profile-source current --requested-by t15-validation --wait
```

## 단일 live execution

시작 `2026-08-26T11:57:04Z` / `2026-08-26 20:57:04 KST`, 종료 `2026-08-26T11:59:36Z` / `2026-08-26 20:59:36 KST`이다. CLI 결과는 `성공`이며 candidate 1, completed 1, failures 0, published run ID 없음이다. `single_notice`는 derived full-run `screening-results.json`을 publish하지 않으므로 해당 파일 부재는 성공 결과의 누락이 아니다.

| binding | value |
|---|---|
| execution | `scr-72a1ae87342d4d4485fbb467b0e4d3fa` |
| notice | `bid:R26BK01689645:000` |
| source run | `20260817-20260823--20260824T090927.138116Z` |
| status | `성공` |
| model/tag | `qwen3.8:27b` |
| model digest | `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643` |
| profile | `company-profile.sha256:96731dd5f77d0183f51d7eae8e4be6c1f5f91b00feed1a7748092db46def053e` |
| policy / prompt | `screening-policy.v1.20260825` / `screening-prompt.v1` |
| input artifact digest | `b14856eb2ee1b29c7ef1673a6533ffa9c7382f978d1c919566f2b388ab82ff5c` |
| generation digest | `51f1878845ed282b20e9c074ca29adbb5ce0a208c89ffae51425a2565ad5dfd1` |

8 attempts가 7 unique logical stage를 구성했다. 모든 attempt/telemetry line에 동일 generation digest가 있고, telemetry에는 prompt/response 원문이 없다. 첫 synthesis attempt의 `schema_violation`은 그대로 기록됐고 두 번째 bounded attempt가 성공했다.

| logical stage | attempt | result | prompt/output tokens | total / eval / load (ns) |
|---|---:|---|---:|---:|
| 기술 적합성 | 1 | success | 593 / 301 | 17,273,408,998 / 4,908,710,000 / 11,582,595,222 |
| 실적 정합성 | 1 | success | 587 / 301 | 7,172,496,179 / 5,275,660,000 / 886,713,990 |
| 공공 SI 적합성 | 1 | success | 845 / 485 | 10,149,565,443 / 7,952,359,000 / 952,144,704 |
| 사업성·자격 제약 | 1 | success | 459 / 319 | 6,954,835,365 / 5,073,970,000 / 917,311,310 |
| 전략 부합 | 1 | success | 723 / 266 | 6,537,944,282 / 4,483,901,000 / 961,900,742 |
| counterargument | 1 | success | 2,178 / 283 | 9,871,505,585 / 6,382,155,000 / 933,271,101 |
| synthesis | 1 | `schema_violation` | 2,519 / 2,533 | 42,648,581,975 / 38,769,811,000 / 911,685,059 |
| synthesis | 2 | success | 2,546 / 3,076 | 49,714,736,919 / 46,900,788,000 / 943,916,448 |

v3 decisions artifact에는 judgment 1건이 있고 `validate_judgment()` read-only 검증을 통과했다. terminal failure artifact는 생성되지 않았다.

## Stop smoke

단일 live 성공과 7-span 확인 후에만 stop smoke를 수행했다. second notice로 execution `scr-650cd5e1eea04205b8ffffeaa789df7f`를 FIFO에 넣고 실제 worker를 실행했다. `2026-08-26T12:03:39.630585Z` / `21:03:39.630585 KST`에 DB에서 status `실행 중`, current stage `counterargument`, attempts 6을 확인한 뒤 actor `t15-validation`으로 stop을 정확히 한 번 요청했다. 요청 reason은 `user_requested`이다.

counterargument 호출은 stop 요청 시점에 이미 in-flight였고 `12:03:40.438928Z`에 종료됐다. 그 뒤 새 stage가 시작되지 않았으며 synthesis attempt는 0건이다. worker terminal은 `중단됨`으로 기록됐다.

| binding | value |
|---|---|
| execution | `scr-650cd5e1eea04205b8ffffeaa789df7f` |
| notice | `bid:R26BK01684997:000` |
| started / finished | `2026-08-26T12:02:50.025253Z` / `2026-08-26T12:03:40.459242Z` |
| terminal status | `중단됨` |
| attempts | 6; 5 perspectives + counterargument |
| completed / failures | 0 / 0 |
| stop actor / reason | `t15-validation` / `user_requested` |
| synthesis | 0 attempts; no new stage after stop request |

stop execution의 6 attempts 모두 success이고 동일 generation digest 및 perspective/counterargument `num_predict=2048` binding이다. partial v3 decisions와 response files는 보존했고 publish 결과는 없다.

## Artifact 및 DB 증거

모든 경로는 retry root 상대 경로다.

| relative path | SHA-256 |
|---|---|
| `data/screening-executions/scr-72a1ae87342d4d4485fbb467b0e4d3fa/screening-input.json` | `b14856eb2ee1b29c7ef1673a6533ffa9c7382f978d1c919566f2b388ab82ff5c` |
| `data/screening-executions/scr-72a1ae87342d4d4485fbb467b0e4d3fa/screening-decisions.json` | `26977b4baa842a9b3b3de7838b925399e411b671d433c5c6494c88ec024ac318` |
| `data/screening-executions/scr-72a1ae87342d4d4485fbb467b0e4d3fa/screening-telemetry.jsonl` | `b3b203f79f827e1a25b8ec6824949eb62e41b7ffbaa6bae358a0ba8416b07f45` |
| `data/screening-executions/scr-650cd5e1eea04205b8ffffeaa789df7f/screening-input.json` | `e05fe528e6996c52880e84f7ace77e5bb2a30e3fae91e22c96a2d03084582e0d` |
| `data/screening-executions/scr-650cd5e1eea04205b8ffffeaa789df7f/screening-decisions.json` | `baf10c5445187993994c4580e909e257bf3322ede3ad5d1bb48607bc76087c0a` |
| `data/screening-executions/scr-650cd5e1eea04205b8ffffeaa789df7f/screening-telemetry.jsonl` | `e6e04672de11d5f28653d46f278005a8519ded10650fa481ad1845a107040dcb` |
| `web/data/profile-snapshots/96731dd5f77d0183f51d7eae8e4be6c1f5f91b00feed1a7748092db46def053e.md` | `96731dd5f77d0183f51d7eae8e4be6c1f5f91b00feed1a7748092db46def053e` |
| `phase1-db/bidops.db` | `dc5074fcabe8d9b3ab8bbdd8d30c8c6fbd36cbd43853e475fea3daa370cfc03c` |

성공 execution response artifact hashes:

```text
responses/0133d6d76c9b9944/기술 적합성-1.json  bc712c7db5f924e8219f2bcf8bfcff3455e65669711d36e9bc48bfd6cb0e36df
responses/0133d6d76c9b9944/실적 정합성-1.json  c5015866dcad6f3b3493965ff40b2655f982fe4809d3ecb7e5b9b0015f0f9c4b
responses/0133d6d76c9b9944/공공 SI 적합성-1.json  344d78c1ebbd1e3a794fb39ba769e5bf33ddfc02360f3eb664a90accea7a055d
responses/0133d6d76c9b9944/사업성·자격 제약-1.json  fa6f7a11cc20549345d301fbc5470b7dd1df3015395026c257ff68041615e669
responses/0133d6d76c9b9944/전략 부합-1.json  61a17148e9f1aa5095d1145217544454efe116df06d2c71254f96cefed6425fa
responses/0133d6d76c9b9944/counterargument-1.json  8f19c00786f8f8efe77374573b6c202583b0ef70a867fcacf34f7d686284d379
responses/0133d6d76c9b9944/synthesis-2.json  5a77fd106fc76c45cf20ab8c94de2652bc6f2997f6246d850c19160fbb6bd21d
```

stop execution response artifact hashes:

```text
responses/25878a45ee9c8012/기술 적합성-1.json  a43b2d33233f25f25dfe01f1fbe0b01b156bd48a60b4e8c8cc691f6d9a778ec3
responses/25878a45ee9c8012/실적 정합성-1.json  0f263889c84a0638a35540be5e10066be9b6ebb751ef9ca6f7f2f9ac32383d82
responses/25878a45ee9c8012/공공 SI 적합성-1.json  fa00ef84f111dc2943d39c2fe7c179d66f5f9062e2eb966588c424ae663e0e6d
responses/25878a45ee9c8012/사업성·자격 제약-1.json  6ea360d7811a5285ac0af1adce1103d9be216296a10e343a1f1a008bca29b046
responses/25878a45ee9c8012/전략 부합-1.json  e7a210226aa605c3541e25b0ed10ddeb7e81e9a494ce2c84ff689ec707565e34
responses/25878a45ee9c8012/counterargument-1.json  b7d34b1f910a0cad8d2c201eb0db3d8f7c7fd4933a8b34ccf367a0b57d7ffd9d
```

실행 전 guard 확인에서 source-directory run ID `20260817-20260823`를 DB validated run ID 대신 사용한 첫 CLI 입력은 `input_error`/`실패`로 거절됐다(2026-08-26T11:55:09Z). 이 guard는 model call과 execution row를 만들지 않았다. 즉시 validated DB run ID로 교정했고, 위 success execution은 실제 live 호출 1회다. 이 실패 및 수정은 숨기지 않고 `phase1-logs/05-run-one.log`에 보존했다.

runtime log SHA-256:

| log | SHA-256 |
|---|---|
| `phase1-logs/01-alembic-upgrade.log` | `bcf0801d445a3b24044191085491bf3cf1c791e4b5a12d3f545e6c281537b63c` |
| `phase1-logs/02-policy-seed.log` | `d5f743d3d2d24ed523a780dca1d622544a20b692104f1f10b0fd3a11f5e694cc` |
| `phase1-logs/03-ingest-run.log` | `4c558f382226ea21257ce41b3a1baf533b1fa5be216d8dbc8754f8833f85b3b8` |
| `phase1-logs/04-pre-run-state.log` | `653da92e22fcc16183ba0c81026de812ef97cf11392430c231527bca0d30b5c4` |
| `phase1-logs/05-run-one.log` | `be8e2100569caaeb8a5a29a88b6396e1378962552346045db98a14fee97505d6` |
| `phase1-logs/06-run-one-live.log` | `9c9b46b97bf8cf408d0d240f6b6fca2bedf2e8429a549d1e286e937a9da007f4` |
| `phase1-logs/07-stop-create.log` | `2058c8b7c6b76b2c4a5fb15cd9d07dcca2a2a72bfeaaec27f61ebd90dcb4ee4a` |
| `phase1-logs/09-stop-request.log` | `035e1fbd3d3650b2eb1ddc71723a4c895e3895f6c89911ed68db410c90ef3253` |

## 시작·종료 상태 및 남은 범위

pre-run과 final DB query에서 모두 다음 경계를 확인했다.

- Alembic head: `0005_generation_config_binding`
- policy: `activation_candidate`, active slot 없음, actor `t15-validation`
- always-on: `enabled=false`
- schedule setting: `prespec_enabled=false`
- scheduler env: `BIDOPS_SCHEDULER_ENABLED=false`
- quality gate / schedule execution: 0 rows
- generation digest: expected value와 일치

이번 기록은 generation binding과 stop semantics의 Phase 1 증거다. historical prior smoke의 synthesis truncation failure는 [기존 기록](20260826-t15-phase1-live-smoke.md)에 그대로 남아 있으며, 이번 success에서는 첫 synthesis schema violation 후 retry success가 확인됐다. 이 사실만으로 policy activation, always-on, scheduler enable 또는 Phase 2/3 gate를 승인하지 않는다.
