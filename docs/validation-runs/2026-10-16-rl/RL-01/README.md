# RL-01 감독 시운전(T12) — bidops-local `bidops_rla`

2026-10-17, run `rla-20261016`. 외부 호출 없음(Slack 토큰 미준비 → `--send` skipped, 사용자 지시).

## 환경

- `COMPOSE_PROJECT_NAME=bidops-local` 안의 별도 DB `bidops_rla`(RL-00 STEP-006과 같음). 이미지 `bidops-local:rla-20261016-rl01`(RL-01 worktree, linux/amd64). 일회용 서비스 `rla-migrate`·`rla-web`(내부망, 모델·첨부·Slack egress 없음, `BIDOPS_SLACK_ENABLED=false`). 화면 확인 때만 `rla-web`을 `127.0.0.1:18797`(loopback)에 publish.
- 회사 근거: 루트랩 v2 활성(`graph_version_id=089239e1…`, `excl:region.keywords=["대구","세종"]`, RL-00 README v2 절).
- 수집 입력: bidops-local `pipeline-data` volume의 `dev-notices-20261006-20261008`(generated 2026-10-09T02:10:20Z)을 격리 volume `bidops-local_rla-pipeline-data`로 **복사**(원본 volume은 읽기 전용 마운트). 원본 회차 불변.

## 실행과 결과

| 단계 | 명령 | 결과 |
|---|---|---|
| migrate | `rla-migrate`(alembic upgrade head + runtime-privileges.sql) | `0037 → 0038_briefing`, exit 0 |
| 적재 | `python -m app.lifecycle.ingest.cli --run dev-notices-20261006-20261008 --collection` | exit 0, run `dev-notices-20261006-20261008--20261009T021020.854768Z`, 경고 1(`opportunity_link_target_missing`), extensions screening·deep_review |
| 생성 | `python -m app.lifecycle.cli build-briefing --date 2026-10-09 --json` | exit 0, `status=collection_incomplete`(기준일 D-1 `lifecycle-20261008-notices` 회차 없음 → `collection_run_missing`, note "기준일 수집 회차 없음"), `created=true`, 추천 10, 추적 변화 0, 제외 `{hardware:1, election:1, design_only:5, staffing_only:0, region:0, amount_floor:10}`, `slack.skipped_reason=not_requested` |
| REST | `GET /api/briefings/latest`·`/2026-10-09`·`/slack-preview`, `GET /api/workload` | 200, 키 spec 그대로, `score`·`policy_sha256`·`graph_version_id` 없음; preview 키 4개·blocks 42·`channel_id_present=false`·운영 정보 없음; `briefing_pending=10`, `company_attention=22` |
| 반응 | `PATCH /api/briefings/items/{rank1}/reaction` 채택 → 같은 request_id 재전송 → 낡은 revision → 대기 | 200(rev 1, via screen) → 200 재생 → 409 `version_conflict` → 200(rev 2); `briefing_pending` 다시 10 |
| 화면 | Playwright 캡처 `/briefing?date=2026-10-09`(1440·1280), `/company`(1440) | h1 1개, 표 10행, 가로 넘침 없음, 금지 문자열 없음. `briefing-1440.png`·`briefing-1280.png`·`company-1440.png` |

## 한계

- 수집 표본이 10/06~08이라 사전규격 9건의 의견 마감이 지나 "마감 지남"으로 보인다(사전규격은 마감 경과로 후보에서 빼지 않는 spec 규칙). `blocking`도 같은 이유로 비었다.
- Slack 실제 전송·Socket Mode 연결·3초 ack는 **증명되지 않았다**(토큰 미준비). 가짜 서버 검사(T8·T9)까지만이다. 토큰이 생기면 테스트 채널로 `--send` 1회 + 버튼 클릭을 사람 확인 아래 실행한다.
- 발주계획 후보는 이 DB에 C-2 실행이 없어 0이다(`order_plan` 경로는 단위·통합 테스트로만 확인).
