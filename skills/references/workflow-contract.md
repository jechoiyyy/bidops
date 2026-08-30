# BidOps 검증 산출물 계약

세 skill은 JSON 파일로 연결한다. 모든 파일은 UTF-8이며, 날짜·시간은 원문 값과 함께 `Asia/Seoul` 기준을 유지한다.

계약을 어긴 파일은 다음 단계의 스크립트가 오류로 중단시킨다. 누락된 필드를 기본값으로 채우는 동작은 어느 단계에도 없다. 판정에 필요한 내용이 없으면 산출물이 만들어지지 않는 것이 정상이다.

| 파일 | 스키마 | 작성 주체 |
|---|---|---|
| `collected-notices.json` | `bidops.collected.v2` | `collect_notices.py` |
| `collected-order-plans.json` | `bidops.collected-order-plans.v1` | `collect_order_plans.py` |
| `validation-set.json` | `bidops.validation-set.v2` | `select_validation_sample.py` |
| `screening-decisions.json` | `bidops.decisions.v2` | **에이전트가 직접 작성한다** |
| `screening-results.json` | `bidops.screening.v2` | `build_screening_results.py` |
| `review-feedback.yaml` | `bidops.feedback.v2` | `render_report.py`가 빈 양식을 만들고 담당자가 채운다 |

---

## 수집 결과

`collected-notices.json`의 최상위 구조는 다음과 같다.

```json
{
  "schema_version": "bidops.collected.v2",
  "generated_at": "2026-08-24T07:41:00+00:00",
  "source_window": {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"},
  "counts": {"total": 0, "candidate_pool": 0, "audit_pool": 0},
  "warnings": [],
  "notices": []
}
```

각 `notices[]` 항목은 다음 필드를 포함한다.

| 필드 | 내용 |
|---|---|
| `notice_id` | 공고번호·차수 또는 사전규격번호를 이용한 안정 식별자 |
| `source_type` | `bid_notice` 또는 `pre_spec` |
| `title`, `agency`, `published_at`, `deadline_at`, `budget`, `estimated_price`, `method`, `url` | 정규화된 기본 정보 |
| `procurement_class` | 조달 분류. `large`, `middle`, `detail`, `code`를 포함한다 |
| `region_limit` | 지역 제한. `basis`, `joint_contract_regions`, `joint_contract_rate`, `regional_joint_contract_limit`을 포함한다 |
| `lifecycle` | 공고 생애주기. `pre_spec_no`, `re_notice`, `changed_at`, `change_reason`, `unified_notice_no`, `previous_failed_notice_no`와 선택적 `order_plan_no`를 포함한다. `order_plan_no`는 원문 `orderPlanUntyNo`의 optional v2 projection이다 |
| `qualification_flags` | 참가제한, 업종제한, 정보사업 여부, 실적제한경쟁, PQ·기술평가 여부와 배점 등 API가 직접 제공한 자격 관련 플래그 |
| `attachments` | API가 제공한 첨부 문서 이름과 URL |
| `focus_matches` | 정규화 개념 일치 신호의 목록. 의미 판정 결과가 아니다 |
| `performance_matches` | 회사소개서 41–46페이지 사업명과 비교한 상위 탐색 신호 |
| `performance_top_score` | 임계값 미만이라 `performance_matches`에 오르지 못한 경우를 포함한 최고 유사도 |
| `candidate_sources` | 후보군 편입에 기여한 신호의 목록 |
| `collection_bucket` | `candidate_pool` 또는 `audit_pool` |
| `unknown_fields` | API 응답에서 확인되지 않은 주요 정보 |
| `raw_source` | 이 항목을 만든 원문 페이지 파일의 상대 경로 |

### 개념 일치 신호의 출처 기록

`focus_matches`는 축별 문자열 목록이 아니라 신호 하나마다 출처를 남긴 객체의 목록이다.

```json
{
  "axis": "공공 SI·통합관리",
  "label": "정보시스템",
  "matched_field": "pubPrcrmntClsfcNm",
  "matched_text": "정보시스템",
  "field_kind": "classification"
}
```

`field_kind`는 `title`, `classification`, `other` 가운데 하나이다. 조달 분류명은 모든 용역 공고에 일괄 부여되는 라벨이므로, 공고 제목에 등장한 개념과 같은 무게로 취급하면 안 된다. 판정 단계는 `field_kind`를 확인하여 신호의 근거 강도를 구분해야 한다.

`candidate_sources`는 `focus_title`, `focus_classification`, `performance_similarity` 가운데 해당하는 값을 담는다. `collection_bucket`은 `candidate_sources`가 비어 있지 않으면 `candidate_pool`이다.

## 발주계획 수집 결과

`collected-order-plans.json`은 공고 목록과 별도의 누적 발주계획 계약이다.

```json
{
  "schema_version": "bidops.collected-order-plans.v1",
  "generated_at": "2026-08-29T01:00:00+00:00",
  "source_window": {"from": "2026-08-25", "to": "2026-08-26", "timezone": "Asia/Seoul"},
  "counts": {"total": 0},
  "warnings": [],
  "order_plans": []
}
```

각 `order_plans[]`는 `order_plan_unty_no`(원문 `orderPlanUntyNo`), `title`(`bizNm`),
기관·업무·서비스(`orderInsttCd`, `orderInsttNm`, `totlmngInsttNm`, `bsnsDivCd`,
`bsnsDivNm`, `bsnsTyCd`, `bsnsTyNm`), 금액(`sumOrderAmt`, `orderContrctAmt`),
예정 시기(`orderYear`, `orderMnth`), 방식(`prcrmntMethd`, `cntrctMthdNm`),
`published_at`/`changed_at`(`nticeDt`/`chgDt`), `bid_ntice_no_list`(`bidNtceNoList`),
`notice_posted`(`ntceNticeYn`), `rcrit_rgst_no`(`rcritRgstNo`), `source_url`(`orderPlanDtlUrl`),
`first_discovered_at`, `last_discovered_at`, `source_sha256`, `unknown_fields`, `raw_source`를
담는다. `rcritRgstNo`의 현재 빈 값은 `null`로 남기고, 측정되지 않은 SW 상태는
`sw_business_status: null`과 `unknown_fields`로 분리한다. `bidNtceNoList`와 `ntceNticeYn`만
전환 비교 신호로 쓰며 `chgDt`는 보존만 한다.

artifact `metadata`에는 `bsnsDivNm` allowlist인 `일반용역`·`기술용역`과
`200412`~`999912` 발주월 보조 범위를 남긴다. 범위 밖 원문 건수는 `counts`에서 확인한다.

### 수행실적 탐색 신호

`performance_matches[]`는 `project_name`, `source_page`, `similarity`, `common_fragment`, `legal_qualification_status`를 포함한다. `legal_qualification_status`는 확인 자료가 없으므로 항상 `unknown`이다.

---

## 검증 표본

`validation-set.json`은 수집 항목에 `sample_role`과 `sample_stratum`을 추가한다.

- `sample_role`: `analysis` 또는 `audit`
- `sample_stratum`: 분석 표본은 `AI/데이터`, `블록체인·DID`, `공공 SI·통합관리`, `수행실적 유사` 가운데 하나이며, 감사 표본은 `분류 근접`, `실적 유사 근접`, `무작위` 가운데 하나이다

분석 표본은 세 우선 축과 `수행실적 유사` 층을 순환하며 뽑는다. 감사 표본은 제외 정답이 아니라 1차 분류가 놓친 사례를 찾기 위한 표본이므로, 무작위 추출만으로 구성하지 않는다. 조달 분류가 디지털 사업군이면서 후보에 들지 못한 공고와 수행실적 유사도가 임계값 바로 아래인 공고를 우선 배정한다.

---

## 판정 입력: 에이전트가 작성하는 파일

`screening-decisions.json`은 이 워크플로에서 LLM이 직접 작성하는 유일한 파일이다. 아래 필드는 전부 필수이며, 하나라도 없으면 병합 단계가 오류로 중단된다.

```json
{
  "schema_version": "bidops.decisions.v2",
  "screening_basis": "판정에 사용한 정보 범위를 한 문장으로 기술한다.",
  "judgments": [
    {
      "notice_id": "bid:R26BK01689645:000",
      "grade": "우선 검토",
      "readiness": "부분 확인 필요",
      "primary_focus": "AI/데이터",
      "exclusion_category": null,
      "summary": "",
      "perspectives": [],
      "matched_performances": [],
      "counterarguments": [],
      "verification_items": [],
      "next_action": ""
    }
  ]
}
```

### 관점

`perspectives[]`는 아래 다섯 관점을 **모두** 포함해야 하며 이름은 정확히 일치해야 한다.

| 관점 이름 | 답해야 하는 질문 |
|---|---|
| `기술 적합성` | 공고가 요구하는 기술과 수행 역할을 회사가 보유하고 있는가 |
| `실적 정합성` | 회사소개서의 수행실적이 이 과업과 실제로 대응하는가 |
| `공공 SI 적합성` | 시스템 구축·고도화·운영·통합·ISP/BPR 가운데 어디에 해당하는가 |
| `사업성·자격 제약` | 예산, 지역, 업종, 실적 요건, 참여 형태가 참여를 제약하는가 |
| `전략 부합` | 세 우선 축과 신규 진출 방향에 부합하는가 |

각 항목은 `name`, `assessment`, `reason`, `evidence`를 가진다.

- `assessment`: `적합`, `부분 적합`, `부적합`, `확인 불가` 가운데 하나
- `reason`: 이 관점에서만 나올 수 있는 판단을 서술한다. 다른 관점의 결론을 옮겨 적지 않는다
- `evidence[]`: `source`, `status`, `fact`를 가지며 최소 한 건이 필요하다. `status`는 `confirmed`, `inferred`, `unknown` 가운데 하나이다. 공고 근거는 사용한 필드 이름을, 회사 근거는 `company-profile.md`의 절 번호와 그 절의 상태를 `source`에 적는다

### 반론

`counterarguments[]`는 최소 한 건이 필요하며, 각 항목은 이 공고에서만 성립하는 반론이어야 한다. 모든 공고에 붙일 수 있는 상투구는 반론이 아니다. 동일한 문장이 전체 판정의 40%를 넘게 반복되면 병합 단계가 오류로 중단된다.

### 확인 항목

`verification_items[]`는 `item`, `why`, `blocking`, `status`를 가진다. `blocking`은 입찰 참여 자체를 막는 항목인지를 나타내는 불리언이다. `status`는 `미확인` 또는 `확인 완료`이다.

- `readiness`가 `부분 확인 필요`이면 최소 한 건이 필요하다
- `readiness`가 `확인 완료`이면 `blocking`이 참인 미확인 항목이 있으면 안 된다
- `readiness`가 `참여 불가 확인`이면 `blocking`이 참인 항목이 최소 한 건 필요하다

### 등급과 참여 준비 상태

`grade`는 `우선 검토`, `검토 권장`, `관찰 대상`, `제외` 가운데 하나이며, `readiness`는 `확인 완료`, `부분 확인 필요`, `참여 불가 확인`, `해당 없음` 가운데 하나이다.

두 축은 독립적이다. 자격 조건이 확인되지 않았다는 이유만으로 등급을 낮추지 않고 `부분 확인 필요`로 표시한다.

`grade`가 `제외`이면 `readiness`는 `해당 없음` 또는 `참여 불가 확인`이어야 한다. 검토하지 않기로 한 공고에 `확인 완료`를 부여하면 확인을 마쳐 참여할 수 있다는 뜻으로 읽히기 때문이다. 또한 `제외`일 때는 `exclusion_category`가 필수이며, 그 외의 등급에서는 `null`이어야 한다.

`exclusion_category`는 다음 값 가운데 하나이다: `도메인 불일치`, `시설·현장 용역`, `공사·인프라`, `행사·교육·홍보`, `연구·조사`, `감리·평가`, `물품·임차`, `자격 미달`, `취소·종료`, `기타 비관련`.

### 수행실적 연결

`notice.performance_matches`가 비어 있지 않으면 `matched_performances[]`도 비어 있으면 안 된다. 탐색 신호를 검토했다는 사실 자체를 기록으로 남기기 위해서이다. 각 항목은 `name`, `match_reason`, `mismatch_or_limit`, `source`, `status`를 가진다. `mismatch_or_limit`에는 유사도가 설명하지 못하는 차이를 반드시 적는다.

---

## 판정 결과

`build_screening_results.py`는 표본과 판정을 대조하여 `screening-results.json`을 만든다.

```json
{
  "schema_version": "bidops.screening.v2",
  "generated_at": "",
  "screening_basis": "",
  "source_window": {},
  "results": [{"notice": {}, "judgment": {}}]
}
```

`judgment`는 `screening-decisions.json`의 항목에서 `notice_id`만 제거한 값이다. 병합 단계는 값을 추가하거나 보정하지 않으며, 검증과 결합만 수행한다.

---

## 리뷰 피드백

```yaml
schema_version: bidops.feedback.v2
reviews:
  - notice_id: ""
    disposition: null       # 심층 검토 진행 | 관찰 | 제외
    system_judgment_review: null   # 동의 | 등급 수정 | 근거 부족
    corrected_grade: null
    corrected_readiness: null
    weakest_perspective: null      # 근거가 가장 부족했던 관점 이름
    reason: ""
    verification_answers: []
```
