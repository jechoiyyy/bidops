# 사전규격 회사 핏 v2(사업 범위 카드) 판정 표시와 엔진 분석 추천 — intent

- 기능 ID: `PS-01-company-fit-card`
- 상위 항목: [roadmap](../../../../constitution/roadmap.md) "PS — 사전규격 운영" 절. 측정 근거: [2026-11-27 회사 핏 측정](../../../../../validation-runs/20261127-company-fit-probe/README.md)
- 크기: L. 백엔드(실행기·검증·migration·새 테이블·REST·CLI)와 프런트엔드(상세·목록·mock)를 함께 바꾸고, 새 계약이 여럿이며, 로컬 모델(LiteLLM → Ollama)을 호출한다.
- 작성일: 2026-11-27

## 문제

회사 핏을 제품 밖에서 측정했다. 사업 범위 카드 v1.2 + 프롬프트 v3.1로 11-26 회차 22건 중 17건이 gold와 일치했고, `matched`는 정밀도 5/5·재현율 5/6이었다. 다만 카드 답을 같은 22건을 보며 정했으므로 과적합 위험이 있고, 품질 근거로 쓰지 않는다.
제품의 회사 핏은 회사 입력이 프로필 사실, 프롬프트가 v1, 대상이 C-1 `우선 검토` 등급뿐이라 측정 조건과 다르다. 그래서 담당자는 사전규격 화면에서 이 판정을 볼 수 없다.
엔진 분석은 비싸다. 담당자가 어느 건에 엔진 분석을 요청할지 고를 때 회사 핏 `matched`를 신호로 볼 수 없다.

## 기대 결과

- 운영자는 REST·CLI로 회사 핏 모드를 `suggest`로 켠다. 그러면 analysis worker가 다음 조건을 모두 만족하는 사전규격마다 카드 기준 회사 핏을 한 번씩 판정한다.
  - 개요가 끝나 결정적 검사를 통과했다.
  - SW사업대상이다.
  - 마감 전·마감 미확인이거나 추적 중이다.
- 측정과 같은 입력을 쓴다: 카드 v1.2, 프롬프트 v3.1, 로컬 `local-agent-main`.
- 사전규격 상세의 "회사 적합성" 칸에 다음을 보여 준다.
  - 판정(부합·판단 보류·불일치)
  - 이유
  - 인용한 카드 범위·정책 이름
  - `참조 실행·미측정` 표식
- `matched`이면 "엔진 분석 추천" 한 줄을 보여 준다. 엔진 분석 요청은 지금처럼 사람이 한다.
- 사전규격 목록에 다음이 생긴다.
  - "회사 핏" 열
  - 회사 핏 필터
  - `회사 핏순` 정렬. `검토할 항목` 탭의 기본 정렬이다. 순서는 `matched` → `unknown` → 판정 전·실패 → `mismatch`이고, 그룹 안에서는 마감 임박순이다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| U1 모드 조회 | `GET /api/pre-specs/company-fit/mode` | 행이 없으면 `mode=off`, `effective=false`, `reason_code`가 첫 미충족 조건이다. 모델 호출은 없다 |
| U2 모드 켜기·끄기 | `python -m app.deep_review.cli set-company-fit-mode --mode suggest --actor <이름> [--reason …]` 또는 `POST /api/pre-specs/company-fit/mode` | 새 append-only 행과 감사 이벤트가 남는다. 같은 `request_id`로 다시 보내도 행은 하나다. `auto_request`는 거부된다 |
| U3 자동 판정 | 모드가 실효 `suggest`인 격리 스택에서 analysis worker를 한 번 돌린다(가짜 모델) | 대상 조건을 만족한 공고마다 카드 lineage attempt가 하나 생기고 `completed`로 끝난다. 심층 검토는 만들어지지 않는다 |
| U4 상세 확인 | mock 빌드 `/pre-specs/992?overview=completed&fit=matched`(`unknown`·`mismatch`·`pending`도) | `matched`·`unknown`·`mismatch`에서는 "회사 적합성"에 판정·이유·카드 범위·정책 이름·품질 표식(공용 라벨 `참조 실행 · 품질 미측정`)이 보인다. `matched`에서만 "엔진 분석 추천"이 보인다. `pending`(실행 중 attempt)은 판정 없이 진행 상태만 보인다. 1280·1440·1920 폭에서 확인한다 |
| U5 목록 정렬·필터 | mock 빌드 `/pre-specs?workspace=actionable` | 기본 정렬이 `회사 핏순`이고 그룹 순서는 matched → unknown → 판정 전 → mismatch다. `회사 핏` 필터로 좁힐 수 있다. `마감 임박순`으로 바꿀 수 있다 |
| U6 측정 재현 | 승인 뒤 11-26 격리 스택(`bidops-prespec1126`)에서 제품 실행기(clock을 측정 시점 2026-11-27 10:30 KST로 주입)로 22건을 판정하고 `score_gold.py`로 채점한다 | 측정(17/22, matched 5/5)과 크게 다르지 않다. 결과는 참조 실행 기록이며 품질 합격이 아니다 |

## 선행·후속 기능

- 선행: 없음. 기존 개요 run·회사 핏 attempt 테이블·overview LiteLLM 경로는 main에 있다.
- 후속:
  - 회사 핏 `auto_request`(관찰 기준 통과 뒤 엔진 분석 자동 요청). ADR-0078 개정과 RL-11 live 경로가 먼저 필요하다.
  - 사람 피드백(판정 맞음 표시)과 관찰 지표
  - 카드의 wiki 생성
  - 아직 큐에 없다.

## 영향 범위

- 모듈·컴포넌트
  - `web/backend/app/deep_review/services/company_fit.py`·`company_fit_runner.py`·`auto_preparation.py`
  - 새 `company_fit_card.py`·`company_fit_mode.py`
  - `deep_review/routers/deep_reviews.py`, `deep_review/cli/`
  - `deep_review/services/prespec_projection.py`
  - `lifecycle/routers/pre_specs.py`·`lifecycle/schemas/pre_specs.py`
  - `core/config.py`, `scripts/runtime-privileges.sql`, `docker/docker-compose.prod.yml`
  - 프런트엔드 `CompanyFitSection.tsx`·`PreSpecsPage.tsx`·`PreSpecListRow.tsx`·`PreSpecListDetailPane.tsx`·`preSpecViews.ts`·`preSpecAutoPreparation.ts`·`types.ts`·`api.ts`, mock `tests/api-mock.ts`·`scripts/mock-api.ts`
- 큰 틀 문서의 절
  - `docs/business-rules.md` "회사 핏 판정 (2026-09-08)"·자동 심층 시작 조건
  - `docs/contracts/deep-review.md` "사전규격 회사 핏 계약"
  - `docs/contracts/lifecycle-rest.md` 사전규격 목록
  - `docs/operations/prespec-reference.md`
  - `docs/ADR.md`
- 데이터·저장소
  - migration `0044`: `prespec_company_fit_attempt`에 카드 신원 열과 lineage 제약을 더한다. 새 테이블은 `prespec_company_fit_mode`다
  - 카드 파일은 git 밖이며 읽기 전용으로 마운트한다
- 외부 서비스·호출: 기존 `overview` 용도 LiteLLM(`local-agent-main` → 로컬 Ollama)만 쓴다. 외부(hosted) 전송은 없다

## 제약

- (공통) `docs/work/feature.json` constraints. 원문·입력·결과 불변/append-only, unknown/적합성·추적·Go/No-Go 분리, 외부 전송 규칙, PostgreSQL 17·합성 worker 슬롯 1개, 직접 영향 검사만, 운영 변경·실제 모델 호출은 직전 확인, 새 테이블 권한은 `scripts/runtime-privileges.sql`, 사용자 요청 없이 commit·merge·push 금지.
- (공통 중 이 기능에 적용하지 않는 것) "RL의 모델 호출은 codex-exec Luna 하나" 제약은 RL 그룹 제약이다. 이 기능은 PS 그룹이고, 기존 사전규격 개요와 같은 LiteLLM → 로컬 Qwen 경로를 쓴다(ADR-0072, 사용자 결정 2026-11-27).
- (기능별)
  - 회사 핏은 적합성 등급·참여 준비·추적 결정·Go/No-Go를 대신하지 않는다. `matched`도 추천 표시일 뿐이며 추적·분석 요청을 만들지 않는다(ADR-0078 결정 1 유지).
  - 측정 재현을 위해 모델에 보내는 입력의 키·값 모양을 측정 실행기(`fit_probe.py`)와 같게 둔다. 식별 문자열 두 개(`schema_version`·`prompt_version`)만 제품 이름으로 바뀐다.
  - 카드는 회사 자료이고 원격 저장소는 공개이므로 git에 넣지 않는다. 테스트는 합성 카드를 쓴다.
  - 결과는 `quality_status=unmeasured_reference`(mock은 `mock_reference`)이며 품질 근거·운영 활성화 근거로 쓰지 않는다.

## 범위 밖

- `auto_request` 모드와 엔진 분석 자동 요청. 후속이며 ADR-0078 개정이 필요하다.
- 사람 피드백(맞음/아님, 사람 판정) 저장과 관찰 지표. 사용자 결정(2026-11-27)으로 이번에서 뺐다.
- 모드 변경 화면. REST·CLI만 두고 화면은 읽기만 한다(사용자 결정).
- 카드 내용 수정, wiki에서 카드 생성, Q8 답변. 측정 README 개선 방안 1이 다룬다.
- 판정 2회 일치 방식(개선 방안 3)과 policy 인용 결정적 검사(개선 방안 4).
- 운영 배포·migration 적용·모드 켜기·실제 모델 호출. 각각 직전 승인 대상이며 이 기능의 구현 단계에 넣지 않는다(U6은 승인 뒤 격리 스택에서 한다).
- 기존 프로필 lineage 회사 핏과 DEMO 회사 lineage의 동작 변경. 다만 카드 모드가 실효인 동안에는 다음 두 가지가 예외다.
  - 프로필 lineage의 자동 enqueue와 claim을 멈춘다.
  - `gate_reasons`가 `company_fit_suggest_only`를 내서 회사 핏을 통한 심층 자동 시작을 막는다.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 회사 핏 대상 | `business-rules.md` "회사 핏 판정": 우선 검토 등급의 자동 분석 조건 | 측정·사용자 결정: 개요 통과 SW사업대상 전체 | 카드 lineage는 SW사업대상 전체를 대상으로 하고 C-1 등급을 보지 않는다. 프로필 lineage 규칙은 그대로 둔다(사용자 결정 2026-11-27) |
| 모델 호출 제약 | `feature.json` constraints "RL은 Luna 하나" | 이 기능은 LiteLLM·Qwen | 새 그룹 PS로 등록해 RL 제약 밖에 둔다(사용자 결정 2026-11-27) |
| 엔진 연결 | 측정 README 개선 방안 5: suggest에서 사람이 "맞음/아님"과 엔진 분석 요청을 남긴다 | 사용자 결정: 피드백은 우선 제외 | 판정 표시 + 추천 한 줄만 한다. 피드백은 후속이다 |
| 모드 변경 위치 | C-2 일일 스위치는 관리 화면 탭에서 바꾼다 | 사용자 결정 | REST·CLI만 두고 화면은 읽기만 한다 |
| 미추적 공고의 자동 처리 범위 | ADR-0078 결정 4: 미추적 공고는 개요까지만 자동이다 | 사용자 결정: 개요 통과 SW사업대상 전체에 회사 핏 | ADR-0080에서 결정 4를 개정한다. 개요 뒤 **로컬 모델 회사 핏(외부 전송 없음)**까지는 자동이고, 엔진 분석 요청은 계속 사람이 한다 |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| 카드 status를 측정처럼 모두 `confirmed`로 보낼지 | spec 작성 전 | `confirmed`로 보낸다. 카드 머리글에 "사용자 확인은 카드 문안에 대한 것"이라고 되어 있고, 측정 입력과 프롬프트 문구("모두 회사가 확인한 내용이다")를 그대로 재현해야 한다. 카드 항목의 근거 level은 카드 파일(버전·sha 고정)에 남는다 |
| 피드백·auto_request 전환 기준 | 후속 기능 문서화 때 | 이번 범위 밖 |
