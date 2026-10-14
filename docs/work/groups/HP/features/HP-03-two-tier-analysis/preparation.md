# HP-03 연결·계약·검사 준비 (구현 전)

D1·D2·D4·D5가 미확정이다. 아래는 코드 조사에 기반한 계약 초안이며 제품 API·정책·DB에 적용하지 않았다.

| 기존 연결 지점 | 준비한 연결 방식 |
|---|---|
| `services/company_deep_review.py`: company_source_units, prepare_company_deep_review, preview_company_deep_review, recheck_company_preview | 현행 회사·문서·정책 소유권과 preview 재검사를 보존하고 HP 정책 분기에서 카드/선택 segment unit을 만든다 |
| `services/company_analysis_input.py`: build_company_analysis_input, frozen_provenance | 회사/ontology/profile/document version·hash와 unit 원문·순서·batch 경계를 승인 입력에 동결 |
| `services/document_segments.py`: requirement_cards | 현재 identity의 저장 카드·locator·상속/미확인 쪽 사용. 이미 변환한 원문을 다시 파싱하는 worker 경로를 만들지 않음 |
| `services/company_knowledge_retrieval.py`: match_concepts, search_graph_paths, select_profile_facts | 기존 결정적 매핑·direct/partial·최대3hop·evidence를 재사용. 수치 대조만 명시적 타입 규칙으로 추가 |
| company_deep_review create_company_review/create_company_attempt → workers/deep_review.run_once → services/deep_reviews.DeepReviewService.claim_next_job/run_claim | 슬롯1, 승인 재검사, 불변 attempt, HP00 identity fail-closed 유지. narrative-v2 보존 |
| codex runner의 고정 schema 파일/정책 로더 | 새 세 출력 schema를 이미지에 포함. 요청으로 model/schema 임의 지정 불가 |

경로는 모두 `web/backend/app/deep_review/` 기준이다. 새 분기는 실제 worker dispatch 조사·스펙 확정 후 추가하며 현행 함수를 복제하지 않는다.

입력 초안: `frozen_input={company_id,knowledge_version_id,ontology_sha256,profile_sha256,policy_id,policy_sha256,document_versions,units,batches}`. unit은 `{unit_id,source_sha256,structure_id,manifest_id,kind,raw_id,normalized_id,ordinal,blocks:[{block_key,text}],page_range,mapping_status}`. 원문 block 외 내용을 근거로 쓰지 않는다. **공통 계약의 `card:<normalized_id>`는 문서 간 충돌한다.** 추천은 `card:<source_sha256>:<ordinal>:<normalized_id>`이며 이번 준비 출력만 이 ID를 사용했다. 대안은 manifest UUID+inventory ID; 최종 계약 변경은 사용자 검토 때 한다.

1층 출력은 공통 계약 §6의 Extract 필드·10개 type 그대로다. batch마다 입력 unit 전체가 정확히1회 나와야 하며 unknowns는 빈 데이터 보정용이 아니다. 숫자 constraint는 typed value/unit·해당 block의 quote와 연결한다. quote/locator/ID/숫자 실패는 `needs_human_review`; 자동 교정이나 근거 없는 재시도 없음.

대조 출력 초안: `{unit_id,fit_status:met|gap|unknown,constraint_results:[{constraint_index,status,fact_ids,path_ids,reason_code}],evidence_ids}`. direct+confirmed+모든 필수 제약 통과일 때 met, 확인된 반대 사실만 gap, partial/경로없음/단위비교불가/unknown은 unknown. 모델이 compare를 덮어쓸 수 없다. 역할은 type whitelist로 입력을 나눠 `{role,unit_findings,cautions,evidence_refs}`; 종합은 역할3개와 고정 대조만 받아 공통 계약 §7·8의 다섯 블록과 conflicts를 만든다. 역할 불일치는 삭제하지 않는다. 이 설계에서 종합 입력의 '역할만' 규칙과 대조 전달은 spec에서 명시적으로 정합화할 사항이다.

저장은 attempt FK를 가진 extract/compare/role/synthesis 불변 row, stage+batch/role unique key, input/result hash와 status를 제안한다. worker 중단 시 완료된 단계는 보존하되 자동 재개하지 않는다. 재시도는 새 attempt. migration·privileges·head·Pydantic/JSON/runner schema·TS를 한 변경으로 맞춘다.

| 검증 입력 | 기대 결과/검사 경로 |
|---|---|
| 동일 SFR-1이 서로 다른 문서/표에 존재 | 고유 unit 유지, 원문·행 중복 삭제 없음; unit builder 단위 검사 |
| 8장 이하이나 한 장이 12,000자 초과 | 자르지 않고 준비 실패/사람 검토; 승인된 분할 대안이 정해지기 전 fail closed |
| quote 타 block/없는 ID/숫자 불일치/누락 unit/중복 unit | stage 거부, 부분 결과 보존; validator + runner 계약 검사 |
| unknown 자격, confirmed false 자격, partial 경로 | 각각 unknown/gap/unknown; 결정적 대조 표 검사 |
| 2억원 vs 200백만원, 종료일 포함/미포함, 단위 null | 승인된 단위 규칙만 비교, 모호하면 unknown; 경계값 검사 |
| preview 뒤 정책·회사·문서 변경, 다른 회사 attempt | 생성/claim 전 차단; PostgreSQL/API 검사 |
| 중복 claim·timeout·repair 실패 | 슬롯1·불변 row·종결 상태 보존; worker PostgreSQL 검사 |
| 모델 없는 mock 성공/부분/실패 | HP04 계약 연결 확인일 뿐 실제 모델 성공 아님 |

구현 순서는 unit·계약 → 불변 저장/migration → extract 검증 → compare → 역할/종합 → worker/REST → 격리 1건 실제 검증이다. 검사 실행은 리더 한 명, 리뷰는 결과 재사용. 실제 모델 실행은 D1/D2/D4/D5 동결과 승인된 입력이 마련된 뒤다.

D4 추천은 8장/12,000자를 시작점으로 두되 **40분 목표와 3600초 timeout은 다르다**고 계약에 명시하는 것(대안: 2400초 hard timeout). 70unit 기본13호출이며 문자 제한 때문에 batch가 더 늘 수 있고 repair1을 포함하면 최대 호출 수를 따로 고정해야 한다. 무한 repair 금지. D5의 여섯 업무 범주는 기존5 taxonomy label과 1:1이 아니므로 label 하나로 모두 선별하지 말고 명시적 제목/section selector와 제외 목록을 동결하는 안을 추천한다.
