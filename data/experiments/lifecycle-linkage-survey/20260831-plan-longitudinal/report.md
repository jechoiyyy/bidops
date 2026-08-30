# 생애주기 연결 조사 — 20260831-plan-longitudinal

수행 시각: 2026-08-31T00:11:16.060394+09:00

## A. 발주계획 갱신 재관측

- 기준 관측: 997건
- 재조회 관측: 997건
- 공통 레코드: 997건
- 값이 바뀐 레코드: 9건

| 변경된 필드 | 건수 |
|---|---|
| `bidNtceNoList` | 9 |
| `ntceNticeYn` | 8 |

## order_plan — 용역 발주계획 현황

- endpoint_id: `g2b_order_plan_service_pps_search_v1`
- 조회 구간: 202608240000 ~ 202608262359 (반개구간)
- 수집 건수: 997건, page 2개

### 연결 키 존재 여부

| 필드 | 상태 | 채움 |
|---|---|---|
| `orderPlanUntyNo` | 존재 | 997/997 |
| `bidNtceNoList` | 존재 | 465/997 |
| `rcritRgstNo` | 존재 | 0/997 |
| `bfSpecRgstNo` | 응답에 없음 | unknown |
| `ntceNticeYn` | 존재 | 997/997 |

### 전체 필드

| 필드 | 채움 | 비율 | 예시 |
|---|---|---|---|
| `agrmntYn` | 997/997 | 100.0% | N |
| `atchFileExistnceYn` | 997/997 | 100.0% | N |
| `bdgtDivCd` | 0/997 | 0.0% | - |
| `bidNtceNoList` | 465/997 | 46.6% | R26BK01698278000 |
| `bizNm` | 997/997 | 100.0% | 2027학년도 2학년 제주도 수학여행 위탁용역  |
| `bsnsDivCd` | 997/997 | 100.0% | 03 |
| `bsnsDivNm` | 997/997 | 100.0% | 일반용역 |
| `bsnsTyCd` | 970/997 | 97.3% | 신120001 |
| `bsnsTyNm` | 970/997 | 97.3% | 신규(단기) |
| `chgDt` | 78/997 | 7.8% | 2026-08-24 22:30:12 |
| `cnsttyDivNm` | 0/997 | 0.0% | - |
| `cnstwkPrdCntnts` | 0/997 | 0.0% | - |
| `cnstwkRgnNm` | 0/997 | 0.0% | - |
| `cntrctMthdNm` | 997/997 | 100.0% | 제한경쟁 |
| `deptNm` | 997/997 | 100.0% | 학년지원부 |
| `dsgnDocRdngPlceNm` | 0/997 | 0.0% | - |
| `dsgnDocRdngPrdCntnts` | 0/997 | 0.0% | - |
| `dtilPrdctClsfcNo` | 0/997 | 0.0% | - |
| `dtilPrdctClsfcNoNm` | 0/997 | 0.0% | - |
| `jrsdctnDivCd` | 997/997 | 100.0% | 소110003 |
| `jrsdctnDivNm` | 997/997 | 100.0% | 교육기관 |
| `ntceNticeYn` | 997/997 | 100.0% | Y |
| `nticeDt` | 997/997 | 100.0% | 2026-08-25 18:56:27 |
| `ofclNm` | 997/997 | 100.0% | <담당자 정보 · 예시 생략> |
| `orderContrctAmt` | 997/997 | 100.0% | 0 |
| `orderEtcAmt` | 997/997 | 100.0% | 0 |
| `orderGovsplyMtrcst` | 997/997 | 100.0% | 0 |
| `orderInsttCd` | 997/997 | 100.0% | 7430073 |
| `orderInsttNm` | 997/997 | 100.0% | 대전광역시교육청 충남기계공업고등학교 |
| `orderMnth` | 997/997 | 100.0% | 04 |
| `orderNtntrsAuxAmt` | 997/997 | 100.0% | 0.0 |
| `orderPlanDtlUrl` | 997/997 | 100.0% | https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=R26… |
| `orderPlanSno` | 997/997 | 100.0% | 0 |
| `orderPlanUntyNo` | 997/997 | 100.0% | R26DD20854235 |
| `orderThtmContrctAmt` | 997/997 | 100.0% | 0.0 |
| `orderYear` | 997/997 | 100.0% | 2027 |
| `prcrmntMethd` | 997/997 | 100.0% | 자체조달 |
| `prdctClsfcNo` | 0/997 | 0.0% | - |
| `prdctClsfcNoNm` | 0/997 | 0.0% | - |
| `qtyCntnts` | 997/997 | 100.0% | 0 |
| `rcritRgstNo` | 0/997 | 0.0% | - |
| `rmrkCntnts` | 0/997 | 0.0% | - |
| `specCntnts` | 0/997 | 0.0% | - |
| `specItemCntnts1` | 0/997 | 0.0% | - |
| `specItemCntnts2` | 0/997 | 0.0% | - |
| `specItemCntnts3` | 0/997 | 0.0% | - |
| `specItemCntnts4` | 0/997 | 0.0% | - |
| `specItemCntnts5` | 0/997 | 0.0% | - |
| `specItemNm1` | 0/997 | 0.0% | - |
| `specItemNm2` | 0/997 | 0.0% | - |
| `specItemNm3` | 0/997 | 0.0% | - |
| `specItemNm4` | 0/997 | 0.0% | - |
| `specItemNm5` | 0/997 | 0.0% | - |
| `sumOrderAmt` | 997/997 | 100.0% | 131125670 |
| `sumOrderDolAmt` | 0/997 | 0.0% | - |
| `telNo` | 997/997 | 100.0% | <담당자 정보 · 예시 생략> |
| `totlmngInsttNm` | 974/997 | 97.7% | 대전광역시교육청 |
| `unit` | 0/997 | 0.0% | - |
| `usgCntnts` | 0/997 | 0.0% | - |

