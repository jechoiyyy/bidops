# RL-00 독립 리뷰 (run rla-20261016)

- 리뷰어: 구현에 관여하지 않은 general-purpose 에이전트, 읽기 전용(테스트 재실행 없음, 리더 결과를 읽음)
- 범위: `git diff c93da20` + 미추적 파일, 기능 intent·spec·plan, feature.json constraints, CLAUDE.md 강제 게이트
- 판정: **BLOCKING 없음**

확인 항목: 두 검사기의 enum·조합 규칙 공용, value 확장 추가형, 오류 code·exit 2, import 출력 +2키·activate 불변, `GET /api/company` 키 4개·404, `company_attention` 소유·순서, lifecycle→deep_review import 없음, demo off 가드 GET 6경로만(HEAD·OPTIONS 포함 다른 메서드·하위 경로 404), fixture 약 30노드 원문 대조(조작 없음, project role/scope/amount null, unknown 21 모두 user_interview), 실회사 1곳 경합(advisory lock), 프런트 토큰·pill·편집 버튼 없음·facts 기반 수치.

ADVISORY와 처리:

1. demo-contract RL 절 상태 문장이 STEP-006 미완으로 적힘 → 반영(완료로 갱신)
2. contracts.md "곧 만료"가 지난 유효기간을 뺌 → 반영(business-rules·화면과 일치)
3. AttentionList 제목 "지금 확인하면 판정이 바뀌는 것" vs ui-spec §4.6 "확인이 필요한 것" → backlog(intent 문구와 ui-spec이 서로 다름, 문구 통일은 후속)
4. `agent_proposal`+`confirmed|inferred` 허용 → backlog(spec은 반대 방향만 제한)
5. `company_attention_count` lineage 검사 없음 → backlog
6. import 단계 demo 재검사 없음 → backlog(현재 CLI만 호출)
7. 미사용 `CompanyProfilePage.tsx`·"시나리오 확정" 라벨 → backlog
