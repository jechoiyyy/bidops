# 승인된 용어 사전 v1과 출현 근거

사용자 “확정할게”로 승인한 [v1 사전](../../preparation/ontology.approved.v1.json)은51concept·4kind·기존11관계다. 아래 출현 수는 내용이 같은 v3 후보로 계산한 결과를 재사용했다. 승인된 ‘따로 보유 여부를 판단하는 개념은 분리’ 원칙을 적용했다. 이전28/35개 후보와 출현 결과는 원본 JSON·coverage로 보존한다.

확정 표본10사례의541카드에서 기존 매퍼로 출현을 다시 계산했다. **297/541(54.9%)**이며 정확도·요구 충족률·업무 완전성 점수가 아니다. 카드 밖 원문은 작성자료에 포함하지만 아래 출현 수의 분모에는 포함하지 않았다. 출현0인 자격 개념도 삭제하지 않았다.

| concept ID | kind | 표시명 / alias | 출현 카드 수 | 첫 근거 위치 |
|---|---|---|---:|---|
| `cap.web-accessibility` | capability | 웹접근성 / 웹 접근성 | 34 | doc1 · MPR-3 · table-1-12-r4-c1 |
| `cap.accessibility-certification-support` | capability | 웹접근성 인증 지원 / 웹접근성 인증 취득 지원 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `qual.web-accessibility` | qualification | 웹접근성 품질인증 / 웹 접근성 품질인증, 접근성 품질인증 | 7 | notice129-attachment187 · MPR-10 · table-1-44-r4-c1 |
| `cap.web-standards` | capability | 웹표준 / 웹 표준 | 21 | doc1 · COR-4 · table-1-30-r2-c1 |
| `cap.browser-compatibility` | capability | 웹호환성 / 웹 호환성, 크로스브라우징 | 18 | doc1 · COR-4 · table-1-30-r2-c1 |
| `cap.cms` | capability | CMS 구축 / 콘텐츠관리시스템 구축, 콘텐츠 관리 시스템 구축 | 1 | gangwon · SFR-1 · table-1-24-r4-c1 |
| `cap.content-operations` | capability | 콘텐츠 운영 / 콘텐츠 관리, 콘텐츠관리 | 11 | gangwon · SFR-1 · table-1-24-r2-c1 |
| `tech.cms` | technology | CMS / 콘텐츠관리시스템, 콘텐츠 관리 시스템 | 8 | doc1 · SFR-2 · table-1-19-r4-c1 |
| `cap.search` | capability | 통합검색 / 통합 검색 | 6 | gangwon · SFR-1 · table-1-24-r4-c1 |
| `tech.search-engine` | technology | 검색엔진 / 검색 엔진 | 6 | doc1 · MPR-3 · table-1-12-r4-c1 |
| `cap.ux-design` | capability | UX 설계 / 사용자 경험 설계 | 1 | mofa · COR-2 · table-1-42-r3-c1 |
| `cap.ui-design` | capability | UI 디자인 / 사용자 인터페이스 디자인 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `cap.web-publishing` | capability | 웹 퍼블리싱 / 퍼블리싱 | 3 | nyj · PMR-1 · table-1-39-r4-c1 |
| `cap.responsive` | capability | 반응형 웹 / 반응형 웹사이트 | 10 | doc1 · SFR-1 · table-1-18-r4-c1 |
| `cap.migration` | capability | 데이터이관 / 데이터 이관, 데이터 마이그레이션 | 7 | doc1 · MPR-3 · table-1-12-r4-c1 |
| `cap.integration` | capability | 시스템연계 / 시스템 연계 | 3 | gangwon · SFR-1 · table-1-24-r4-c1 |
| `tech.sso` | technology | SSO / 통합인증 | 2 | gangwon · SFR-1 · table-1-24-r4-c1 |
| `tech.api` | technology | API / 없음 | 8 | gangwon · SFR-1 · table-1-24-r4-c1 |
| `cap.vulnerability` | capability | 취약점점검 / 취약점 점검 | 20 | doc1 · MPR-3 · table-1-12-r4-c1 |
| `cap.secure-coding` | capability | 시큐어코딩 / 시큐어 코딩 | 10 | doc1 · SER-4 · table-1-24-r4-c1 |
| `cap.privacy` | capability | 개인정보보호 / 개인정보 보호 | 33 | doc1 · STR-1 · table-1-9-r4-c1 |
| `cap.periodic-inspection` | capability | 정기점검 / 정기 점검 | 18 | doc1 · MPR-2 · table-1-11-r5-c1 |
| `cap.monitoring` | capability | 모니터링 / 없음 | 24 | doc1 · MPR-3 · table-1-12-r4-c1 |
| `cap.incident` | capability | 장애대응 / 장애 대응, 장애처리, 장애 처리 | 21 | doc1 · MPR-3 · table-1-12-r4-c1 |
| `cap.backup` | capability | 백업 / 없음 | 20 | doc1 · MPR-3 · table-1-12-r4-c1 |
| `cap.recovery` | capability | 데이터 복구 / 백업 복구 | 1 | notice57-attachment88 · DAR-3 · table-1-39-r4-c1 |
| `cap.incident-recovery` | capability | 장애복구 / 장애 복구 | 9 | doc1 · MPR-5 · table-1-14-r4-c1 |
| `cap.sla` | capability | 서비스수준관리 / 서비스 수준 관리, SLA 관리 | 2 | doc1 · MPR-5 · table-1-14-r4-c1 |
| `cap.availability` | capability | 가용성 관리 / 가용성 보장 | 3 | doc1 · QUR-1 · table-1-25-r2-c1 |
| `cap.around-clock-response` | capability | 24시간 대응 / 24시간 장애 대응 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `cap.onsite` | capability | 상주 운영 / 상주 유지관리 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `cap.handover` | capability | 인수인계 / 인수 인계 | 9 | mofa · PSR-1 · table-1-36-r2-c2 |
| `cap.knowledge-transfer` | capability | 기술이전 / 기술 이전 | 10 | doc1 · PSR-2 · table-1-38-r2-c1 |
| `cap.training` | capability | 교육지원 / 교육 지원 | 6 | doc1 · MPR-3 · table-1-12-r4-c1 |
| `cap.manual-authoring` | capability | 매뉴얼 작성 / 매뉴얼 제작 | 3 | notice73-attachment107 · MPR-2 · table-1-17-r4-c1 |
| `cap.multilingual` | capability | 다국어 홈페이지 / 다국어 웹사이트 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `cap.hosting` | capability | 웹호스팅 / 웹 호스팅 | 9 | school · PMR-6 · table-1-43-r4-c1 |
| `tech.egov` | technology | 전자정부표준프레임워크 / 전자정부 표준프레임워크, 전자정부 표준 프레임워크 | 8 | doc1 · STR-1 · table-1-9-r2-c1 |
| `tech.java` | technology | Java / 없음 | 2 | notice73-attachment107 · QUR-3 · table-1-44-r4-c1 |
| `tech.jsp` | technology | JSP / 없음 | 2 | notice129-attachment187 · SER-7 · table-1-64-r4-c1 |
| `tech.db` | technology | 데이터베이스 / DB | 85 | doc1 · MPR-1 · table-1-10-r4-c1 |
| `tech.dbms` | technology | DBMS / 데이터베이스 관리 시스템 | 10 | gangwon · COR-2 · table-1-64-r4-c1 |
| `tech.oracle` | technology | Oracle / 없음 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `tech.ssl` | technology | SSL / 없음 | 8 | doc1 · MPR-3 · table-1-12-r4-c1 |
| `tech.tls` | technology | TLS / 없음 | 4 | gangwon · SER-9 · table-1-53-r4-c1 |
| `qual.gs` | qualification | GS인증 / GS 인증 | 1 | gangwon · SFR-1 · table-1-24-r4-c1 |
| `qual.isms` | qualification | ISMS / 없음 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `qual.isms-p` | qualification | ISMS-P / 없음 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `qual.direct-production` | qualification | 직접생산확인 / 직접생산확인증명서, 직접생산 확인 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `qual.sme` | qualification | 중소기업확인 / 중소기업확인서 | 0 | 카드 출현 없음; 카드 밖 확인 대상 |
| `dom.website` | domain | 홈페이지 / 웹사이트, 누리집 | 153 | doc1 · STR-1 · table-1-9-r4-c1 |

최종 결정은 이51개 concept·ID·alias를 초기 사전으로 동결하고, 의미 비교는 별도 조건과 근거로 수행하는 것이다. ISMS/ISMS-P, Java/JSP, SSL/TLS, CMS 구축/콘텐츠 운영, 백업/장애복구는 동의어로 합치지 않는다. 대안은 좁은 표기만 먼저 동결하는 것이며 후보 누락과 unknown 비중이 늘 수 있다.

다음 한계는 사전 동결로 해소되지 않는다.

- 현행 매퍼는 ISMS-P에서 ISMS도 후보로 반환한다. HP03에서 중첩·자격 범위 대조를 검증하기 전에는 이를 충족 판정으로 사용하지 않는다.
- 웹접근성 품질인증·GS인증은 대상 사이트/제품의 인증일 수 있다. 회사 보유 자격으로 자동 귀속하지 않는다.
- ‘통합인증’과 SSO, ‘가용성 보장’과 관리 활동은 원문 맥락에서 다를 수 있다. 어휘 후보 출현은 수행 능력이나 계약 조건 일치를 뜻하지 않는다.
- 누락된 회사 사실은 unknown이다. 미보유·실적 없음·능력 없음은 서로 바꾸지 않는다.

외부 증거는 `hp-evaluation-20261015/coverage.selected10.v1.json`이며 원문 hash와 block 인용을 보존했다. 회사 사실에 맞춰 공고 정답이나 추천 판정을 생성하지 않았다.
