# run rla-20261016 결정 기록

2026-10-17 사용자 지시: "앞으로 있을 선택사항들에 대해서는 너가 권장하는 방향으로 일괄진행하고 md문서로 따로 기록을 남겨줘". 이후 선택은 리더가 권장안으로 진행하고 이 문서에 남긴다. 사용자 지시의 정지 조건(모듈 경계·권한·drift 실패, spec 밖 테이블·REST·설정 키, 문서 밖 회사 사실, 외부 전송)과 운영 변경·커밋 외 승인 범위는 그대로다.

| # | 일시 | 기능 | 선택 | 결정 | 결정자 | 근거 |
|---|---|---|---|---|---|---|
| 1 | 2026-10-16 | RL-00·01 | bidops-local DB가 HP-03 migration 0039로 main(0037)과 이력 분기 | bidops-local postgres 안에 새 DB `bidops_rla`를 만들어 검증. 기존 `bidops` DB 불변 | 사용자(권장안 선택) | 비파괴, 격리 유지 |
| 2 | 2026-10-16 | RL-00 | demo-on `/companies/:id/profile → /company` 리다이렉트로 DEMO 프로필 화면 spec 11건이 대상 상실 | spec대로 리다이렉트, 해당 spec 삭제·리다이렉트 검사로 교체 | 사용자(권장안 선택) | DEMO 그룹 종료, 회사 1곳 |
| 3 | 2026-10-17 | RL-00·01 | 회사 파일 `excl:region.keywords`가 `["지역제한"]`이라 브리핑 지역 규칙과 불일치 | 루트랩 파일 v2: `["대구","세종"]`(v1 보존, bidops_rla revision 2) | 사용자(권장안 선택) | preferences 본점 대구·지점 세종, 세종 등기 형태 unknown을 차단 조건으로 쓰지 않음 |
| 4 | 2026-10-17 | RL-01 | 독립 리뷰 BLOCKING: `region_limit_json.basis`는 판단 기준("본사소재지")이라 지역 제외식이 지역제한 공고 전부를 제외 | 지역 제외 보류(`excluded.region`=0), spec 개정·accept-spec, findings 기록, 참가 가능 지역 수집은 후속 | 사용자(권장안 선택) | 모르는 값은 제외 근거가 아님 |
| 5 | 2026-10-17 | 배치 | 사용자 "커밋도 진행해주고 계속해줘" | 이 run의 기능 커밋과 배치 통합 merge를 진행. main 반영(run finish --merge)은 별도 확인 | 리더 해석 | commit_policy=manual에 대한 명시 요청 |
| 6 | 2026-10-17 | RL-01 | 리뷰 권고: Slack 반응 줄 조사 "이" 고정 | 한글 이름은 받침에 따라 이/가, 그 밖은 spec 문구대로 "이" | 리더(권장안) | 프런트 `subjectParticle`과 같은 규칙 |
| 7 | 2026-10-17 | RL-01 | 리뷰 권고: reason chip 직렬화에 `text`·`count` null 키 | 코드 유지, contracts.md에 실제 모양 명시 | 리더(권장안) | PG strict 테스트·프런트가 이미 그 모양을 씀 |
| 8 | 2026-10-17 | RL-01 | 리뷰 권고 나머지(늦게 도착한 C-2 결과 미추천, 빈 수집일 incomplete, Enter 동작, Socket Mode 백업 host, 추적 변화만 있는 날 Slack 없음) | 이번 범위에서 고치지 않고 backlog로 남김 | 리더(권장안) | spec 문자 그대로이거나 spec 밖 개선 |
