# 회사 프로필

> 목적: AI 에이전트, 제안서 작성, 사업기회 분석, 기술·레퍼런스 매칭 등 여러 서비스에서 공통으로 참조할 수 있는 회사 기준 정보
> 프로필 기준 시점: 2026-08
> 정보 상태: `confirmed` = 소개서에서 직접 확인, `inferred` = 소개서의 최근 포지셔닝·실적에서 도출, `unknown` = 자료만으로 확인 불가

---

# 1. Company Identity

```yaml
company:
    name: "주식회사 루트랩"
    ceo: "김종현"
    established: "2022-09-23"
    business_type: "소프트웨어 및 하드웨어 개발/공급"
    headquarters: "대구광역시"
    employees:
        value: 58
        as_of: "2026-08"
        status: confirmed
    rnd_ratio:
        value: "70%"
        status: confirmed
    revenue_2025:
        value: "38억원"
        status: confirmed
        note: "회사소개서에 정부용역사업 21억원이 별도 표기되어 있으며, 두 금액의 포함 관계는 자료만으로 확정하지 않음"
    credit_rating:
        value: "BBO"
        status: confirmed
    project_solution_count:
        value: "151건 이상"
        status: confirmed
    inhouse_solution_ratio:
        value: "주요 솔루션 100% 자체개발로 소개"
        status: confirmed
```

---

# 2. Company Capability

## 2.1 보유 기술

### AI / LLM / AI Agent

```yaml
capability:
    status: confirmed
    evidence_level: strong
    technologies:
        - "생성형 AI / LLM 기반 정보 분석"
        - "AI Agent 기반 업무자동화"
        - "AI 기반 의사결정 지원"
        - "AI 기반 보고서 생성"
        - "빅데이터 분석 및 예측"
        - "패턴·트렌드·감성 분석"
        - "AI 학습모델 개발"
        - "영상 분석 / 객체·행동 인식 / 자세 추정"
```

대표 근거:
- AI 공보관
- AI Agent 기반 R&D 분석·의사결정 플랫폼
- 공공 AI 영향평가 세부설계 및 제도화 방안 연구
- 소방예방정보시스템 기능 고도화

### 데이터 / 빅데이터 / 표준화·연계

```yaml
capability:
    status: confirmed
    evidence_level: very_strong
    technologies:
        - "공공·행정·산업 데이터 수집 및 통합"
        - "데이터 표준화 및 품질관리"
        - "기관 간 API·시스템 연계"
        - "빅데이터 분석 및 시각화"
        - "데이터 기반 예측 및 의사결정 지원"
        - "공공 마이데이터 연계"
```

### 블록체인 / DID / 디지털 증명

```yaml
capability:
    status: confirmed
    evidence_level: very_strong
    technologies:
        - "DID 기반 신원인증"
        - "블록체인 메인넷 구축·운영"
        - "전자증명서·전자지갑"
        - "디지털배지·학습이력 증명"
        - "NFT 기반 인증·디지털자산 관리"
        - "스마트컨트랙트"
        - "블록체인 기반 데이터 이력·위변조 방지"
```

대표 근거:
- 대구형 블록체인 메인넷
- 블록체인 시민체감서비스 다대구
- 한국조폐공사 통합전자지갑
- KOGAS형 DID 출입관리
- 고등평생교육 디지털배지 플랫폼
- 부산 자원봉사은행

### 온톨로지 / 지식그래프

```yaml
capability:
    status: confirmed
    evidence_level: limited
    technologies:
        - "이기종 데이터 모델링 및 표준화"
        - "산업 도메인 특화 지식베이스 구축"
        - "지식 기반 지능형 데이터 추론"
        - "AI 연계 맞춤형 검색·추천"
```

비고:
- 회사소개서에서 핵심 기술영역으로 명시되어 있음.
- AI·데이터·블록체인과 비교하면 소개서에서 확인 가능한 대표 수행실적은 상대적으로 적음.

### SaaS / Cloud

```yaml
capability:
    status: confirmed
    evidence_level: strong
    technologies:
        - "SaaS 기반 업무시스템"
        - "클라우드 기반 통합관리"
        - "클라우드 기반 데이터 플랫폼"
        - "공공 클라우드 기반 서비스 구축"
```

### SI / 통합관리 / 웹·포털

```yaml
capability:
    status: confirmed
    evidence_level: very_strong
    technologies:
        - "신규 시스템 구축"
        - "기능 고도화"
        - "운영 및 유지관리"
        - "통합관리시스템"
        - "PMS / 평가·접수·심사 시스템"
        - "CMS / 홈페이지 / 포털"
        - "ISP / BPR / 정보화전략"
```

## 2.2 수행 가능 역할

```yaml
delivery_capability:
    status: confirmed
    roles:
        - "정보화전략계획(ISP/BPR)"
        - "정책·기술 연구"
        - "신규 시스템 구축"
        - "기존 시스템 고도화"
        - "운영 및 유지관리"
        - "SaaS 개발 및 공급"
        - "자체 솔루션 개발·공급"
        - "R&D / 실증사업"
        - "데이터 구축·표준화"
        - "AI 모델 및 AI Agent 개발"
        - "공공·민간 데이터/서비스 연계"
```

## 2.3 사업영역

```yaml
business_domains:
    confirmed:
        - "AI·DATA 기반 공공혁신"
        - "디지털 행정"
        - "디지털 재난안전"
        - "디지털 교육"
        - "디지털 헬스케어"
```

세부 수행 도메인:
- 공공행정 및 업무자동화
- 소방·재난안전
- 데이터 플랫폼 및 분석
- 블록체인·DID 기반 공공서비스
- 학습이력·디지털배지·교육 플랫폼
- 의료·헬스케어 데이터
- 산업·R&D 데이터 분석
- SaaS 기반 업무시스템
- 웹·포털·CMS 및 통합관리

## 2.4 대표 수행실적

| 영역 | 대표 사업 | 기관 |
|---|---|---|
| 공공 AI | 공공 AI 영향평가 세부설계 및 제도화 방안 연구 | 행정안전부·NIA |
| AI Agent | AI Agent 기반 R&D 분석·의사결정 플랫폼 | 한국산업기술진흥원 |
| 빅데이터 | 소방안전 빅데이터 플랫폼 | 소방청 |
| 데이터 분석 | 빅데이터 플랫폼 기반 분석서비스 지원 | NIA |
| 재난안전 | 재난안전 영상정보 공유 플랫폼 | NIA |
| 디지털행정 | 블록체인 시민체감서비스 다대구 | 대구광역시 |
| 공공마이데이터 | 공공마이데이터 플랫폼 모이소 | 경상북도 |
| DID | KOGAS형 블록체인 신원증명 출입관리 | 한국가스공사 |
| 전자지갑 | 통합전자지갑 운영·유지관리 | 한국조폐공사 |
| 디지털배지 | 고등평생교육 디지털배지 플랫폼 | KISA |
| 학습이력 | 맞춤배움길·배움이력 전자지갑 | KERIS |
| 헬스케어 | SaaS 기반 K-Dental 플랫폼 | 중소벤처기업부 |
| SaaS 업무 | SaaS 통합평가관리시스템 | 대구테크노파크 |
| 웹·통합관리 | 홈페이지·민원·연구장비·제안서 접수 등 다수 구축/운영 | 공공기관 다수 |

### 수행실적 데이터 유의사항

- 회사소개서 PDF 41–46페이지의 사업명 130건은 [검색용 수행실적 레퍼런스](company-performance-titles.tsv)에 별도로 구조화했다.
- 해당 사업명은 유사 공고를 후보군으로 회수하는 탐색 근거이며, 사업 범위의 동일성이나 입찰 자격 충족을 자동으로 증명하지 않는다.
- 회사 설립일은 2022-09-23임.
- 회사소개서의 수행실적 목록은 2014년부터 제시됨.
- 2022년 이전 실적이 현재 법인의 직접 수행실적인지, 대표자·구성원의 이전 실적인지 자료만으로 확인되지 않음.
- 법적 실적증명이 필요한 경우 별도 원본 증빙 확인이 필요함.

## 2.5 인증·기업역량

```yaml
certifications:
    confirmed:
        - "벤처기업"
        - "전문연구사업자"
        - "기업부설연구소"
        - "Inno-Biz"
        - "Main-Biz"
        - "ISO 9001"
        - "ISO 14001"
        - "ISO/IEC 20000-1:2018"
        - "ISO 45001"
        - "K-PaaS 인증"
        - "클라우드보안인증(CSAP)"
        - "클라우드서비스 확인(KACI)"
        - "기술평가등급 T3"
```

수상:
- 2024 중소벤처기업부 장관표창
- 2025 과학기술정보통신부 장관표창(블록체인)

## 2.6 지식재산권

```yaml
intellectual_property:
    registered_patents:
        value: 8
        status: confirmed
    patent_applications:
        value: 18
        status: confirmed
    major_fields:
        - "블록체인"
        - "DID"
        - "디지털제품여권"
        - "물류·공급망"
        - "IoT 보안"
        - "문서·로그 데이터 관리"
        - "가상현실/스포츠 콘텐츠"
```

## 2.7 인력

```yaml
workforce:
    total:
        value: 58
        as_of: "2026-08"
        status: confirmed
    rnd_ratio:
        value: "70%"
        status: confirmed
    corporate_research_institute:
        value: true
        status: confirmed
    pm_pl_count:
        value: null
        status: unknown
    ai_llm_data_staff:
        value: null
        status: unknown
    ontology_staff:
        value: null
        status: unknown
    blockchain_did_staff:
        value: null
        status: unknown
    technical_grade_distribution:
        value: null
        status: unknown
    staff_certifications:
        value: null
        status: unknown
    available_delivery_staff:
        value: null
        status: unknown
```

## 2.8 솔루션

### 확인된 대표 솔루션/제품군

- **AI 공보관**
    - 뉴스·커뮤니티 데이터 분석
    - 감성분석
    - 보고서 생성
    - 공보 대응 자동화

- **BadgeONE 디지털배지 통합관리 솔루션**
    - 학습이력 관리
    - 디지털배지
    - 전자지갑
    - 발급·검증·제출이력 관리

- **DID/블록체인 기반 디지털 신원·증명**
    - DID 인증
    - 전자지갑
    - 전자증명
    - 출입관리

- **SaaS 통합평가관리**
    - 온라인 접수
    - 평가·심사
    - 결과관리

- **데이터 분석·시각화 플랫폼**
    - 공공/R&D/재난안전 데이터 통합
    - 분석·시각화
    - 의사결정 지원

### 솔루션 관련 미확인 정보

```yaml
solution_unknowns:
    gs_certification: null
    procurement_registration: null
    digital_service_marketplace_registration: null
    product_pricing_policy: null
    saas_subscription_policy: null
    standard_feature_spec: null
    product_technology_stack: null
```

---

# 3. Business Evidence

## 3.1 주요 고객 경험

회사소개서에 공공기관 및 민간기업 32여 곳의 고객사를 보유한 것으로 소개됨.

주요 공공기관 수행 경험:
- 행정안전부
- 소방청
- 한국지능정보사회진흥원(NIA)
- 한국인터넷진흥원(KISA)
- 한국교육학술정보원(KERIS)
- 한국조폐공사
- 한국가스공사
- 대구광역시
- 경상북도
- 대구테크노파크
- 정보통신산업진흥원(NIPA)
- 한국산업기술진흥원
- 한국콘텐츠진흥원
- 한국보건산업진흥원
- 공공 연구·교육기관 및 지역 혁신기관 다수

## 3.2 반복 수행 경험이 확인되는 기관

> 아래 정보는 선호기관을 의미하지 않으며, 소개서의 수행실적에서 반복 관계가 확인되는 기관 정보임.

```yaml
repeated_client_experience:
    - "대구광역시"
    - "대구테크노파크"
    - "한국지능정보사회진흥원(NIA)"
    - "소방청"
    - "한국인터넷진흥원(KISA)"
    - "한국교육학술정보원(KERIS)"
    - "한국조폐공사"
    - "대구디지털혁신진흥원"
    - "구미전자정보기술원"
```

## 3.3 확인 가능한 사업 규모 참고정보

```yaml
business_scale_evidence:
    kisa_blockchain_public_project:
        value: "14억원"
        status: confirmed
        note: "회사소개서의 수주 성과 표기"
    fire_bigdata_platform:
        value: "누적 20억원"
        status: confirmed
        note: "회사소개서의 누적 수주 성과 표기"
    revenue_2025:
        value: "38억원"
        status: confirmed
```

이 항목은 과거 수행규모에 대한 참고정보이며 회사의 선호 예산이나 단독 수행 한도를 의미하지 않음.

---

# 4. Business Preference

## 4.1 관심 분야

회사소개서의 최근 사업 포지셔닝과 수행실적을 기준으로 한 추정 정보임.

```yaml
interested_areas:
    status: inferred
    primary:
        - "공공 AI / 공공 AX"
        - "생성형 AI / LLM"
        - "AI Agent / 업무자동화"
        - "공공·행정 데이터 플랫폼"
        - "데이터 표준화·연계·분석"
        - "디지털 행정"
        - "소방·재난안전"
    established:
        - "블록체인 / DID / 디지털신원"
        - "전자지갑 / 전자증명"
        - "디지털배지 / 학습이력"
        - "SaaS 기반 공공업무시스템"
    expansion:
        - "온톨로지 / 지식그래프 + LLM"
        - "공공 AI 거버넌스 / 영향평가"
        - "디지털 헬스케어 / 의료데이터"
        - "산업·R&D 데이터 분석"
        - "글로벌 SaaS / 블록체인"
```

## 4.2 비관심 분야

```yaml
uninterested_areas:
    value: []
    status: unknown
```

회사소개서만으로 명시적인 비관심 분야를 확인할 수 없음.

## 4.3 선호 사업유형

```yaml
preferred_project_types:
    value: null
    status: unknown
```

수행실적으로는 구축, 고도화, 운영·유지관리, ISP/BPR, 연구, R&D/실증, SaaS 공급 경험이 확인되지만 선호 우선순위는 자료만으로 확정할 수 없음.

## 4.4 선호 기관

```yaml
preferred_institutions:
    value: []
    status: unknown
```

반복 수행기관은 `Business Evidence`에 별도로 관리하며 선호기관으로 자동 해석하지 않음.

## 4.5 선호 예산

```yaml
preferred_budget:
    minimum: null
    preferred_range: null
    solo_upper_limit: null
    consortium_threshold: null
    status: unknown
```

## 4.6 전략 고객

```yaml
strategic_customers:
    value: []
    status: unknown
```

## 4.7 신규 진출 영역

최근 회사소개서의 기술 포지셔닝 및 사업사례를 기반으로 한 추정 정보임.

```yaml
new_business_areas:
    status: inferred
    areas:
        - "공공 AI / AI Agent / 업무자동화"
        - "공공 AI 거버넌스 / 영향평가"
        - "온톨로지·지식그래프 + 생성형 AI"
        - "의료·헬스케어 데이터 플랫폼"
        - "글로벌 SaaS / 블록체인·헬스케어"
```

## 4.8 지역 전략

```yaml
regional_strategy:
    value: null
    status: unknown
```

대구·경북 지역 수행실적이 다수 존재하지만 이를 회사의 공식 지역 선호전략으로 확정할 근거는 없음.

---

# 5. Business Constraint

## 5.1 참여 제약

```yaml
participation_constraints:
    minimum_project_size: null
    maximum_solo_project_size: null
    consortium_required_condition: null
    preferred_project_duration: null
    maximum_concurrent_projects: null
    maximum_onsite_staff: null
    profitability_threshold: null
    status: unknown
```

## 5.2 자격·조달 관련 정보

### 확인됨
- 벤처기업
- 전문연구사업자
- 기업부설연구소
- Inno-Biz
- Main-Biz
- ISO 9001 / 14001 / 20000-1 / 45001
- K-PaaS
- CSAP
- 클라우드서비스 확인(KACI)
- 기술평가등급 T3

### 추가 확인 필요

```yaml
qualification_unknowns:
    direct_production_certificate: null
    software_business_registration: null
    gs_certification_by_product: null
    procurement_registration: null
    digital_service_marketplace_registration: null
    security_certifications_other_than_listed: null
    required_industry_licenses: null
```

## 5.3 수행 제약

```yaml
delivery_constraints:
    nationwide_large_scale_onsite_operation: null
    large_scale_hw_supply: null
    large_scale_network_construction: null
    available_staff_by_technology: null
    status: unknown
```

## 5.4 기피 조건

```yaml
avoid_conditions:
    value: []
    status: unknown
```

자료만으로 공식 기피 조건을 확인할 수 없음.

---

# 6. Unknown / To Be Confirmed

공통 프로필의 활용도를 높이기 위해 우선 확인이 필요한 정보:

1. 확정 관심 분야 및 관심 키워드
2. 확정 비관심 분야 및 제외 키워드
3. 사업유형별 선호 우선순위
4. 최소·선호·최대 사업예산
5. 단독수행과 컨소시엄 참여 기준
6. 전략 고객 및 고객별 중요도
7. 선호 기관 여부
8. 지역 우선순위
9. 최대 동시 수행 사업 수
10. 최대 상주 가능 인력
11. 목표 수익성 또는 최소 마진 기준
12. AI / 데이터 / 온톨로지 / 블록체인 분야별 실제 투입 가능 인력
13. PM/PL 보유인력 및 공공사업 경력
14. 기술등급·자격증별 인력 현황
15. 직접생산확인증명 및 조달 관련 자격
16. GS인증 및 제품별 공공조달 등록현황
17. 2022년 이전 수행실적의 법적·계약상 인정 범위
18. 솔루션별 표준 기능, 가격정책, 라이선스·구독 정책
19. 대형 HW·네트워크 포함 사업 수행 가능 범위
20. 공식 기피 사업·조건

---

# 7. Profile Metadata

```yaml
profile:
    name: "회사 프로필"
    purpose:
        - "AI 에이전트 공통 컨텍스트"
        - "사업기회 분석"
        - "기술·실적 매칭"
        - "제안서 및 회사소개 자료 생성"
        - "영업·전략 분석"
```
