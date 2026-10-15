# HP-04 — spec

근거: intent.md, HP03 spec의 모든 결과 타입, HP 공통 계약 §8. 화면은 판정을 다시 계산하지 않는다.

## API 계약

`GET /api/companies/{company_id UUID}/pre-specs/{notice_id int}/verdict?attempt_id=<UUID>`를 company_reads router/service에 추가한다. attempt 미지정은 해당 회사·공고 최신 생성 시각/UUID 내림차순 HP attempt(동률 UUID)다. 다른 회사/공고 attempt는 404, 잘못된 경로·query는422. 회사/공고 존재 확인 후 실행이 없으면200 none. legacy narrative attempt 명시 선택은200 legacy(no HP result). DB 불가503, 안전 projection 오류500 processing_failed. GET은 생성·모델 호출을 하지 않는다.

schema_version="bidops.practitioner-verdict-view.v1". 다음 키 전부 필수, 추가키 없음:

- company_id(UUID), notice_id(int), attempt_id(UUID|null), availability(none|pending|running|completed|failed|needs_human_review|legacy), is_current(bool), stale_reasons(string[]).
- quality_status=measured|unmeasured_reference|mock_reference|null(저장 값 그대로; HP 신규 실제 실행은 unmeasured_reference).
- identity=null|{policy_id:UUID,policy_sha256:Hash,model:string,reasoning_effort:string,cli_version:string}.
- source_binding=null|{document_versions:[{document_version_id:UUID,source_sha256:Hash}],company_version_id:UUID,company_sha256:Hash,ontology_sha256:Hash}. company_version_id는 graph_version_id다. policy/identity와 source는 선택 attempt의 동결 값, 최신 값으로 덮지 않는다.
- result=null|{verdict,reason,blocking_condition_ids,checklist,matrix,cautions,conflicts,next_actions}. verdict/reason/blocking IDs/cautions/actions는 HP03 synthesis, conflicts는 HP03 코드 계산이다.
- checklist={key,status,evidence_refs}[] 정확히5개, 순서 qualification_track_record/staffing_onsite/amount_period/technology/operations_sla_security. status=met|gap|unknown. key별 source unit은 각각 자격·실적 / 인력 / amount 또는 duration 또는 date constraint / 기술·기능 / 운영·성능SLA·보안이다. 대상없음=unknown; 한 gap이라도 gap, 그 외 모두met이면met, 아니면unknown. evidence_refs는 HP03 Evidence[]의 유효근거 합집합이다.
- matrix={unit_id,type,fit_status,role_findings,evidence_refs,page_range,mapping_status}[]: role_findings={role,assessment,reason,evidence_refs}[], type/Fit/role/Evidence는 HP03와 동일. page_range=null|{first:positive int,last:positive int}, first<=last. mapping_status=mapped|partial|inherited|unavailable. unavailable이면 range null. matrix는 gap→unknown→met, 동률 frozen unit 순서.
- partial_stage_ids(UUID[]), error_code(string|null), missing_sections(HP03 section enum[]), started_at/finished_at(RFC3339|null) 추가 필수. 단계 id는 검증된 hp_analysis_stage만 포함한다.
- partial_matrix는 matrix와 같은 row[]이며 completed가 아니면 검증 완료된 compare만 보여 준다. completed일 때 빈 배열이다. 최종 result는 모든 단계·근거/coverage 검사가 성공한 completed에만 값이 있다. failed의 부분표를 최종 판정으로 합성하지 않는다.

stale_reasons 집합=company_changed|ontology_changed|documents_changed|policy_changed|superseded. 현재성은 기존 currentness 규칙과 동결 hash 비교로 서버가 계산한다. none은 is_current=false/stale_reasons=[]/identity/source/result=null/배열[]/시각null/qualitynull/errornull. legacy도 result/partial_matrix=null이 아니라 result=null, partial_matrix=[]이며 기존 attempt identity·시각·품질만 있는 대로 표시한다. 없는 binding은 null이다.

attempt queued→pending, running→running, completed→completed; failed 중 HP 검증/timeout/selector누락 code는 needs_human_review, 그 외 failed. superseded는 원래 결과 가용성에 따라 completed 또는 failed로 보이고 stale_reasons에 superseded 추가; 완성 result 없는 superseded는failed. 기존 DB enum은 바꾸지 않는다.

## UI

기존 회사 사전규격 상세 안에 다섯 블록: 판정 요약·조건 체크리스트·요구사항 표·주의 포인트·다음 행동. 행마다 근거 펼치기와 기존 문서 API 링크를 쓴다. inherited는 ‘앞 문단에서 상속한 추정 쪽’, partial은 ‘일부 매핑’, unavailable은 ‘쪽 미확인’과 점프 없음. URL은 기존 document_version 접근 fence 뒤 서버 API로 생성하며 filesystem/object 경로를 노출하지 않는다.

미시작은 분석 요청 경로 안내, pending/running은 진행 상태와 검증된 부분표, 실패는 안전한 오류·부분표·새 attempt 재시도 안내. legacy는 기존 보고서 링크, stale은 과거 기준을 명시한다. quality=null은 ‘표식 없음’. 충돌은 주의 영역에서 역할별로 함께 표시하고 사라지지 않는다. 모델 판정/추적 승인/Go-NoGo를 별도 표시하고 새 자동결정 action은 만들지 않는다.

HP 화면 회사 선택에는 hp-onweb만 노출한다. 기존 회사 목록 API나 DB row 삭제/권한 변경은 하지 않는다. hp-onweb 미등록이면 준비 필요 상태, 다른 회사로 fallback 없음. 설정/로그인/편집 UI 신규 없음. Astryx discover/layout/component 확인 후 기존 테마 토큰·Table을 사용한다. 데스크톱1280x800/1440x900에서 긴 원문·키보드·오류를 검사한다.

## 테스트 케이스

| ID | 입력 | 기대 결과 |
|---|---|---|
| T1 | none/legacy 및 잘못된query/다른회사attempt | 정확한200/404/422, 비밀 없음 |
| T2 | PostgreSQL complete/failed/partial/stale/동률attempt | 정확한projection·정렬·최신성·null 보존 |
| T3 | 다섯블록/긴문장/키보드/두viewport | 의미·구조 통과, build strict |
| T4 | mapped/partial/inherited/unavailable·충돌 | 올바른쪽표시·추정표시·점프차단·역할보존 |
| T5 | mock 진행→부분실패·회사미등록·품질null | 실패가 최종성공으로 보이지 않음, 서버외부fallback 없음 |
| T6 | bidops-local 기존 승인 결과 조회 | 실제 REST→화면 연결, 모델 재실행 없이 검증 |

저장 migration 없음; HP03 저장 결과의 읽기 투영만 추가. frontend proof는 build+관련 화면 spec, API/DB shape는 임시 PostgreSQL을 포함한다.
