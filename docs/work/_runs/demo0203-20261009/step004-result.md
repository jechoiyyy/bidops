# STEP-004 결과

- 지정 complex 구현자(gpt-5.6-sol high)가 input_versions.py의 public validate_profile_snapshot와 v1/v2 strict 분기를 구현했다. v2 company/profile/graph/source/content/location/ontology/node/edge/fact/evidence 계보·hash를 검증한다.
- v1 고정 source_file 및 기존 object version/hash 검증 유지. v2 기본 소비는 private source를 읽지 않고 명시적인 require_verified_source=True일 때만 고정 source version을 다시 읽는다. unknown/null·fictional_scenario·non-unknown 근거1개/unknown 근거0개를 보존한다.
- STEP005 재사용 interface: validate_profile_snapshot(session, profile, require_verified_source=False), profile_context(session, profile). DEMO03 모델 입력 evidence origin 조립은 후속 단계 소유다.
- 리더 red: step004-before.log 38failed, 19deselected, skip0, exit1. 제품 수정 전 v2 거부/새 interface 부재 확인.
- 리더 green: step004-tests.log 78passed, 91deselected, skip0, exit0. SQLite와 일회용 PG17.11, v2 변조16종·고정 source version·기존 source repair·module boundary 포함.
- 소스 해시는 step004-source-hashes.json. 제품/테스트 두 파일만 수정했고 운영·모델 호출은 없다.
