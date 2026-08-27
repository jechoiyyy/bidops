# T15 Phase 2 `model_comparison` live A/B 검증

검증일: 2026-08-26 (KST)  
실행 구간: 2026-08-26T12:26:33Z–2026-08-26T12:29:27Z / 2026-08-26 21:26:33–21:29:27 KST

## 결론

Phase 2 A/B는 시작되지 않았다. 모델 호출 전에 `QualityGateService.create_gate()`의 고정 회차 전검증이 실패했다. 첫 실패 뒤에는 live 호출을 하지 않았고, 같은 no-write 전검증 오류와 전후 row count를 확인하는 재현 명령만 1회 수행했다. gate·pass A·pass B·evaluation 행과 Phase 2 artifact는 생성되지 않았다. 따라서 Phase 2의 성공/실패 수, retry, latency/token aggregate, quality metrics는 **미측정**이다.

재현된 결함은 다음과 같다.

- 구현이 허용하는 고정 gate 회차 ID: `20260817-20260823`
- 검증 DB에 실제 존재하는 유일한 run ID: `20260817-20260823--20260824T090927.138116Z`
- 호출: `QualityGateService.create_gate(purpose="model_comparison", policy_version="screening-policy.v1.20260825", profile_source="git:ee621835db934ddac944f7a07a986ed0b73ecc7a", created_by="t15-validation")`
- 결과: `QualityGateValidationError: quality gate run or policy is missing`
- 전검증 전후 `quality_gate=0`, `screening_execution=2`로 유지

이 기록은 Phase 2 실제 gate 결과나 T15 전체 완료를 주장하지 않는다. 정책 활성화, always-on, scheduler, Phase 3 gate는 수행하지 않았다.

## 사전 검증과 고정 binding

검증 root는 `/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase1-retry`로 고정했다. 운영 DB는 사용하지 않았다. `/api/tags`에서 모델 호출 전 다음 exact identity를 확인했다.

| binding | 값 |
|---|---|
| endpoint | `http://192.168.0.139:11434` |
| model tag | `qwen3.8:27b` |
| model digest | `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643` |
| live marker | `BIDOPS_LIVE_OLLAMA_TEST=true` |
| scheduler | `BIDOPS_SCHEDULER_ENABLED=false` |
| max concurrency | `1` |
| generation digest | `51f1878845ed282b20e9c074ca29adbb5ce0a208c89ffae51425a2565ad5dfd1` |
| generation config | `num_ctx=16384`, perspective/counterargument `2048`, synthesis `4096`, `think=false`, `stream=false` |
| policy | `screening-policy.v1.20260825`, `activation_candidate` |
| policy content digest | `954f8275f8737183885d5007597f2d4c785b10d8720031d38015008f4c9c1289` |
| prompt version | `screening-prompt.v1` |
| required profile source | `git:ee621835db934ddac944f7a07a986ed0b73ecc7a` |
| baseline profile blob digest | `a231ab54c36031a7e72779bbca550f70561dc0c946dc5544eeb930c7c6149de2` |

결정론적 fixed input validator는 실제 모델 호출 전에 통과했다.

- validation set: schema `bidops.validation-set.v2`, exactly 40 unique notices
- baseline: schema `bidops.decisions.v2`, exactly 40 historical decisions
- sample order: baseline과 정확히 일치
- sample SHA-256: `2ea6a21e6b121f691195bbc891b8ec7766817f821d6b343c20b12b608f3e47e3`
- baseline decisions SHA-256: `69a444e5ec9846c592de4b454472817477abaa4a109c97dbe84787dff9c6789d`
- ordered notice-ID digest: `34061f9c3d9fe0b45b55944d0645882d692ec27e907341a81ac4ec28d865f5ca`
- source window: `2026-08-17`–`2026-08-23`, `Asia/Seoul`

Gate가 생성되지 않아 pass A/B의 40건 `quality_sample` frozen input, input metadata digest, historical profile snapshot row, model/policy/prompt/generation binding 비교와 FIFO 실행은 수행할 수 없었다. 모델 호출 수는 0이다.

## 시작·종료 상태

| 항목 | 시작 | 종료 |
|---|---:|---:|
| Alembic head | `0005_generation_config_binding` | `0005_generation_config_binding` |
| run / notice / judgment | 1 / 40 / 40 | 1 / 40 / 40 |
| 기존 execution | 2 terminal | 2 terminal |
| quality gate / evaluation / review | 0 / 0 / 0 | 0 / 0 / 0 |
| policy | `activation_candidate` | `activation_candidate` |
| always-on | `false` | `false` |
| schedule prespec | `false` | `false` |
| schedule execution | 0 | 0 |
| DB integrity | `quick_check=ok`, FK 위반 0 | `quick_check=ok`, FK 위반 0 |

기존 Phase 1 execution은 새로 만들거나 변경하지 않았다.

| queue | execution ID | scope/trigger | status | candidate/completed/failure |
|---:|---|---|---|---:|
| 1 | `scr-72a1ae87342d4d4485fbb467b0e4d3fa` | `single_notice` / `cli_single` | `성공` | 1 / 1 / 0 |
| 2 | `scr-650cd5e1eea04205b8ffffeaa789df7f` | `single_notice` / `cli_single` | `중단됨` | 1 / 0 / 0 |

Phase 2에는 queue 3/4, gate ID, pass A/B execution ID, evaluation ID가 **할당되지 않았다**. 따라서 7 logical stage/attempt/retry/failure, immutable result/telemetry, timings/tokens, endpoint interruption은 모두 `미측정`이며 이를 성공 또는 실패 수치로 추정하지 않는다.

## 보존한 백업과 증거

SQLite backup API로 만든 백업과 별도 안전 복사본을 다음 ignored runtime에 보존했다.

`/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase2-backup`

| artifact | SHA-256 |
|---|---|
| `phase2-initial.db` | `da6af6643938ca3487b0354836ec7f816dac343968e4812f57bb099b70f4191f` |
| `phase2-initial.db.manifest.json` | `6c43cf238c26d88369ac50ff08f1c68552994d46be473268e03fbb95f0b3bb44` |
| `phase1-source-copy.db` | `dc5074fcabe8d9b3ab8bbdd8d30c8c6fbd36cbd43853e475fea3daa370cfc03c` |
| `phase2-preflight.log` | `6288ae5760c5fb51eeab8ab8337cff944eb9235a67b2d3dbe2ccec09706b798f` |
| `phase2-gate-defect-repro.log` | `76233545e814ecf0292f6e0ad79058902a0c8876128e3b9e719a479990ee2d9a` |
| `phase2-final-state.log` | `34d7882bdbe4b8b46c8d3c7dd619834c7a15706f372848daf35b0b36e29c675a` |

기존 Phase 1 raw DB/artifact/log는 삭제하지 않았다. Phase 2 실패 전후 DB SHA-256은 `dc5074fcabe8d9b3ab8bbdd8d30c8c6fbd36cbd43853e475fea3daa370cfc03c`로 동일하다. Phase 2 artifact directory는 생성되지 않았고 기존 두 execution directory만 남아 있다.

## 활성화 경계와 blocker

`model_comparison`은 원래도 정책 활성화 근거가 아니다. 이번 실행에서는 해당 gate 자체가 생성되지 않았으므로 `통과/미달/보류/미측정` evaluation 결과를 만들거나 refresh할 수 없었다. 사람 review도 만들지 않았다. 운영 정책은 계속 `activation_candidate`, always-on과 scheduler는 계속 `false`다.

재개 조건은 구현 결함을 고쳐 실제 DB의 imported run ID와 fixed gate contract를 일치시키는 별도 코드 변경 및 검증 승인이다. 그 전에는 같은 runtime에서 gate 또는 live 실행을 재시도하지 않는다.

## 2026-08-27 Phase 2 live retry — `BLOCKED` (localhost preflight)

### 결론

이번 재시도는 모델 호출·gate 생성 전에 중단됐다. 승인된 endpoint
`http://127.0.0.1:11434/api/tags`가 연결을 거부해 2xx 응답과 exact model
identity를 확인할 수 없었다. 지침에 따라 다른 포트, 원격 Ollama, OpenAI 호환
endpoint, 대체 모델을 사용하지 않았고 gate·evaluation·execution·review 행을
만들지 않았다. 최종 상태는 `BLOCKED`이며 성공으로 보정하지 않는다.

모델 preflight 증거는 다음 시각(UTC/KST)에 남겼다.

- 시작: `2026-08-27T00:14:52.658970+00:00` /
  `2026-08-27T09:14:52.658970+09:00`
- 종료: `2026-08-27T00:14:52.691494+00:00` /
  `2026-08-27T09:14:52.691494+09:00`
- 결과: `URLError: [Errno 111] Connection refused`, curl-equivalent exit `7`
- 증거: `/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase2-live-retry-20260827/phase2-logs/00-model-preflight.log`

### 고정 binding과 read-only source preflight

| 항목 | 값 |
|---|---|
| endpoint policy | `http://127.0.0.1:11434` only |
| endpoint requested | `http://127.0.0.1:11434/api/tags` |
| required model tag | `qwen3.8:27b` |
| required model digest | `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643` |
| observed HTTP/model metadata | unavailable (connection refused before response) |
| canonical generation config | `num_ctx=16384`, perspective/counterargument `2048`, synthesis `4096`, `think=false`, `stream=false` |
| required config digest | `51f1878845ed282b20e9c074ca29adbb5ce0a208c89ffae51425a2565ad5dfd1` |
| scheduler env | `BIDOPS_SCHEDULER_ENABLED=false` |
| live marker | `BIDOPS_LIVE_OLLAMA_TEST=true` was not used to bypass preflight |

The fixed artifacts were read-only copied into the new retry root and their
byte pins still match: validation set
`2ea6a21e6b121f691195bbc891b8ec7766817f821d6b343c20b12b608f3e47e3`, baseline
decisions `69a444e5ec9846c592de4b454472817477abaa4a109c97dbe84787dff9c6789d`,
and screening results
`fb9160602771ff057b708d69b197b9fc7e464f9e021615a7ebaa83a94733903b`. The
`screening-results.generated_at` resolver target remains canonical
`20260817-20260823--20260824T090927.138116Z`; no alias row was created or used.
The copied collection artifact SHA-256 is
`ec5021f5e09c6c15ccde090998df39b57dfdaf728f7a30a1bf24c8f1f1d98ce0`.

### Fresh backup, baseline, and terminal no-write state

This retry uses a new deterministic ignored runtime directory and does not
overwrite the earlier `phase2-backup` evidence:

`/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase2-live-retry-20260827`

The source was the requested Phase 1 retry DB
`phase1-retry/phase1-db/bidops.db`; its pre-run SHA-256 was
`dc5074fcabe8d9b3ab8bbdd8d30c8c6fbd36cbd43853e475fea3daa370cfc03c`. A
SQLite online backup was taken before any gate operation:

- backup: `phase2-db/phase2-live-pre-run.db`, SHA-256
  `da6af6643938ca3487b0354836ec7f816dac343968e4812f57bb099b70f4191f`
- working DB copy: `phase2-db/bidops.db`, SHA-256
  `da6af6643938ca3487b0354836ec7f816dac343968e4812f57bb099b70f4191f`
- backup manifest:
  `phase2-db/phase2-live-pre-run.db.manifest.json`, SHA-256
  `66f370292a50e4f0006a3571a6f73b975666acd53ae3a3b83e6d167dc849cc73`
- logical snapshot fingerprint in the manifest:
  `7dd8b1539532d854d72e999d5ce7802843ce96f7a6ec054991b467246236c66a`
- baseline JSON:
  `phase2-logs/01-pre-run-baseline.json`, SHA-256
  `1f69c6349cdf37fa78f33fcd1b3a098b7adc07bd95932a850b789ae019817e65`
- post-run read-only verification:
  `phase2-logs/02-post-run-verify.json`, SHA-256
  `d0859dc0e9effaa2e18decfb5ea62c5e700eff129470f1f3025720b06d07a9d0`,
  exit `0`

The read-only baseline was Alembic
`0005_generation_config_binding`, SQLite `quick_check=ok`, foreign-key
violations `0`, with core counts run/notice/judgment/review/attachment
`1/40/40/0/149`. Existing executions were unchanged: successful
`scr-72a1ae87342d4d4485fbb467b0e4d3fa` and stopped
`scr-650cd5e1eea04205b8ffffeaa789df7f`. The initial quality counts were and
remain gate/evaluation/review `0/0/0`; schedule execution `0`, policy remains
`activation_candidate`, always-on remains `false`, and prespec remains
`false`.

### Gate and execution result

No gate ID, pass-A/B execution ID, evaluation ID, or review ID was allocated.
Consequently the following are **미측정 / not run**, not zero-quality claims:

| measure | result |
|---|---|
| model calls | `0` (preflight blocked) |
| A/B notices | `0 + 0` processed; required `40 + 40` was not started |
| logical executions | `0` new quality-sample executions |
| persisted attempts | `0` new attempts |
| FIFO order/completion | not applicable; no queue rows added |
| A/B metrics / gate result / evaluation | not measured; no rows |
| provider/schema retries | none; no provider request was issued |
| truncation/error output events | none; only preflight connection refusal |

No policy activation candidate mutation, policy activation, scheduler enable,
always-on enable, operational-approval gate, external model call, or release
operation occurred. The working DB hash equals the pre-run backup hash, and
the source DB was not modified.

### Safety and deferred hardening

The requested basic file-pin/TOCTOU, transaction rollback/replay, and public
bypass protections were not exercised because the required localhost runtime
was unavailable; no result is claimed for them. Same-process inspect/closure
attack hardening is explicitly deferred to a future strengthening phase per
the operator decision and is not a blocker classification for this retry.

To resume T15 Phase 2, `127.0.0.1:11434/api/tags` must first return 2xx with
exact tag `qwen3.8:27b` and the required digest. A new deterministic retry
directory and fresh pre-run backup are required; this blocked evidence and
the earlier Phase 2 record remain immutable.

## 2026-08-27 Phase 2 live retry r2 — `BLOCKED` (localhost preflight)

### 결론

The operator-requested r2 retry was stopped at the read-only Ollama preflight.
`http://127.0.0.1:11434/api/tags` refused the connection, so the required 2xx
response, exact model tag, and exact digest could not be verified. No alternate
port, remote endpoint, OpenAI-compatible endpoint, or substitute model was
attempted. No gate, evaluation, execution, review, activation, scheduler, or
always-on mutation was performed. This run is `BLOCKED`, not a quality pass or
failure result.

The preflight command and result are preserved at
`/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase2-live-retry-20260827-r2/phase2-logs/00-model-preflight.log`:

- command: `curl --silent --show-error --max-time 20 --connect-timeout 5 -w '\\n__HTTP_STATUS__:%{http_code}\\n' http://127.0.0.1:11434/api/tags`
- start: `2026-08-27T00:22:57.478295+00:00` /
  `2026-08-27T09:22:57.478295+09:00` KST
- finish: `2026-08-27T00:22:57.486349+00:00` /
  `2026-08-27T09:22:57.486349+09:00` KST
- exit: `7`; HTTP status: `000`; error: `curl: (7) Failed to connect to 127.0.0.1 port 11434 after 0 ms: Couldn't connect to server`
- log SHA-256: `51328bf7c97fd06edd2b20b6d9dcf106d7fb51d1e6f6d29b518e6f069a316a24`

### Binding and fixed-input evidence

| binding | required value | observed |
|---|---|---|
| endpoint | `http://127.0.0.1:11434` (`/api/tags`) | connection refused |
| model tag | `qwen3.8:27b` | unavailable; no response |
| model digest | `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643` | unavailable; no response |
| generation config | `num_ctx=16384`, perspective/counterargument `2048`, synthesis `4096`, `think=false`, `stream=false` | reserved config; no execution binding created |
| generation config digest | `51f1878845ed282b20e9c074ca29adbb5ce0a208c89ffae51425a2565ad5dfd1` | not exercised |
| scheduler | `BIDOPS_SCHEDULER_ENABLED=false` | unchanged |

The fixed artifact byte pins remain the approved values from the preceding
read-only baseline: validation set
`2ea6a21e6b121f691195bbc891b8ec7766817f821d6b343c20b12b608f3e47e3`, baseline
decisions `69a444e5ec9846c592de4b454472817477abaa4a109c97dbe84787dff9c6789d`,
screening results
`fb9160602771ff057b708d69b197b9fc7e464f9e021615a7ebaa83a94733903b`, and
collection `ec5021f5e09c6c15ccde090998df39b57dfdaf728f7a30a1bf24c8f1f1d98ce0`.
The generated-at resolver target is still canonical
`20260817-20260823--20260824T090927.138116Z`; alias
`20260817-20260823` was not inserted or used as a DB row.

### Fresh r2 no-write backup and baseline

The new deterministic ignored runtime is
`/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase2-live-retry-20260827-r2`.
It does not overwrite the earlier `phase2-backup` or r1 runtime. A read-only
SQLite backup of the requested source DB was captured before any possible gate
operation:

- source DB: `phase1-retry/phase1-db/bidops.db`, pre-run SHA-256
  `dc5074fcabe8d9b3ab8bbdd8d30c8c6fbd36cbd43853e475fea3daa370cfc03c`
- backup: `phase2-db/phase2-live-pre-run.db`, SHA-256
  `da6af6643938ca3487b0354836ec7f816dac343968e4812f57bb099b70f4191f`
- working copy: `phase2-db/bidops.db`, SHA-256
  `da6af6643938ca3487b0354836ec7f816dac343968e4812f57bb099b70f4191f`
- manifest: `phase2-db/phase2-live-pre-run.db.manifest.json`, SHA-256
  `df0dd0b97563392cda959e5d55a8de876f1da6261aa61019520d663e59f9c1fd`
- manifest logical snapshot fingerprint:
  `7dd8b1539532d854d72e999d5ce7802843ce96f7a6ec054991b467246236c66a`
- baseline JSON: `phase2-logs/01-pre-run-baseline.json`, SHA-256
  `e0747dde6823de07ef7520480e122ea65e09769ad89e93093f4eca3e96cbc225`

The baseline has Alembic head `0005_generation_config_binding`, SQLite
`quick_check=ok`, and zero foreign-key violations. Counts are run/notice/
judgment/review/attachment `1/40/40/0/149`; existing executions remain the
Phase 1 success `scr-72a1ae87342d4d4485fbb467b0e4d3fa` and stop smoke
`scr-650cd5e1eea04205b8ffffeaa789df7f`. Initial quality gate/evaluation/review
counts are `0/0/0`, schedule execution is `0`, policy remains
`activation_candidate`, always-on remains `false`, and prespec remains
`false`. The source and working DB hashes were unchanged by this retry.

### Gate, A/B, and model-call result

No gate ID, pass-A/pass-B execution ID, evaluation ID, or review ID was
allocated. The following are not measured because preflight failed before
gate creation:

| item | result |
|---|---|
| model calls | `0` |
| A/B processing | `0 + 0`; required `40 + 40` not started |
| quality-sample logical executions | `0` |
| persisted attempts | `0` |
| FIFO/sequential processing | not started |
| A/B metrics, gate result, evaluation | not measured; no rows |
| provider/schema/truncation retries | none; no provider request occurred |
| errors | one preflight connection refusal, no model-output error |

No `operational_approval` gate, policy activation candidate change, policy
activation, scheduler enable, always-on enable, public bypass, or external
model call occurred. Same-process inspect/closure attack testing is explicitly
deferred to the future security-hardening phase requested by the operator.

### Post-check and resume condition

This r2 path is no-write by construction: the source DB was opened read-only,
the working copy equals the immutable pre-run backup, and only ignored runtime
evidence files plus this append-only validation section were created. A future
retry requires `127.0.0.1:11434/api/tags` to return 2xx with exact
`qwen3.8:27b` and digest
`22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`, followed
by a new deterministic runtime and fresh backup. Neither this blocked retry
nor the earlier evidence may be reclassified as a pass.

### Fresh r3 remote preflight, partial run, and operator stop

The requested remote Ollama endpoint was verified before any database write:
`http://192.168.0.139:11434/api/tags` returned HTTP 200 with exactly one
`qwen3.8:27b` entry and the approved digest
`22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`.
The run used the existing Ollama API and the fixed generation binding
(`num_ctx=16384`, perspective/counterargument `2048`, synthesis `4096`,
`think=false`, `stream=false`, digest
`51f1878845ed282b20e9c074ca29adbb5ce0a208c89ffae51425a2565ad5dfd1`).

The deterministic ignored runtime was
`/home/jechoi/projects/side/bidops-agent/.dryforge/t15-runtime/phase2-live-retry-20260827-r3`.
The initial gate attempt failed before publication because Git parent discovery
looked for the approved profile at the wrong runtime-prefixed path. The
diagnosis is preserved in `phase2-logs/02-gate-create-diagnosis.json`; setting
`GIT_CEILING_DIRECTORIES=/home/jechoi/projects/side/bidops-agent/.dryforge`
enabled the verified vendored baseline fallback without changing source code or
fixed inputs. The corrected attempt created exactly one `model_comparison`
gate (`gate-97dea790d27542c8bf4b0ee966374b36`) with independent A/B executions:
`scr-c9cbcd041e7a40c0976f8b67b59fc1b8` and
`scr-5a4896bbd8f24e28bf4b9f9db9a874b5`.

The operator then requested a pause before the full A/B sample completed. A
cooperative stop was persisted at 2026-08-27 00:55:29 UTC. The worker finished
its in-flight synthesis call and exited; no further model call was started.
Final execution state was:

| item | result |
|---|---|
| A status / sample | `중단됨` / fixed 40; completed `2`, failure `8` |
| A attempts | `79` total: `62` success, `17` `schema_violation` failures |
| B status / sample | `중단됨` / fixed 40; not started, `0` attempts |
| gate status / result | `대기` / `미측정` |
| quality gate/evaluation/review rows | `1 / 1 / 0` |
| schedule execution/reservation rows | `0 / 0` |
| always-on / policy | unchanged; disabled / `activation_candidate` |

Post-stop SQLite checks passed: `quick_check=ok`, foreign-key violations `[]`.
The final working DB SHA-256 was
`01d42cb5e6be4ae766abe20005e488be936176fd86dd02d209095b818e6da812`; the
immutable pre-run backup remained
`da6af6643938ca3487b0354836ec7f816dac343968e4812f57bb099b70f4191f`.
No operational-approval gate, policy activation, scheduler/always-on change,
or public bypass occurred, and no additional external provider call occurred
after the operator stop. The partial run is not a quality pass and must not be
resumed until the `bidops-deep-review` merge is completed. Same-process
inspect/closure attack testing remains deferred to the later security-hardening
phase requested by the operator.
