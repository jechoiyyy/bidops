# 평일 브리핑 생성·Slack 전송·반응 저장 — intent

- 기능 ID: `RL-01-daily-briefing`
- 상위 항목: roadmap §RL 표 2행, ADR-0073 결정 2(G1)·3·4, [ui-spec §4.1·§4.2](../../../../../1016_rootlab-redefinition/ui-spec.md), [ux-review §5 결정 3·4·8](../../../../../1016_rootlab-redefinition/ux-review.md)
- 크기: L — 새 테이블 3개·REST 4개·CLI 1개·Slack 외부 전송(Socket Mode worker)·호스트 스크립트·화면 1개. lifecycle↔screening 확장점을 새로 쓴다.
- 작성일: 2026-10-16

## 문제

실무자 5명이 2~3일마다 나라장터를 직접 훑는다(기준선 연 약 500시간). 수집·C-2 선별·사전규격 적재는 매일 돌지만 결과가 "목록 화면"에만 쌓여 사람이 다시 훑어야 하고, 발주계획 라벨링은 전건 사람 몫이다. 추천이 사람에게 **밀려오지** 않으면 서칭을 그만둘 수 없다.

## 기대 결과

- 평일 아침마다 전일 수집분(사전규격·입찰공고 1순위, 반복 발주처의 연차 예고 발주계획)에서 회사 근거(RL-00 활성 그래프의 선호·제외·반복 발주처·실적)로 **결정적 규칙**이 상위 N(≤10)을 고르고, 항목마다 추천 이유 칩·차단 조건·마감을 붙여 `/briefing` 화면과 Slack 전용 채널에 같은 내용을 보낸다.
- 실무자는 화면 또는 Slack 버튼으로 볼게요(채택)·무시·나중에만 반응한다. 반응은 담당 기록이며 추적 상태를 바꾸지 않고 되돌릴 수 있다(ux-review 결정 3).
- 추적 중인 사업의 정정·마감 변경은 같은 날 브리핑의 둘째 묶음과 별도 Slack 메시지로 알린다.
- 추천 0건이면 Slack은 보내지 않고 화면은 "오늘 추천할 공고가 없습니다 · 수집 정상"을, 수집이 끝나지 않았으면 경고 블록을 보인다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| 전일 브리핑 생성 | `python -m app.lifecycle.cli build-briefing --date 2026-10-16`(`--date`=브리핑 날짜, 수집 회차는 전일; 호스트 `scripts/run-daily-briefing.sh`가 수집 트랙 뒤에 호출) | `GET /api/briefings/2026-10-16` 200, items ≤ 10, 각 항목에 stage·reasons·deadline·opportunity_id, status `generated` |
| 추천 0건 | 후보가 모두 제외 조건에 걸리는 날 | status `empty`, Slack 미발송(`slack_sent_at=null`), 화면 빈 상태 문구 |
| 수집 미완 | 기준일 notices 회차가 없거나 경고가 있을 때 | status `collection_incomplete`, 화면 경고 블록, 있는 후보로는 항목 생성 |
| Slack 발송과 버튼 반응 | `build-briefing --send`(08:00 cron) → 채널 메시지 → 볼게요 클릭 | 메시지 1건(항목 n개), 클릭 뒤 메시지가 "✓ 이름이 볼게요 · 되돌리기"로 갱신되고 `PATCH` 없이도 화면 반응이 `채택` |
| 화면 반응·되돌리기 | `/briefing` 행 선택 → 볼게요(또는 키 1) → Z | `reaction=채택` 즉시 반영, 5초 토스트 되돌리기로 `대기`, 이벤트 2건 append |
| 추적 중 변화 | 추적 중 사업의 공고 마감이 바뀐 관측 | 둘째 묶음 `tracked_change` 1행(판정 "재검토 중"), 별도 Slack 메시지 1건 |
| 전송 payload 확인 | `GET /api/briefings/2026-10-16/slack-preview` | 공고 id·제목·기관·금액·마감·링크·이유 한 줄만 있고 원문·회사 자료·모델 문구 없음 |

## 선행·후속 기능

- 선행: `RL-00-company-ground-truth`(선호·제외·반복 발주처·실적이 회사 그래프에 있어야 규칙이 돈다).
- 후속: `RL-02-opportunity-timeline`(반응이 활동 피드에 보임), `RL-03-fit-verdict`(상위 N 진입이 자동 분석 트리거, 판정 열 채움).

## 영향 범위

- 모듈·컴포넌트: lifecycle(새 `services/briefing*.py`, `routers/briefings.py`, `cli.py` 신설, 확장점 `briefing_order_plan_candidates`·`company_facts_projection`), screening(확장점 제공자: C-2 relevant 발주계획), deep_review(확장점 제공자: 실회사 confirmed 사실 projection), core(`slack.py` 전송기·설정), 새 worker 프로세스 `slack-socket-worker`, 프런트 `BriefingPage` 완성·`PeekPanel`·사이드바 건수.
- 큰 틀 문서의 절: contracts.md REST·DB 절, business-rules.md(브리핑 규칙·반응 상태), operations.md(일일 운영에 브리핑 단계·Slack env·cron 예시), ARCHITECTURE §5.1a·§4.2, tech-stack(Slack SDK 의존 추가).
- 데이터·저장소: 새 테이블 `briefing`·`briefing_item`·`briefing_reaction_event`(append-only), 권한은 `scripts/runtime-privileges.sql`. 불변 규칙 파일 `briefing-policy-v1.json`(가중치·N·창).
- 외부 서비스·호출: Slack Web API(`chat.postMessage`·`chat.update`)와 Socket Mode(websocket). 모델 호출 없음.

## 제약

- (공통) feature.json constraints 전부. 특히 외부 전송 allowlist(`slack.com`)·env 파일 토큰·hosted fallback 금지, 새 테이블 권한은 runtime-privileges.sql, 운영 cron 설치는 사람.
- (기능별) 사용자 결정(2026-10-16): 이유·차단 조건은 결정적 규칙(RL-01에 LLM 호출 없음), Slack 반응은 Socket Mode. 반응은 추적 상태·Go/No-Go를 바꾸지 않는다. Slack payload는 공고 식별자·요약·링크만(tech-stack). 화면·Slack 항목은 같은 4줄·같은 2버튼(ux-review 결정 4). 운영 정보(모델·정책·실행 시각·분모) 표시 금지.

## 범위 밖

판정 문장·차단 조건의 모델 생성(RL-03), 자동 추적 결정, 노트·보고서·새 리스트·커맨드 팔레트, Slack DM·멘션·스레드 기록(분석 완료 스레드 기록은 RL-03), 공개 HTTPS endpoint, 로컬 LLM.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 판정 열 | ui-spec §4.1 판정 pill(진행 가능 등) | RL-01은 LLM 없음 | RL-01은 `분석 대기`(사전규격·입찰공고)·`연차 추적`(발주계획)만. RL-03이 채운다 |
| Luna 정책 발행 시점 | roadmap "RL-01 전에 정책 파일 발행" | RL-01 LLM 호출 없음 | RL-03으로 이동(roadmap 문장 갱신, STEP-008) |
| 추천 이유 3줄 | roadmap "이유 3줄" | ux-review 결정 4 "이유 1줄 + 부족·미확인 1줄" | 화면·Slack 모두 이유 칩 3개 이내 + 차단 조건 1줄(결정 4 우선) |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| 이유 생성 방식 | spec 작성 전 | 2026-10-16 사용자: 결정적 규칙 |
| Slack 반응 수신 | spec 작성 전 | 2026-10-16 사용자: Socket Mode |
| 상위 N·생성 시각 | spec 작성 전 | 추천값 수용: N=10 상한(`tunable`), 생성은 수집 트랙 뒤(07:30 목표), 발송 08:00 KST, 0건 미발송 |
