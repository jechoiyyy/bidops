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
