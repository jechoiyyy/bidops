# HP-04 정보 구성·상태·REST 초안 (미구현)

회사 사전규격 상세의 판정 탭을 제안한다. 기존 `web/frontend/src/lib/companyApi.ts`와 `pages/CompanyPreSpecsPage.tsx`에서 회사 선택/조회 계보를 재사용하며 실제 상세 컴포넌트 분리는 구현 시 확인한다. 다음은 정보 설계이며 UI를 만들거나 브라우저 검증한 결과가 아니다. 구현 때 Astryx build→layout→component 조회 절차를 따른다.

| 순서 | 정보 | 상호작용/근거 |
|---|---|---|
| 1 판정 | 진행 가능/조건부 진행/진행 어려움/판단 불가, 한 줄 사유, 차단 수, 참조 표식, 실행시각·정책 | 보조 의견임을 표시. 사람 Go/No-Go/추적 상태와 분리 |
| 2 조건 | qualification_track_record / staffing_onsite / amount_period / technology / operations_sla_security | 각 met/gap/unknown의 근거를 펼쳐 source unit·회사 fact 확인 |
| 3 매트릭스 | unit ID·요구명·type·대조상태·역할 의견·쪽 | type/status 필터, 결과 수, 기본 gap→unknown→met 후 문서순 제안 |
| 4 주의 | 확인 필요, 위험, 역할 의견 불일치 | conflicts를 별도 소제목으로 보존; 자동 해소 없음 |
| 5 다음 행동 | 누가/무엇/근거/확인 상태 | 안내만 제공. 자동 연락·입찰·추적 승인 없음 |

| 상태 | 표시와 동작 |
|---|---|
| 결과 없음 | “분석 결과 없음”; 기존 preview 진입. 0점/판단 불가 결과로 합성하지 않음 |
| 준비/대기/실행 | stage와 시각, 완료된 부분의 범위; 최종 판정은 빈 상태 |
| 완료 | 다섯 블록. `quality_status=unmeasured_reference|mock_reference`면 참조 표식 유지. null이면 품질 미확정으로 그대로 보존 |
| 실패/needs_human_review/timeout | 안전한 error_code와 사람 확인 안내; 부분 근거만 열람, 성공 카드 없음 |
| 과거/legacy 결과 | 현재 회사·정책·문서와 다른 이유 명시, 과거 attempt 조회 가능. 새 결과로 합치지 않음 |
| met/gap/unknown | 충족/부족/미확인; unknown을 경고색의 부족으로 표시하지 않음 |
| mapped/partial | 직접 쪽 점프; partial은 일부 위치만 확인임을 표시 |
| inherited | “앞 문단에서 상속한 쪽” 표시 후 점프. 원문 정확 쪽으로 단정하지 않음 |
| unavailable | “쪽 미확인”, 쪽 점프 비활성. block/table 근거는 열람 가능 |

REST 제안(D6): `GET /api/companies/{company_id}/pre-specs/{notice_id}/verdict`와 동일 경로 `?attempt_id=<uuid>`로 과거 특정 결과 조회. 읽기 전용이며 동작 시작은 기존 preview/승인 경로만 쓴다. 다른 회사 소유 자료/attempt는 404, 잘못된 query는 422. 결과 없음은 200+`availability=none,result=null`을 추천하며 대안은 404(빈 상태와 자료 접근 실패 구분이 불편). 응답 초안:

```text
{schema_version:"bidops.practitioner-verdict-view.v1",
 company_id, notice_id, attempt_id:null|uuid,
 availability:none|pending|running|completed|failed|needs_human_review,
 is_current, stale_reasons:[], quality_status:null|unmeasured_reference|mock_reference,
 identity:{policy_id,policy_sha256,model,reasoning_effort,cli_version}|null,
 source_binding:{document_versions,company_version_id,ontology_sha256}|null,
 result:null|{verdict,reason,blocking_condition_ids,checklist:[{key,status,evidence_refs}],
 matrix:[{unit_id,type,fit_status,role_findings,evidence_refs,page_range,mapping_status}],
 cautions,conflicts,next_actions},
 partial_stage_ids:[], error_code:null|string}
```

availability는 기존 실행 상태를 이 view에 투영하는 초안이며 새 DB 상태를 만들자는 뜻이 아니다. schema·enum 상세는 HP03 spec과 함께 고정한다. evidence_refs는 소유권 검사 가능한 source/version/block/fact 식별자만 포함하며 파일 경로·버킷 자격증명·원문 전체를 응답하지 않는다. unit ID는 HP03의 문서 간 충돌 해결안과 동결한다.

검사 계획: API 회사/attempt 교차 접근·현재/과거 계보·null 표식·실패/부분 shape; PostgreSQL 변형 포함. 화면은 API mock으로 각 상태, 필터 결과 수, unavailable 클릭 금지와 inherited 안내를 의미 검사하고 1280×800·1440×900에서 구조/가로 넘침을 확인한다. actual API 연결도 별도 1사례 확인한다. 모바일 화면은 만들지 않는다.

D3 추천은 DEMO 3사 row를 보존한 채 HP 화면 회사 목록만 필터링하는 설정이다. 대안은 모든 회사에서 탭을 보이고 미지원 안내. row 삭제·비활성화로 정리하지 않는다. D6은 위 경로 및 current/attempt 분리를 추천한다. 기본 정렬과 conflicts 위치는 제품 판단으로 미확정이다.
