# 실제 카드 기반 어휘·concept 후보 (승인 전)

2026-10-15 HP01 제품 추출기로 5문서 198카드를 다시 읽었다. 직접 매핑0·상속88·쪽미확인110이다. 과거 scratchpad의 198/198 및 카드별 p 표시는 폐기하며 이 파일의 원문 위치와 HP01 증거를 따른다.

후보 28개는 전체 어휘를 확정한 사전이 아니다. alias 배열에는 동의어뿐 아니라 검토할 관련어 묶음도 들어 있다. 특히 Java/JSP, SSL/TLS, 디자인/UI/UX, 취약점점검/시큐어코딩, 백업/복구, 웹표준/웹호환성은 동일 능력으로 확정하지 말고 분리 여부를 결정해야 한다. 아래 수치는 어휘 출현이며 요구 충족률이 아니다.

현재 넓은 후보 묶음의 출현 카드 129/198 (65.2%); 목표·채택 기준 미확정. 비일치 카드도 외부 coverage 파일에 전부 보존했다.

| concept ID 후보 | kind | label / alias 후보 | 카드 수 | 첫 원문 근거(문서·카드·block) |
|---|---|---|---:|---|
| `cap.web-accessibility` | capability | 웹접근성 / 웹 접근성, 접근성 품질인증 | 19 | doc1 · MPR-3 · `table-1-12-r4-c1` |
| `cap.web-standards` | capability | 웹표준 / 웹 표준, 웹호환성, 크로스브라우징 | 10 | doc1 · COR-4 · `table-1-30-r2-c1` |
| `cap.cms` | capability | 콘텐츠관리 / 콘텐츠 관리, CMS, 콘텐츠관리시스템 | 9 | doc1 · SFR-2 · `table-1-19-r4-c1` |
| `cap.search` | capability | 통합검색 / 통합 검색, 검색엔진 | 5 | doc1 · MPR-3 · `table-1-12-r4-c1` |
| `cap.design` | capability | 디자인 / UI, UX, 퍼블리싱 | 27 | doc1 · MPR-3 · `table-1-12-r4-c1` |
| `cap.responsive` | capability | 반응형 / 반응형 웹 | 8 | doc1 · SFR-1 · `table-1-18-r4-c1` |
| `cap.migration` | capability | 데이터이관 / 데이터 이관, 마이그레이션 | 3 | doc1 · MPR-3 · `table-1-12-r4-c1` |
| `cap.integration` | capability | 시스템연계 / 시스템 연계, SSO, API | 6 | gangwon · SFR-1 · `table-1-24-r4-c1` |
| `cap.vulnerability` | capability | 취약점점검 / 취약점 점검, 시큐어코딩, 개발보안 | 15 | doc1 · MPR-3 · `table-1-12-r4-c1` |
| `cap.privacy` | capability | 개인정보보호 / 개인정보 보호, 개인정보 | 27 | doc1 · STR-1 · `table-1-9-r4-c1` |
| `cap.monitoring` | capability | 정기점검 / 정기 점검, 모니터링 | 17 | doc1 · MPR-2 · `table-1-11-r5-c1` |
| `cap.incident` | capability | 장애대응 / 장애 대응, 장애관리, 장애처리, 장애복구 | 11 | doc1 · MPR-3 · `table-1-12-r4-c1` |
| `cap.backup` | capability | 백업 / 복구 | 12 | doc1 · MPR-3 · `table-1-12-r4-c1` |
| `cap.sla` | capability | 서비스수준 / 서비스 수준, SLA, 가용성 | 7 | doc1 · MPR-5 · `table-1-14-r4-c1` |
| `cap.onsite` | capability | 상주 / 상주인력, 상주 인력 | 12 | doc1 · SER-2 · `table-1-22-r4-c1` |
| `cap.handover` | capability | 인수인계 / 인수 인계, 기술이전 | 9 | doc1 · PSR-2 · `table-1-38-r3-c2` |
| `cap.training` | capability | 교육지원 / 교육 지원, 매뉴얼 | 20 | doc1 · STR-1 · `table-1-9-r4-c1` |
| `cap.multilingual` | capability | 다국어 / 외국어, 영문 | 5 | doc1 · MPR-2 · `table-1-11-r4-c1` |
| `cap.hosting` | capability | 웹호스팅 / 웹 호스팅, 호스팅 | 9 | school · PMR-6 · `table-1-43-r4-c1` |
| `tech.egov` | technology | 전자정부표준프레임워크 / 전자정부 표준프레임워크, 표준프레임워크 | 6 | doc1 · STR-1 · `table-1-9-r3-c2` |
| `tech.java` | technology | Java / JSP | 1 | nyj · MHR-2 · `table-1-56-r4-c1` |
| `tech.db` | technology | 데이터베이스 / DB, DBMS | 32 | doc1 · MPR-1 · `table-1-10-r4-c1` |
| `tech.tls` | technology | SSL / TLS | 6 | doc1 · MPR-3 · `table-1-12-r4-c1` |
| `qual.gs` | qualification | GS인증 / GS 인증 | 1 | gangwon · SFR-1 · `table-1-24-r4-c1` |
| `qual.isms` | qualification | ISMS / ISMS-P | 0 | 현재 카드 출현 없음; 카드 밖 자격 조건 확인 필요 |
| `qual.direct-production` | qualification | 직접생산확인 / 직접생산, 직접 생산 | 0 | 현재 카드 출현 없음; 카드 밖 자격 조건 확인 필요 |
| `qual.sme` | qualification | 중소기업 / 중소기업확인 | 0 | 현재 카드 출현 없음; 카드 밖 자격 조건 확인 필요 |
| `dom.public-web` | domain | 홈페이지 / 공공 웹사이트 | 69 | doc1 · STR-1 · `table-1-9-r4-c1` |

원문 전문과 정확한 인용은 Git 밖 `.../.sdlc/local-runtime/hp-preparation-20261015/coverage.v2.json`의 `evidence[].quote`에 있다. 각 인용은 실제 table_cell text 그대로이며 `source_sha256`·block_key·unit_id·page_range/mapping_status가 연결된다. `unavailable`이면 물리 쪽을 추정하지 않는다.

D2 추천: 기존 4 kind·relation 집합 유지, cap./tech./qual./dom. 접두 도입. 다만 기존 DEMO 접두(capability./technology./qualification./domain.)를 유지하는 대안은 혼용 비용을 줄인다. 표시용 7묶음은 kind와 분리한다. 광범위 단어를 묶어 매핑률을 높이는 것은 채택 근거가 아니다.

추천 검토: 관련어를 동의어에서 분리 → 자격·계약 카드 밖 근거 추가 → 후보별 채택/분리/제외 → 미매핑 카드 검토 → 동결. 개별 결정은 아직 모두 미확정이다.
