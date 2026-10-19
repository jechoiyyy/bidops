# 모델 품질 게이트

품질 게이트는 모델 비교 evidence와 운영 승인 evidence를 분리한다. pass는 정책을 자동 활성화하지 않으며, 이 문서의 수치는 구현에 고정된 이번 회차 계약이다.

**이 문서는 C-1 공고 판정 policy의 게이트만 다룬다.** C-2 발주계획 1차 선별은 별도 테이블
(`order_plan_screening_quality_gate`·`order_plan_screening_quality_evaluation`)과 게시일별 채점·2회 통과 규칙을 쓰며
[ADR-0060](tracking/decisions/0060-c2-policy-db-row-authority.md)과 [contracts.md](contracts.md)가 정본이다. 이 문서의
고정 입력·통과 기준을 C-2에 적용하지 않는다.
RL 카드 판정의 사용자 gold 대조는 아래 "RL 판정 gold 인수 (RL-05)" 절이 따로 다룬다.

## 고정 입력

- `FIXED_RUN_ID=20260817-20260823`
- `data/runs/20260817-20260823/validation-set.json`, schema `bidops.validation-set.v2`
- source window `2026-08-17`–`2026-08-23`, timezone `Asia/Seoul`
- exactly 40 unique notices
- `data/runs/20260817-20260823/screening-decisions.json`, schema `bidops.decisions.v2`, 40건이며 sample 순서와 ID가 정확히 일치
- baseline은 Claude historical decision이고 `screening_basis`는 `회차에 고정된 정규화 공고와 회사 프로필·정책 버전`이다.

**고정 입력의 모델 신원은 더 이상 위 회차의 실행과 맞지 않는다.** C-1이 부르는 모델 id가
이전 태그 형식에서 vLLM served id `qwen3.8-27B`로 바뀌었으므로
([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)), 옛 이름으로
기록된 기존 execution·판정 row는 carry-over·재판정 검증과 `queue.enqueue`에서 거부된다.
이 40건 고정 표본으로 gate를 다시 측정하려면 **새 이름으로 A/B execution을 새로 만들어야
한다.** 옛 이름의 기록을 새 실행의 baseline으로 재사용하지 않는다. 이 상태는
[findings](tracking/findings.md)에 재현 조건과 함께 기록돼 있다.

모델 identity 확인 방법도 바뀌었다. blob digest를 노출하는 면이 없으므로
`GET {base_url}/models`의 served id를 확인하고, 서버가 `model_revision`을 실어 보내는 경우에만
배포가 선언한 64자 revision과 대조한다([ADR-0042](tracking/decisions/0042-c2-model-revision-declared-at-deployment.md)).

두 pass는 같은 frozen 40건을 사용하고 각각 고유 execution/artifact/telemetry를 가진다. 분모는 항상 40이며 threshold 직전에 반올림하지 않는다.

두 pass는 frozen generation configuration도 공유해야 한다. 기본값은 context 16384, perspective/counterargument 2048, synthesis 4096, `think=false`, `stream=false`이며 canonical compact UTF-8 JSON의 SHA-256 digest를 gate와 evaluation에 저장한다. 이 이름들은 계약 digest에 묶여 있어 바꾸지 않는다. OpenAI 호환 호출에서 stage별 `num_predict`는 `max_tokens`가 되고, `num_ctx`는 대응 파라미터가 없어 binding 기록에만 남으며, `think=false`는 `extra_body.chat_template_kwargs.enable_thinking=false`가 된다([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)). A/B config 또는 digest가 다르면 gate 생성·평가·통과·activation 전에 거부한다. 이 T15 구현은 아직 live 재검증 전이며 기존 Phase 1 synthesis truncation 실패 evidence를 변경하지 않는다.

Gate JSON 자체도 shared canonical parser와 digest로 검증한다. persisted JSON이
tamper되거나 evaluation/pass execution과 불일치하면 activation/always-on을
변경하지 않고 fail closed한다. API 응답은 `generation_config`와 digest를
함께 반환하며 요청으로 이 값을 주입하는 경로는 없다. legacy all-2048 digest는
새 scheduled/manual recovery 승인의 우회로가 아니다.

## 목적과 프로필 분리

| 목적 (`purpose`) | 프로필 source | 의미 | activation 사용 |
|---|---|---|---|
| `model_comparison` | 정확히 `git:ee621835db934ddac944f7a07a986ed0b73ecc7a` | 역사 baseline과 설명 가능한 비교 | 불가 |
| `operational_approval` | 정확히 `current` | 실행 당시 current bytes snapshot에 대한 승인 | 최신 passing 평가만 가능 |

비교 gate가 pass해도 운영에 사용할 수 없다. current snapshot이 바뀌면 새 snapshot/digest와 새 gate가 필요하다. profile/policy/prompt/model identity를 섞은 평가는 activation 대상이 아니다.

## 생성과 평가 수명주기

`POST /api/quality-gates`는 gate metadata를 immutable하게 저장하고 같은 transaction에서 A/B `quality_sample` execution 두 개를 공통 FIFO에 넣어 202를 반환한다. gate aggregate status는 대기 → 실행 중 → 완료/실패/중단됨으로 projection된다. 두 실행이 모두 terminal이어야 evaluation 계산을 시작한다.

처음 evaluation revision은 1, 결과는 `미측정`이다. `QualityGateReview`는 pass A에만 작성하며 reviewer/actor, evidence judgment(`동의|근거 부족|판단 보류`), decision digest를 요구한다. pass-A decision digest와 일치하지 않거나 구조가 malformed인 review는 분모에서 제외한다. 수정은 기존 revision을 바꾸지 않고 새 immutable revision을 추가한다. 유효 review 10건 이상, 서로 다른 notice 10건 이상이 있어야 evidence 지표를 계산한다.

게이트가 중단되거나 일부 공고 실패를 가진 경우 A/B artifact와 실패 목록을 보존한다. incomplete sample을 성공으로 채우지 않고 gate는 `보류`/`미측정`으로 남긴다.

## 지표와 기준

| 지표 | 기준 |
|---|---|
| 최종 grade 재현성 | A/B 각각 baseline 대비·A/B 비교에 필요한 valid 40분모에서 `>=80%` |
| perspective mismatch concentration | 전체 불일치 중 어느 한 관점도 `>50%`가 아니어야 함 (`<=50%`) |
| discrimination | A/B 각각 `우선 검토` 비율 `10–25%` (valid count가 10 이상일 때) |
| evidence validity | 유효 review 중 `동의 >=70%`, `근거 부족 <=10%` |
| perspective split | A/B 각각 각 관점 split `>=40%` |
| perspective reproducibility | A/B 관점별 일치·불일치와 분포를 표시하고 concentration을 함께 판정 |
| information sufficiency | 측정·표시하되 이번 회차 추가 pass threshold 없음 |
| two-axis mixing/counterargument | 측정·표시하는 보호/진단 지표. grade 자동 보정 없음 |

grade, perspective, discrimination은 구조적으로 유효한 판정만 사용한다. invalid structure, incomplete sample 또는 계산 불가능한 denominator는 `보류`다. A/B가 terminal이 아니거나 review가 10건 미만이면 `미측정`; 값은 계산됐으나 기준을 못 맞추면 `미달`이다. `required_metrics_pass`에는 grade reproducibility, mismatch concentration, discrimination A/B, perspective split A/B, evidence agreement/insufficient가 포함된다. 계산 불가를 pass로 취급하지 않는다.

두 축 혼입은 `사업성·자격 제약=확인 불가`이고 종합 grade가 `관찰 대상|제외`일 때 flag `확인 요망`으로 표시한다. 이 보호 표시는 사람 review와 지표에 쓰지만 등급·readiness를 자동 변경하지 않는다.

## 정책 activation과 always-on의 분리

정책은 `draft|activation_candidate|active`이고 body/prompt는 immutable version이다. fresh migrated DB의 `screening_policy`와 `agency_portal`은 0행이며, 명시적 seed 명령은 `policy seed-default --created-by system-bootstrap`이다. idempotent seed는 같은 digest일 때만 허용된다. seed 상태는 `activation_candidate`이고 migration/startup/container는 policy/portal을 seed하지 않는다.

`POST /api/policies/{version}/activate`는 다음을 모두 요구한다.

1. 최신 passing evaluation이 `operational_approval`이어야 한다.
2. evaluation의 policy/prompt/model/profile binding이 activation candidate와 정확히 일치해야 한다.
3. 확인 actor가 명시되어야 한다.

`model_comparison` pass나 stale/current mismatch는 activation을 허용하지 않는다. 게이트 pass만으로 자동 activation하지 않는다. `always_on_state.enabled`도 별도 operator switch이며 환경 cap `BIDOPS_SCHEDULER_ENABLED`와 active policy 및 passing operational approval이 모두 필요하다. T14/T15는 operator direction 없이 activation/always-on을 수행하지 않는다.

## 확인 명령과 산출물

DB gate/evaluation/review와 A/B execution artifact가 정본이다. API는 `GET /api/quality-gates`, `GET /api/quality-gates/{gate_id}`, `PUT /api/quality-gates/{gate_id}/reviews/{notice_id}`를 사용한다. quality sample은 새 canonical run을 발행하지 않는다. 모델·프로필 전문이나 reviewer 비밀을 log/response에 포함하지 않으며, 자세한 REST/파일/DB 계약은 [외부 인터페이스 계약](./contracts.md)에 있다.

## RL 판정 gold 인수 (RL-05)

위 C-1·C-2 게이트와 **별개**로, RL-03 카드 판정(`analysis-policy-luna-rl-v1`~`-v9`)은 사용자가 모델 출력 전에 쓴 gold 10건과 대조해 인수 후보를 가린다. 계약 원본은 [HP-06 spec](work/groups/HP/features/HP-06-gold-acceptance/spec.md)이고 루트랩에서 바뀐 점은 [RL-05 spec](work/groups/RL/features/RL-05-gold-acceptance/spec.md) "루트랩 재명세 차이"다. 절차는 [operations.md "RL 판정 gold 인수 평가"](operations.md#rl-판정-gold-인수-평가-rl-05-2026-10-19)다. 기준은 위 두 게이트의 수치와 무관하다.

| 지표 | 기준(`acceptance-criteria.approved.v1.json` v1, 2026-10-15 사용자 확정, 변경 없이 재사용) |
|---|---|
| 판정 일치 | 10건 중 `>= 8` |
| 차단 조건 recall | `>= 0.8` (전체 항목 micro 집계) |
| 카드 상태 일치 | `>= 0.7` (문서당 상태 표본 10, micro 집계) |
| 명백한 필수자격 미충족을 충족으로 판단 | 0건 (채점 도구가 세지 않는다: `pending_human_review`·개수 `null`, 사람이 비일치 항목을 검토해 `acceptance.json`에 적는다) |

- **분모 0은 미측정이며 통과가 아니다.** 차단 조건 recall·카드 상태 일치의 분모가 0이면 지표 값은 `null`이고 그 검사는 `unmeasured`다(`pass`가 아니다). 숫자 기준을 모두 넘어도 도구는 `pending_human_review`일 뿐 인수가 아니다.
- **채점은 제품 밖에서 한다.** `scripts/rl-gold.py score`가 gold·prediction·criteria 파일을 읽어 지표를 계산하고 DB·네트워크·모델을 쓰지 않는다. 제품은 `export-evaluation`으로 완료된 attempt를 **읽기 전용**으로 내보낼 뿐 채점·인수를 하지 않는다. 도구는 `decision=null`만 쓰며 `accept|reject|defer`는 사람이 `acceptance.json`에 적는다(`scoring_input_sha256` = 수출 receipt + criteria sha + 도구 sha의 canonical sha, HP-06 정의).
- **결과는 사람이 `accept`하기 전까지 `unmeasured_reference`이며 품질 근거가 아니다.** 대상 attempt는 RL 정책 identity·`completed`·`unmeasured_reference`만이고(`mock_reference`·실패·실행 중은 채점 제외), 인수 후보 기준을 넘어도 운영 품질 보증이나 정책 활성화 근거가 아니다. 사람의 `decision`이 없으면 RL-05는 `validating`에 머문다.
- **gold는 모델 출력 전에 쓴다.** export가 gold `authored_at`(ISO-8601, 시간대 포함)을 그 공고의 첫 RL review `deep_review.created_at`과 대조한다. 같거나 늦은 RL review가 있고 첫 attempt가 수동 `verdict_request`면 `gold_after_model`(사람이 gold 완료 전에 모델을 돌림), 자동 시작이면 `holdout_violated`(홀드아웃이 막지 못함)이며 둘 다 해당하면 `holdout_violated`가 우선한다. 둘 다 export를 거부하고 그 표본은 교체 대상이다.
- **홀드아웃은 두 겹이다.** (1) 선정 공고마다 `verdict_request`에 `status=rejected`·`reason=gold_holdout`를 미리 넣는다(`drain-verdict-queue --hold`). RL-03 자동 트리거 조건 (7)이 이 행이 있는 공고를 건너뛰고, gold 검사를 통과한 뒤의 수동 판정 요청이 행을 해제한다. (2) 선정이 끝나기 전에는 `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`를 유지한다.
- gold·actual·alignment·prediction·receipt·`acceptance.json`은 Git 밖 `.sdlc/local-runtime/rl-evaluation-<날짜>/`에 두고 문서 원문·사람 답은 저장소·로그에 남기지 않는다. gold를 고치면 새 버전 디렉터리를 만들고 옛 것은 그대로 둔다. 실행 기록(비민감 sha·결과 위치·metrics)만 [validation-runs](validation-runs/2026-10-19-rl/RL-05/README.md)에 적는다.
