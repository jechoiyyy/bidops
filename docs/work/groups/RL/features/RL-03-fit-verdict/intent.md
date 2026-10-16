# 카드 기반 참여 판정(추출→대조→역할→종합)과 판정 화면 — intent

- 기능 ID: `RL-03-fit-verdict`
- 상위 항목: roadmap §RL 표 4행, ADR-0073 결정 2(G2)·4·5, HP 공통 계약 §6~8(재사용 계약), HP-03·HP-04 spec(재명세 원본), [ui-spec §4.4](../../../../../1016_rootlab-redefinition/ui-spec.md), [bid-procedure §3](../../../../../1016_rootlab-redefinition/bid-procedure.md)
- 크기: L — 새 정책 파일·전송 사전 승인 테이블·분석 단계 테이블·worker 분기·runner contract 3개·REST 4개·화면 1개·자동 트리거. 외부 모델(Luna) 호출. **1차 분석 대상은 사전규격**(입찰공고는 문서 취득 경로가 없어 후속; 결정 근거는 spec 머리).
- 작성일: 2026-10-16

## 문제

브리핑이 공고를 밀어 줘도 "우리가 할 수 있는가"는 제안요청서 50~90쪽을 사람이 2~4시간 정독해야 안다. 현재 심층 검토(narrative-v2)는 서술형 보고서라 요구사항 단위로 충족·부족·미확인을 보여 주지 못하고, 회사 핏은 가상회사·건별 클릭 승인 전제라 실회사 자동 실행이 막혀 있다. HP-03·04 설계는 가상 온웹서비스 기준으로 끝까지 가지 못했다.

## 기대 결과

- 브리핑 상위 N에 든 사전규격은 문서 준비·개요가 끝나면 **자동으로** 카드 기반 분석이 돈다(입찰공고는 연결된 사전규격 판정을 참조 표시): 요구사항 카드(HP-01)와 여섯 영역 unit → Luna 1층 추출 → 코드 결정적 대조(루트랩 `confirmed` 사실만 근거) → 역할 3 → 종합. 전송은 정책 파일 단위 사전 승인으로 자동화하고 건별 감사·payload 동결·allowlist·일일 호출 상한을 둔다.
- `/opportunities/:id/verdict`가 판정(진행 가능·조건부 진행·진행 어려움·판단 불가)·체크리스트 5·요구사항 표(부족→확인 필요→충족)·원문 패널을 보여 준다. `unknown`과 `proposed`는 "확인 필요"이지 부족이 아니다.
- 판정 완료는 활동 피드·브리핑 Slack 스레드에 한 줄로 기록되고 브리핑 판정 열이 채워진다. 추적·Go/No-Go는 바뀌지 않는다.

## 유즈케이스

| 유즈케이스 | 실행 방법 | 확인 기준 |
|---|---|---|
| 정책 사전 승인 | `python -m app.deep_review.cli approve-transfer-policy --policy analysis-policy-luna-rl-v1 --actor <name> --daily-cap 10`(사람이 직전 확인 뒤 실행) | `transfer_policy_approval` 행 1건(active), `GET /api/analysis/transfer-policy` 200 |
| 자동 분석 | 브리핑 추천(pre_spec/bid) 생성 → 문서 준비 ready | attempt 1건 `running→completed`, 승인 없이는 생성조차 안 됨(`policy_not_approved`), 하루 cap 초과분은 `queued`·사유 `daily_cap_reached` |
| 수동 다시 판정 | 판정 탭 "다시 판정" → `POST /api/opportunities/{id}/verdict-requests` | 202, 같은 계보면 새 attempt(기존 `create_company_attempt` 규칙), 계보 다르면 새 review; 이전 결과 보존 |
| 판정 화면 | `/opportunities/501/verdict` | 좌측 판정·사유·체크리스트 5·다음 행동·고지 1줄, 중앙 요구사항 표(기본 부족·확인 필요만), 행 선택 → 원문 패널(쪽 링크, 상속 쪽 "(추정)", 미확인 쪽 링크 없음) |
| unknown 보존 | 직접생산 세부품명 unknown인 회사 + 품명 요구 공고 | 해당 unit `unknown`→"확인 필요", 체크리스트 자격 항목 `unknown`, 판정이 `진행 어려움`이 아님 |
| 실패 보존 | 검증 실패·60분 초과 | attempt `failed`, 화면 "사람 검토 필요" + 검증된 부분표, 자동 보정·자동 재시도 없음 |
| 전송 감사 | 실행 뒤 | 건별 감사 이벤트(정책 sha·입력 sha·unit 수·호출 수), payload에 노트·회사 `proposed`/`unknown` 값·원문 외 텍스트 없음 |

## 선행·후속 기능

- 선행: `RL-00-company-ground-truth`(실회사 그래프·`proposed` 상태), `RL-01-daily-briefing`(트리거·판정 열·Slack 스레드), `RL-02-opportunity-timeline`(판정 탭 자리·활동 확장점), `HP-01-requirement-cards`(카드 inventory, 완료).
- 후속: `RL-04-proposal-draft`(요구사항 대응표 입력), `RL-05-gold-acceptance`(판정 채점).

## 영향 범위

- 모듈·컴포넌트: deep_review(`services/card_analysis.py`·`card_compare.py`·`verdict_view.py`·`transfer_policy.py`, `schemas/card_analysis.py`·`verdict_view.py`, `contracts/bidops.requirement-extract.v1.json`·`verdict-role.v1`·`practitioner-verdict.v1`, `policies/analysis-policy-luna-rl-v1.json`, `services/company_deep_review.py` 게이트·분기, `company_analysis_input.py` v2, `deep_reviews.py` dispatch, `luna_client.py`·`luna_identity.py`, `cli/approve_transfer_policy.py`, `routers/company_analysis.py`·`company_reads.py`·새 `verdicts.py`), codex-runner(schema 3개·contract allowlist), lifecycle 확장점 제공(활동 `verdict_completed`, 브리핑 `verdict_display`), core(설정 3개), 프런트 `pages/OpportunityVerdictTab.tsx`·`components/verdict/*`·`SourcePanel`.
- 큰 틀 문서의 절: HP 계약 §6·7·8(루트랩 기준 재적용 주석), DEMO 계약 §5·§6·§9(승인 단위 개정), contracts.md(REST·DB·정책), business-rules.md "회사 핏 판정"·"자동 문서 준비와 자동 심층 시작"(RL 자동 분석 규칙), operations.md(정책 승인·cap·시운전), ADR-0050·0069 완화 기록(ADR.md 한 줄), ui-spec §4.4.
- 데이터·저장소: 새 테이블 `transfer_policy_approval`·`card_analysis_stage`·`verdict_request`·`verdict_feedback`(append-only), cap 초과 큐는 `verdict_request.queued`(WorkJob은 만들지 않음). worker 역할에 preview·review·attempt·approval·stage INSERT 권한 추가(runtime-privileges.sql).
- 외부 서비스·호출: codex-exec `gpt-6-luna`/high(HP-00 identity)만. 호출 수 = ceil(unit/8)+3+1(+repair ≤ 1회/호출).

## 제약

- (공통) feature.json constraints 전부. 특히 "외부 모델 전송은 정책 단위 사전 승인 + 건별 감사·payload 동결·allowlist·hosted fallback 금지", 슬롯 1개, HWP/HWPX 원본 정본, `proposed`·`unknown`은 차단 조건 아님.
- (기능별) HP 계약 §7 enum·체크리스트 key·호출 수·40분 목표/60분 강제 종료 유지. 검증 실패는 사람 검토, 자동 보정 금지. 노트 본문(RL-02)·`proposed`/`unknown` 값·운영 정보는 payload에 넣지 않는다. 판정은 보조 의견이며 추적·Go/No-Go를 저장하지 않는다. 운영 전환·실제 호출은 직전 사람 확인.

## 범위 밖

gold 채점·인수(RL-05), 제안서(RL-04), narrative-v2 경로 변경·삭제, 개요 run 자동 enqueue 폐지(별도 결정), 발주계획 판정(브리핑 "연차 추적" 유지), 가상회사 경로, 로컬 LLM, 역할 간 충돌 자동 해소, 입찰 delta.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 전송 승인 단위 | ADR-0069·DEMO §9 건별 preview→approval | ADR-0073 결정 5 정책 단위 사전 승인 | 정책 승인 테이블을 두고 preview·approval 행은 **자동 생성**(사람 클릭 없음)으로 유지해 기존 동결·재검사 경로를 재사용 |
| 회사 입력 문구 | HP 정책 "fictional scenario" 규칙 | 실회사 | 새 정책 파일에 실회사 규칙(`origin` 7값, `proposed`는 미확인과 같은 취급) |
| 분석 트리거 | ADR-0049·0054 등급 `우선 검토` + 개요 completed + 회사 핏 matched | ADR-0073 결정 4 "카드 기반 1회 분석 자동" | RL 트리거 = 브리핑 추천 ∧ 문서 준비 ready ∧ 개요 completed ∧ SW=Y ∧ 정책 승인 active ∧ cap 여유(회사 핏 matched는 요구하지 않음). 기존 자동 심층 시작 플래그는 그대로 두고 RL 플래그를 따로 둔다 |
| 분석 대상 | roadmap·브리핑 "사전규격·입찰공고" | 코드: 입찰공고는 첨부·준비·개요 경로 없음 | 1차 사전규격만, 입찰공고는 참조 표시·후속 기능(사용자 확인 대상으로 보고) |
| 판정 REST 경로 | HP-04 D6 `/companies/{company_id}/pre-specs/{notice_id}/verdict` | ui-spec 레코드 탭(사업기회 id) | 둘 다 둔다. 사업기회 경로는 연결된 최신 사전규격/공고로 해석하는 읽기 전용 별칭 |
| 저장 테이블 이름 | HP-03 `hp_analysis_stage` | RL | `card_analysis_stage`(HP 이름 폐기, 구현 전이라 이관 없음) |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| 정책 승인 발행 시점 | spec 작성 전 | 추천값 수용(2026-10-16): RL-03에서 발행(RL-01에 LLM 없음) |
| 자동 트리거·일일 상한 | spec 작성 전 | 추천값 수용: 브리핑 상위 N 진입 + 문서 준비 완료, cap `tunable` 기본 10 |
