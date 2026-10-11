# DEMO-04 독립 최종 리뷰 (2026-10-12)

- 리뷰어: Claude general-purpose. 구현에 관여하지 않았고 읽기 전용으로 검토했다.
- 대상: 기준 `c50ed55`에서 기능 worktree의 미커밋 변경 전체(배치 병합 뒤 tree와 같다). 리더 로그만 대조했고 리뷰어는 build·test를 실행하지 않았다.
- 판정: **PASS_WITH_NOTES, 차단 0**

## 확인한 항목 (위반 없음)

- DTO가 백엔드 pydantic schema와 같다. preview·create·attempt·PATCH body도 계약 §2·§6과 같다.
- 회사 간 혼입이 없다. query key·sessionStorage가 회사 단위로 나뉘고, 회사가 바뀌면 화면을 새로 마운트한다. 저장 뒤 cache는 시작한 회사만 갱신하고, 응답의 company_id가 다르면 그리지 않는다.
- request_id·expected_revision·409 처리, 그리고 preview_changed·preview_used가 나면 승인을 폐기하는 규칙이 계약대로다.
- 화면을 보기만 하면 호출이 0건이다. 입력이 바뀌면 승인을 폐기한다. 원문 대조는 true만 보낸다. 회사 핏 승인 UI는 없다.
- 기존 동작이 유지된다. 사전규격 추적은 계속 추적 단일 선택이고, Luna·보고서는 adapter가 없을 때 기존 endpoint와 key를 쓴다. demo를 끄면 회사 경로가 없다.
- 브라우저가 순위·비교 상태·관계를 계산하지 않는다. unknown·null·is_current=false를 문자로 구분한다. `--color-*` 재정의와 모바일 레이아웃이 없다.
- T1–T7이 assertion과 연결돼 있고, 합성 검사는 따로 표기돼 있다. mock은 계약 규칙을 따른다. 최종 실패 6건은 기준 빌드와 같다.
- 정본 문서는 "frontend만 변경, mock 검증, 실제 인수는 DEMO-05"로 정확하게 적었다.

## 주의와 처리

| # | 내용 | 처리 |
|---|---|---|
| 1 | 회차를 바꿀 때 전체 무효화가 demo-config까지 다시 읽는다. 일시 실패하면 값이 `enabled:false`로 내려가 router가 재생성되고 화면 전체가 다시 마운트된다 | 같은 회차에 수정 |
| 2 | 저장 요청이 진행 중일 때도 이탈 확인이 "입력이 사라진다"고 안내한다(실제로는 A에 저장됨) | 같은 회차에 수정 |
| 3 | 회사 이름을 확인하기 전에도 심층 승인이 가능하다 | 같은 회차에 수정 |
| 4 | 회사 목록에 ↑↓·Ctrl/Cmd+Enter 조작이 없다. traversal key가 미사용이다 | backlog. spec 요구가 아니다 |
| 5 | `company-workspace.css`에 240px·180px가 하드코딩돼 있다 | backlog. ADR-0040상 허용 범위 |
| 6 | plan 변경 파일 표에 실제로 바꾼 공용 파일이 빠져 있다. 결과 절이 "미구현"이다. 증거 위치가 plan과 다르다 | 리더가 문서로 정합화 |
| 7 | 사유 maxLength가 UTF-16 단위다(서버는 trim 뒤 글자 수) | backlog. 실제 영향은 거의 없다 |

## 범위 밖 권고 (backlog)

- 핏 GraphPath를 이름으로 보여 주려면 계약에 이름 필드를 추가해야 한다.
- LS-06의 dirty 규칙(담당자 이름만 입력한 경우)을 정한다. 회사 경로도 같은 규칙을 쓴다.
- 회사 목록에 키보드 조작을 맞춘다.
- DEMO-05에서 실제 스택으로 생성(202)→폴링→보고서 흐름과 회사 전환을 인수한다. 그 전에는 "검증됨"으로 적지 않는다.
