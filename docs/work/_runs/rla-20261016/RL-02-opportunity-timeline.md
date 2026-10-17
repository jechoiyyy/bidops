# RL-02-opportunity-timeline — run rla-20261016

- 브랜치·worktree: `sdlc/rla-20261016-RL-02-opportunity-timeline` · `.sdlc/worktrees/rla-20261016-RL-02-opportunity-timeline`, 기준 5e2e119
- 단계 7/7 done → validating

| 단계 | 담당 | 결과 |
|---|---|---|
| STEP-001 단계 바·제목 | implementer-opus | 6단계 순수 함수, 대표 연결(최신 created_at·id) |
| STEP-002 활동 피드 | implementer-opus | 13 kind 파생·opaque 커서·hook 확장점, action_added detail "담당 <owner>" |
| STEP-003 노트 | implementer-opus | `opportunity_note`·0039·열 단위 UPDATE 권한·멱등 REST |
| STEP-004 활동 REST | implementer-opus | `GET /activity`, 병합 200 |
| STEP-005 마감 알림 | implementer-opus | briefing-policy-v2, D-3/D-1 입찰공고 공고당 1행 |
| STEP-006 레코드 화면 | implementer-sonnet | 레코드 셸·탭·RecordTitleContext·"사업기회", opportunities.spec 31건 이식 |
| STEP-007 문서 | implementer-sonnet | contracts·business-rules·ui-spec·ARCHITECTURE·ADR·AGENTS.md |

## 검증(리더 실행, `logs/RL-02-*`)

- tests 295 passed(2 deselect 기존), postgres 201 + 리뷰 수정 뒤 69, frontend build·contrast·Playwright 191(+briefing 27), route-context 기존 12건만 실패, doctor exit 0.
- 단계별: step003-005(197)·pg(117).

## 재시도·우려·합의

- 최종 리뷰(RL-02 + 배치) BLOCKING 1 → 결정 #18·#21(stages[].link_id)로 해소, 권고 3건 수정(#19), 나머지 backlog(#20). 기록 `RL-02-review.md`.
- 라벨·route 교체로 깨진 기존 기대값만 갱신(#13), 기존 실패는 baseline과 대조해 무관 확인.
