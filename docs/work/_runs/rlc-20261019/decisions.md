# run rlc-20261019 결정 기록

| # | 날짜 | 대상 | 상황 | 결정 | 결정자 | 비고 |
|---|---|---|---|---|---|---|
| C1 | 2026-10-19 | 운영 | 운영 `bidops` 스택이 미커밋 C-2 Mac 작업 트리에서 돌고 있어 main 그대로 배포하면 C-2 v5가 멈춤 | C-2 Mac 작업 커밋·main 병합 뒤 같은 작업 트리를 fast-forward해 반영(경로·env·volume 유지). 리허설·백업·롤백 태그 선행 | 사용자(일괄 승인 A) | `docs/validation-runs/20261019-ops-rl-rollout/` |
| C2 | 2026-10-19 | RL-03·04 | run start가 범위 밖 선행 RL-03의 manual `real_data_run` stale로 거부 | 입력 변경이 RL 경로 무관(diff 확인)하므로 2026-10-18 사용자 확인 결과를 근거와 함께 재연결. 실제 실행 없음 | 리더(권장안) | 사용자에게 보고 |
| C3 | 2026-10-19 | RL-05 | 표본 구성 roadmap "fixture 5 + 실제 5" vs spec "실제 수집 10" | 실제 수집 10건(fixture 4·폴리텍 제외), roadmap 행 갱신은 STEP-005 | 사용자 | |
| C4 | 2026-10-19 | RL-03 plan·RL-04 plan | 증명 절의 `test_proposal_payload_guard.py`·`test_proposal_api_postgres.py`는 실제로 없음(검사는 test_proposal_input·test_proposal_draft·test_proposal_api의 PG 변형) | 실제 파일로 실행. plan 문구 정정은 백로그(done 기능 문서 변경은 spec_hash 재승인 필요) | 리더(권장안) | |
| C5 | 2026-10-19 | RL-05 STEP-003 | intent는 "RL-01 브리핑에서 채택한 사전규격 중 문서 ready·개요 completed"부터 고르라 하지만 운영 DB에는 회사 근거·브리핑이 없고, 실제 수집 원본·개요는 운영 스택에만 있음(bidops_rla에는 후보 65건 중 3건) | 후보 = 운영 REST 읽기(개요 completed·첨부 전부 완료·SW Y) 65건 목록을 Git 밖 `rl-evaluation-20261019/candidates.md`로 제시하고 사용자가 10건 선택. 선정 뒤 해당 회차를 bidops_rla에 적재하고 운영 MinIO 원본을 기대 sha256과 함께 `attach-local-original`로 연결(G2B·모델 호출 없음) | 리더(권장안) | 선택은 사용자 |
| C6 | 2026-10-19 | RL-05 STEP-003 | 표본 10건 선정(모델 출력 전) | 사용자: "권장 10건" — candidates.md #22·33·40·48(홈페이지 유지관리)·#11·24·43·45(개발·플랫폼)·#7·56(거리 먼 사업). 단일 원문 묶음 58건 중에서 | 사용자 | 여러 원문 묶음 7건 제외(STEP-002 selection_mismatch) |
| C7 | 2026-10-19 | RL-05 spec | quality_status 출처(preview provenance_jsonb에 품질 필드 없음)와 gold_after_model/holdout_violated 정의 중복 | 사용자 승인 "둘 다 승인": 제품 규칙 `quality_status_for_reviews`, 첫 attempt 시작 원인(수동=gold_after_model, 자동=holdout_violated 우선)으로 spec 정정·accept-spec | 사용자 | |
| C8 | 2026-10-19 | RL-05 STEP-003 | 선정 #56 복합기 임차(R26BD00281853)는 본문 2.3만 자이나 요구사항 고유번호 표가 없어 카드 0개 → 카드 상태 표본 10개를 쓸 수 없음 | 같은 "거리 먼 사업" 범주에서 원본 연결 뒤 카드 수를 확인(결정적 추출, 모델 출력 아님)한 후보 3건(#15 23장·#25 25장·#36 39장) 중 성격이 가장 가까운 #15 국가기술표준원 전산장비(PC 등) 유지관리(R26BD00284827)로 교체. 이전 selection·cards·blank gold는 사람 입력 전이라 `superseded-56-zero-cards/`로 보존. 추가 연결 3건·#56도 holdout(합 13행) | 리더(권장안) | 사용자에게 보고, gold 작성 전이면 변경 가능 |
| C9 | 2026-10-19 | RL-05 spec | spec "모든 CLI 오류는 exit 2" vs export-evaluation의 재시도성 `processing_failed`·`storage_failed` exit 1 | 기존 CLI 관례(attach-local-original 등 exit 1 = 재시도·저장소 장애)와 같아 구현 유지, spec 문구 보정은 백로그 | 리더(권장안) | |
| C10 | 2026-10-19 | 회사 근거 v3 | G2 실적을 사용자 지시로 나라장터 계약정보(공개 기록)에서 채움. 등록 파일 origin 허용값에 공개문서가 없음(company_brochure·homepage·user_interview·agent_proposal) | origin=user_interview(인터뷰 G2 답의 지시 방식), 근거 계약번호를 scope와 company-profile §8.2.1에 기록. 홈페이지 목록 밖 계약(재난안전통신망 교육·훈련 지원)은 문서에만 | 리더(권장안) | |
