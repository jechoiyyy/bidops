# 모델 품질 게이트

품질 게이트는 모델 비교 evidence와 운영 승인 evidence를 분리한다. pass는 정책을 자동 활성화하지 않으며, 이 문서의 수치는 구현에 고정된 이번 회차 계약이다.

## 고정 입력

- `FIXED_RUN_ID=20260817-20260823`
- `data/runs/20260817-20260823/validation-set.json`, schema `bidops.validation-set.v2`
- source window `2026-08-17`–`2026-08-23`, timezone `Asia/Seoul`
- exactly 40 unique notices
- `data/runs/20260817-20260823/screening-decisions.json`, schema `bidops.decisions.v2`, 40건이며 sample 순서와 ID가 정확히 일치
- baseline은 Claude historical decision이고 `screening_basis`는 `회차에 고정된 정규화 공고와 회사 프로필·정책 버전`이다.

두 pass는 같은 frozen 40건을 사용하고 각각 고유 execution/artifact/telemetry를 가진다. 분모는 항상 40이며 threshold 직전에 반올림하지 않는다.

두 pass는 frozen generation configuration도 공유해야 한다. 기본값은 context 16384, perspective/counterargument 2048, synthesis 4096, `think=false`, `stream=false`이며 canonical compact UTF-8 JSON의 SHA-256 digest를 gate와 evaluation에 저장한다. A/B config 또는 digest가 다르면 gate 생성·평가·통과·activation 전에 거부한다. 이 T15 구현은 아직 live 재검증 전이며 기존 Phase 1 synthesis truncation 실패 evidence를 변경하지 않는다.

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
