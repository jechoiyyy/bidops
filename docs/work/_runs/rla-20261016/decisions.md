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
| 9 | 2026-10-17 | RL-02 | 추천 0건(status=empty)인 날은 RL-01 규칙상 Slack 미발송이라 D-3/D-1 마감 알림도 Slack에 안 감 | RL-01 규칙 유지(화면에는 표시), backlog로 기록 | 리더(권장안) | 바꾸려면 RL-01 spec 결정 필요, 배치 범위 밖 |
| 10 | 2026-10-17 | RL-02 | 마감 알림은 브리핑이 있는 평일에만 계산 → D-3/D-1이 주말이면 그 알림 없음 | spec 문자 그대로 유지, backlog | 리더(권장안) | spec "브리핑 날짜 기준·하루 1회" |
| 11 | 2026-10-17 | RL-02 | 노트를 못 찾거나 다른 사업기회 노트일 때의 오류 code가 spec에 없음 | 기존 core `not_found`(404) 재사용, 새 code 없음 | 리더(권장안) | 새 오류 어휘를 만들지 않음 |
| 12 | 2026-10-17 | RL-02 | 추천 행에 마감 알림이 겹칠 때 표시 | 추천 행 change_fields에 합치고 표시는 "분석 대기" 유지, "마감 임박"은 추적 변화 행에만 | 리더(권장안) | RL-01 공고당 1행 규칙 |
| 13 | 2026-10-17 | RL-02 | "사업 추적"→"사업기회" 라벨 변경과 단독 상세 route 교체로 route-context spec 6건이 새로 실패(spec 목록 밖 파일) | 라벨 문자열과 단독 route 기대값(`/opportunities/501` → 레코드 화면)만 갱신, 기존 12건 실패는 손대지 않음 | 리더(권장안) | spec이 라벨·route 교체를 소유, 기존 실패는 범위 밖. 같은 이유로 briefing.spec의 Enter 이동 기대 URL을 `/opportunities/501/activity`로 갱신 |
| 14 | 2026-10-17 | RL-02 | 다음 행동 담당 머리글자에 필요한 owner가 활동 응답에 없음 | `action_added`의 기존 `detail`에 "담당 <owner>"를 싣고 화면이 그 이름의 머리글자를 씀(새 키 없음) | 리더(권장안) | spec ActivityItem 키 유지, ui-spec "담당 머리글자" 충족 |
| 15 | 2026-10-17 | RL-02 | 화면 구현자가 spec 22건보다 많은 31건을 `?selected=`로 이식, bid-delta·draft·screen-semantics spec 3건 최소 수정 | 수용 | 리더(권장안) | 단독 route 교체의 직접 결과, 단언 약화 없음 |
| 16 | 2026-10-17 | RL-02 | bid-delta "같은 내용 재확인 request_id" 테스트 간헐 실패 | RL-02 회귀 아님(batch HEAD 빌드에서도 반복 3/3 실패)으로 기록, 수정은 backlog | 리더(권장안) | bid-delta 코드는 이번 배치에서 미변경 |
| 17 | 2026-10-17 | RL-02 | 활동 확장점 제공자가 예외를 내면 GET 500 | 그대로(읽기 오류를 숨기지 않음), RL-03·04 제공자 구현 때 재검토 | 리더(권장안) | 오류를 빈 목록으로 접지 않음 |
| 18 | 2026-10-17 | RL-02 | 최종 리뷰 BLOCKING: 화면 헤더·좌측은 단계의 가장 오래된 연결, 제목·단계 바는 가장 최근 연결을 대표로 씀(재공고 시 불일치) | 프런트 대표 연결 선택을 백엔드와 같은 규칙(권위 연결 중 created_at·id 최대)으로 맞추고 두 입찰공고 회귀 테스트 추가 | 리더(권장안) | spec "현재 단계 = 제목을 준 연결의 단계", 규칙 한 곳 |
| 19 | 2026-10-17 | RL-02 | 리뷰 권고: `<time dateTime>`에 초·마이크로초, 사전규격 source_type 철자 불일치, 첫 관측을 observed_at으로 판정 | 셋 다 수정(분 단위 dateTime, 백엔드와 같은 철자 집합, 적재 순서 id로 첫 관측) | 리더(권장안) | spec 초 단위 노출 금지·백엔드 정의·loader `is_new`와 일치 |
| 20 | 2026-10-17 | RL-02·배치 | 리뷰 권고 나머지: 입찰공고 마감 null일 때 current 해석, 마감 pill 추가 문구, 다음 행동 200건 상한, 추천 행에 합친 change_fields 미표시(Slack·화면), 미사용 `OpportunityDetailPage` export·낡은 주석, Composer 담당 입력 원시 input, 화면 곳곳 "사업 추적" 문구 | backlog(이번 범위에서 고치지 않음) | 리더(권장안) | spec 밖 또는 문구·정리 수준 |
| 21 | 2026-10-17 | RL-02 | #18 수정에 프런트가 연결 `created_at`을 받지 못함: A) 링크 응답에 created_at 추가 후 화면이 규칙 재구현, B) 활동 응답 `stages[].link_id`로 서버가 대표 연결 id 제공, C) 양쪽 max id | **B** — `stages[]`에 `link_id` 추가(가산형), 화면은 id로만 고름. spec 응답 줄·contracts 개정, accept-spec | 리더(권장안) | business-rules "대표 규칙을 화면·다른 service가 다시 만들지 않는다", 기존 링크 응답 불변 |

