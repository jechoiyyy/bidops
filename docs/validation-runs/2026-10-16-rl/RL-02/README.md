# RL-02 실제 스택 확인 — bidops-local `bidops_rla`

2026-10-17, run `rla-20261016`. plan의 필수 증명은 아니며(수동 proof 없음) 가짜 서버로 증명되지 않는 REST↔DB↔화면 연결을 한 번 확인한 기록이다. 외부 호출 없음.

- 환경: RL-01 T12와 같은 격리 DB `bidops_rla`(RL-01 README 참조), 이미지 `bidops-local:rla-20261016-rl02`(RL-02 worktree = 배치 전체 + RL-02), `rla-web` loopback `127.0.0.1:18797`.
- migrate: `0038_briefing → 0039_opportunity_note` exit 0.
- `GET /api/opportunities/134/activity`(T12 브리핑 1순위 사업기회): 200, 키 7개, `title`=사전규격 제목, stages `order_plan:unknown`(건너뛴 앞 단계)·`pre_spec:current`·`bid_notice:pending`·`deadline/opening/contract:unknown`, items `briefing_reacted`(T12 반응, link `/briefing?date=2026-10-09&selected=<item_id>`)·`pre_spec_opened`.
- 노트 REST(actor `RL02-smoke`): note POST 201 → action POST(owner Kim) 201 → 같은 request_id 재전송 200 → done PATCH 200(`done_by`=actor). 피드에 `note_added`·`action_added`(detail "담당 Kim")·`action_done` 시간 내림차순.
- 화면: `/opportunities/134` → `/opportunities/134/activity` replace, 상단 경로 "사업기회 / 2027년 스팸대응시스템 응용SW 유지관리", 1280·1440 가로 넘침 없음, 금지 문자열 없음. `record-1440.png`·`record-1280.png`.
- 한계: 마감 D-3/D-1 알림은 이 DB에 추적 중 입찰공고가 없어 실제 스택에서 보지 못했다(단위·서비스 테스트 T5로만 확인).
