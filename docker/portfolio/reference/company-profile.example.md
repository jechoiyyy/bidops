# 회사 프로필 (예시)

> 합성 회사의 가상 프로필이다. 실제 회사 자료가 아니다. 형식만 보여 주며 테스트가 이 파일을 읽는다.
> 포트폴리오 스택은 이 자리의 로컬 `company-profile.md`를 읽는다(`docker/docker-compose.portfolio.yml`). 파일은 Git에 두지 않는다.
> 정보 상태: `confirmed` = 근거 문서에서 확인, `inferred` = 근거에서 도출, `unknown` = 확인 불가

---

# 1. Company Identity

```yaml
company:
    name: "합성 회사"
    employees:
        value: 12
        as_of: "2026-01"
        status: confirmed
    revenue_2025:
        value: null
        status: unknown
```

---

# 2. Company Capability

## 2.1 보유 기술

```yaml
capability:
    status: confirmed
    technologies:
        - "웹 포털 구축"
        - "데이터 연계"
```

대표 근거:
- 가상 포털 구축 사례 A

## 2.2 수행 가능 역할

```yaml
roles:
    status: inferred
    items:
        - "구축 주관"
```

## 2.3 사업영역

```yaml
domains:
    status: confirmed
    items:
        - "공공 정보시스템"
```

## 2.4 대표 수행실적

```yaml
projects:
    status: confirmed
    items:
        - "가상 포털 구축 사례 A"
```

# 4. Business Preference

## 4.1 관심 분야

```yaml
interests:
    status: inferred
    items:
        - "정보시스템 유지관리"
```

# 5. Business Constraint

## 5.2 자격·조달 관련 정보

```yaml
qualifications:
    software_business_registration:
        value: null
        status: unknown
```
