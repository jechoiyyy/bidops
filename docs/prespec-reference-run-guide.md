# 사전규격 참조 실행 시작 가이드

이 문서는 **처음 돌려 보는 사람**을 위한 안내다. 무엇을 먼저 하고, 각 단계에서 무엇이
정상이며, 어디서 멈춰야 하고, 나온 결과를 어떻게 읽는지를 정리한다.

**명령과 환경변수의 정본은 `operations.md`의 "사전규격 심층 검토 참조 실행" 절이다.**
이 문서는 그 절을 대신하지 않는다. 여기서는 순서와 판단 기준을 잡고, 실제 명령은 그 절을
연다.

> 이전 수집·Qwen/Luna·PDF 참조 실행 기록은 [현황](tracking/status.md)에 구간별로 남아 있다.
> 그 기록은 새 policy v5의 두 단계 Qwen 주장 검증을 실행하거나 승인했다는 뜻이 아니다.
> 현재 안정화 작업의 실행 범위와 승인 대기는 [작업 Plan](0910_prespec-workflow-hardening/Plan.md)을 따른다.

## 2026-09-10 안정화 변경의 참조 확인

이번에는 아래 전체 종단 절차를 다시 실행하지 않는다. 변경한 수집기·개요 runner·DB·조회와
화면의 격리 검증을 마친 뒤, 변경하지 않은 C-2·C-1·변환 결과는 동결 입력으로 재사용한다.
새 수집 회차는 기존 폴더를 덮거나 선생성하지 않고 raw 재분류 입력과 출력 경로를 분리한다.

실제 전송 전에 notice/document/target과 source/PDF/input/manifest hash, 정책 v5 digest,
사설 Qwen 목적별 allowlist·선언 revision, draft 및 semantic payload 범위, 정상 2회/최대
3회(semantic 최대 1회)를 고정한다. semantic payload는 검증 통과한 실제 draft와 인용으로
구성되므로 예시 preview를 실제 모델 출력으로 표시하지 않는다. 기존 activation v1은
이 승인을 대신하지 않으며 `--preview-activation`으로 새 v2 실행 계약을 확인한다.

운영 migration·정책 활성화·건별 모델 전송 승인이 빠졌으면 준비 결과와 필요한 대상만
제시하고 멈춘다. 회사 핏·심층 자동 시작·scheduler는 열지 않는다. analysis-worker의 실제
설정/기동을 별도 확인하되 재사용하는 판정·변환 worker를 새로 돌릴 필요는 없다.
결과는 `unmeasured_reference`이며 사람의 모든 주장/PDF 대조와 품질 승인은 별도다.

선택 원문 합계 5,000자만으로 표본을 제외하지 않는다. 초안·의미 각각의 실제 요청과 확인된
overview 모델 context·출력 예약·기존 payload 상한으로 허용량을 판단한다. 35·142번도
기존 동결 원문 전체로 재평가하며, 예산 초과/확인 불가는 해당 단계 미실행이지 내용 검증 실패가
아니다. 초안 전 사전 계산과 생성된 초안으로 만든 실제 의미 요청 계산을 구분해 기록한다.
절단·사전 요약·자동 분할·추가 호출로 우회하지 않는다.
명령과 중지·복구 절차는 [operations의 v4 ops](operations.md#v4-cohort-준비enqueue-ops)를 따른다.

## 두 갈래로 나눠서 간다

한 번에 실제 모델까지 가지 않는다. 먼저 저장소만으로 흐름 전체를 통과시켜 코드가 이어져
있는지 확인하고, 그 다음에 실제 모델과 실제 첨부를 붙인다.

| | 1단계 · mock 종단 | 2단계 · 실제 참조 실행 |
|---|---|---|
| 필요한 것 | 저장소와 Python venv뿐 | 나라장터 API key, 승인 vLLM, 방화벽 |
| 걸리는 시간 | 1분 미만 | 반나절 이상 |
| 외부 호출 | 없음 | 모델·첨부 서버 |
| 확인하는 것 | 코드가 끝까지 이어지는가 | 실제 문서로 쓸 만한 결과가 나오는가 |
| 절차 | 아래 "1단계" | `operations.md`의 7단계 |

**1단계가 실패하면 2단계로 넘어가지 않는다.** 1단계는 외부 요인이 하나도 없으므로,
여기서 깨지면 그건 코드 문제다. 실제 모델을 붙인 뒤에 깨지면 원인이 코드인지 모델인지
네트워크인지 가리기 어려워진다.

## 1단계 · mock 종단 (먼저 이것부터)

저장소 안의 합성 회차 하나를 적재부터 최종 의견까지 통과시킨다. 모델도 외부망도 부르지
않는다.

```bash
cd web/backend
WS=$(mktemp -d)                     # 비어 있는 작업 디렉터리

BIDOPS_TEST_MODE=1 .venv/bin/python -m app.deep_review.cli run-prespec-e2e \
  --fixture "$PWD/tests/fixtures/deep_review/prespec-run" \
  --workspace "$WS" \
  --confirm-workspace "$WS" \
  --output "$WS/evidence.json" \
  --extension-provider app.screening:register_lifecycle_extensions \
  --actor-name "담당자"
```

**`BIDOPS_TEST_MODE=1`은 생략할 수 없다.** 파일 객체 저장소가 격리 경계에서만 열리므로,
없으면 첫 첨부에서 `isolated_boundary_required`로 막힌다. 이것은 결함이 아니라 운영
저장소를 건드리지 않게 하는 안전장치다.

`--extension-provider`도 생략할 수 없다. 판정(screening) 모듈을 설정으로 주입하는
자리이며, 없으면 `screening_provider_missing`으로 멈춘다.

### 정상 결과

마지막 줄에 `"passed": true`가 나오고, 요약이 이렇게 보인다.

```json
{"auto_started_notice_keys": ["pre-1"], "awaiting_click_notice_keys": ["pre-5"],
 "notices": 2, "passed": true, "unsupported_attachments_excluded": 2}
```

**`$WS/evidence.json`을 열어 두 건이 갈렸는지 본다.** 이것이 이 단계의 핵심이다.

| | `pre-1` (SW=Y) | `pre-5` (SW=N) |
|---|---|---|
| 자동 준비 상태 | `deep_review_started` | `deep_review_ready_for_click` |
| 사유 코드 | 없음 | `not_sw_business` |
| 개요 검토 | `completed` · 추진 검토 | `completed` · 추진 검토 |
| 심층 검토 | `completed`, 시스템이 시작 | **없음** — 사람이 눌러야 한다 |

`pre-5`에 심층 검토가 없는 것이 **정상**이다. SW사업대상이 아닌 건은 개요까지만 자동으로
가고 그 다음은 사람 판단이라는 규칙이 그대로 동작한 것이다.

첨부 제외 2건은 zip 첨부다. 묶음에 들어가지 않고 비차단 경고
(`unsupported_attachment_excluded`)로 남으며, 그 사실이 보고서 한계 절에도 적힌다.

### 여기서 깨지면

증거 파일이 안 만들어지거나 `passed`가 `false`면 2단계로 가지 말고 멈춘다. 작업
디렉터리는 매번 **비어 있어야** 하고, 같은 경로에 두 번 쓰지 않는다(증거 파일은 덮어쓰지
않도록 되어 있다).

## 2단계 · 실제 참조 실행

`operations.md`의 "사전규격 심층 검토 참조 실행" 절을 연다. 일곱 단계이고 각 단계에
명령·overlay·환경변수·확인 방법·중단 기준이 있다.

### 시작 전에 손에 있어야 하는 것

- 나라장터 API key
- 승인된 vLLM endpoint의 **IP와 port**, 그리고 운영자가 확인해 준 **64자 model revision**
- PostgreSQL·MinIO 자격증명
- 방화벽에서 첨부 host 한 곳과 모델 IP 한 곳을 열 수 있는 권한

model revision이 없으면 모델을 쓰는 모든 용도가 호출 전에 막힌다. 이것은 설계된 동작이며
우회하지 않는다.

### 반복해서 걸리는 다섯 가지

`operations.md` 본문에도 있지만, 시작 전에 한 번에 읽어 두는 편이 낫다.

1. **수집기 timeout은 300초로 준다.** 기본 30초로는 사전규격 구간에서 거의 항상 모자란다.
2. **회차는 host에서 만들고 `docker compose cp`로 넣는다.** web 컨테이너에는 API key가 없다.
3. **컨테이너 안에서 `127.0.0.1`을 쓰지 않는다.** DB는 `postgres`, 객체 저장소는 `minio`처럼
   서비스 이름을 쓴다. 모델 서버만 컨테이너에서 닿는 실제 IP다.
4. **`import-profile-policy`가 낸 UUID를 `.env`에 넣은 뒤 반드시 재기동한다.** 설정은 프로세스
   시작 때 읽는다. 재기동하지 않으면 심층 검토 생성이 계속 `service_unavailable`로 막힌다.
5. **방화벽은 첨부 host와 모델 IP를 각각 한 곳만 연다.** overlay가 network를 붙이는 것과
   egress가 안전한 것은 다른 문제다.

## 어디까지 갔는지 읽는 법

사전규격 목록·상세 화면의 **자동 준비 상태**가 진행 지점을 그대로 보여 준다. 막혔을 때는
그 옆의 사유 코드를 본다.

| 상태 | 뜻 | 다음에 할 일 |
|---|---|---|
| `not_applicable` | 등급이 `우선 검토`가 아니다 | 대상이 아니다 |
| `waiting_attachments` | 첨부를 받는 중이거나 받을 것이 없다 | 취득 worker 로그를 본다 |
| `bundle_draft` | 묶음이 초안에 머물러 있다 | 차단 issue를 확인한다 |
| `bundle_ready` | 묶음 확정, 개요 대기 | analysis worker가 도는지 본다 |
| `overview_running` | 개요 검토 실행 중 | 기다린다 |
| `deep_review_started` | 심층 검토가 자동으로 시작됐다 | 보고서를 본다 |
| `deep_review_ready_for_click` | 자동 시작 조건이 아니다 | 사유 코드를 본다 |
| `blocked` | 검사·변환 실패 첨부가 있다 | 첨부를 제외하거나 수동 업로드한다 |

`deep_review_ready_for_click`의 사유 코드는 이렇게 읽는다.

| 사유 코드 | 뜻 |
|---|---|
| `not_sw_business` | SW사업대상이 아니다. **정상이며, 사람이 누르면 된다** |
| `bundle_not_auto_ready` | 사람이 확정한 묶음이다. 사람이 이어서 판단한다 |
| `overview_not_completed` | 개요가 사람 검토 필요·실패로 끝났다 |
| `overview_recommendation_closed` | 개요 권고가 `검토 종료`다. 비용을 더 쓰지 않는다 |
| `overview_bundle_mismatch` | 개요가 본 문서가 지금 묶음에 없다 |
| `service_unavailable` | active profile/policy 설정이 없거나 §6.5 조건이 안 맞는다 |

`service_unavailable`이 보이면 위 함정 4번(UUID 넣고 재기동)을 먼저 확인한다.

## 결과를 어떻게 볼 것인가

### 모든 결과에 품질 표식이 붙는다

개요 카드와 보고서 상단에 배지가 있다.

- **참조 실행 · 품질 미측정** (`unmeasured_reference`) — 실제 모델이 돌았지만 품질을 재지
  않았다.
- **mock 참조** (`mock_reference`) — 결정적 mock이다.
- **표식 없음** (`null`) — 표식이 생기기 전의 실행이다. 미측정이나 측정으로 올려 읽지 않는다.

**이번 차수의 모든 결과는 참조 실행이다.** 운영 완료로 집계하지 않고, 모델 품질의 근거로
쓰지 않으며, 정책 활성화의 근거로도 쓰지 않는다. 사업 판단에 그대로 쓰지 않는다.

### 미리 알고 봐야 할 두 가지

두 항목 모두 `tracking/findings.md`에 재현 조건·영향·후속 방향과 함께 적혀 있다.

**요구사항이 많은 문서는 보고서가 `failed`로 나온다.** 모델이 한 단계에서 내놓는 주장은
8개로 묶여 있는데 실제 제안요청서에는 요구사항 번호가 수십 개 있다. 대조 검사가 "문서에
있는데 모델이 언급하지 않은 번호"를 누락으로 보고 중대 실패로 올리고, 그것이 보고서 전체를
`failed`로 만든다. **이것은 문서를 잘못 읽었다는 뜻이 아니라 검사 기대치와 모델 출력 예산이
맞지 않는다는 뜻이다.** 명세대로 둔 상태이며 다음 차수에 범위를 정한다.

**개요 검토는 mock으로 돌려도 "실제 모델 · 품질 미측정"으로 보인다.** mock 표식이 붙은 시도는
완료될 수 없게 되어 있어서, 저장소 안에서 개요를 완주시키려면 mock을 전송 계층에 두어야 하고
그러면 표식이 실제 참조 실행과 같아진다. 지금은 mock 종단이 검증 경로에서만 돌고 운영 화면에
그 데이터가 생기지 않아 실제 혼동은 일어나지 않는다. 심층 검토의 mock 표식은 이 제약과
무관하게 정상 동작한다.

## 증거를 남긴다

`operations.md` 7단계의 템플릿을 그대로 써서
`validation-runs/<YYYY-MM-DD>-prespec-deep-review-reference.md`에 적는다.

**실제로 실행한 명령과 요약 줄만 적는다.** 이전 통과 기록을 재사용하지 않고, 실패한 것은
실패한 대로 적는다. 실패를 적어 두는 것이 이 실행의 목적 중 하나다 — 이번은 결과를 쓰려고
돌리는 것이 아니라 흐름이 실제로 도는지 보려고 돌리는 것이다.

## 관련 문서

- `operations.md` — 명령·overlay·환경변수의 정본. 7단계 절차와 증거 템플릿
- `business-rules.md` — 등급·자동 준비·자동 심층 시작의 규칙
- `contracts.md` — REST 응답 필드와 상태 값의 정본
- `tracking/findings.md` — 위 두 가지를 포함한 미해결 항목
- `engineering-notes.md` — 증상별 재발 방지 지식
- `e2e-bc-acceptance.md` — 문서 준비(B)→심층 검토(C) 인수 절차
