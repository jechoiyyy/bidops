# HP-02 준비 — 초안, 등록·활성화 전

> 승인 전 제안과 준비 경과 기록이다. 현재 실행 계약·결정 상태는 [intent](intent.md)·[spec](spec.md)·[plan](plan.md)을 따른다.

실제 카드 근거와 분류·alias·concept ID 후보는 [vocabulary-candidates.md](vocabulary-candidates.md), 기계 판독 후보는 [ontology.candidates.draft.json](../../preparation/ontology.candidates.draft.json), 가상회사 설정은 [company.proposal.draft.json](../../preparation/company.proposal.draft.json). 실제 온톨로지 검증기와 NFKC 어휘 매퍼를 오프라인으로 통과했지만 사용자 승인·업무 적합 검증을 뜻하지 않는다. 관련어 묶음의 분리 여부를 먼저 결정한다. 파일 이름부터 초안이며 회사 파일은 등록 CLI 형식이 아니다.

회사 추천안은 가상 온웹서비스(hp-onweb), 18명·연매출18억원·2018년 설립·최근3년 홈페이지3건·최대2억원 실적이다. 전부 사용자 검토용 가상 수치다. 의도적 차이는 ISMS 미보유, 다국어 실적 없음, 상주 가용2명 제한이며 Oracle 경험과 직접생산확인 유효범위는 unknown/null이다. 마지막 둘을 미보유로 판정하지 않는다. 24시간 대응도 unknown이며 업무시간 대응만 가정했다. 등록 시 승인된 각 사실을 fictional_scenario source_refs와 별도 불변 버전에 연결해야 한다.

대안은 규모를 줄여 상주·실적 격차를 더 드러내거나, 규모를 키우되 자격·기술 격차만 남기는 것이다. 추천은 중간 규모 유지: 항상 전부 met 또는 gap인 데모를 피할 수 있다. 실제 공고 숫자에 맞춰 회사 사실을 사후 조정하지 않는다.

재생성 명령과 외부 파일 위치는 [준비 묶음](../../preparation/README.md). `coverage`는 후보가 나타난 카드 비율일 뿐 정확도·충족률이 아니다. 자격·계약은 카드 밖에 있을 수 있으므로 현재 사전의 카드 출현 0을 불필요로 자동 삭제하지 않는다. D1·D2 승인 후 source_refs가 있는 정식 fixture·스펙 작성, 현재 validator 재검증, 고정 hash, 격리 등록·활성화 순서로 진행한다. 이번에는 DB/MinIO/정책에 쓰지 않았다.

## 공동 검토 결정 — 2026-10-15

사용자가 “승인할게”로 승인한 범위: **회사에서 보유 여부를 따로 답할 수 있는 항목은 별도 concept로 나누고, 표기만 다른 말은 alias로 묶는다. 인원·금액·시간은 별도 조건 값으로 둔다.** 웹접근성 개선/인증 지원, 웹표준/호환성, UX/UI/퍼블리싱, 취약점 점검/안전한 코드 개발, 정기점검/상시 감시, 백업/복구의 여섯 묶음 분리를 승인했다.

이를 반영한 현재 검토 파일은 [ontology.candidates.draft.v2.json](../../preparation/ontology.candidates.draft.v2.json)이다. 이전 파일과 coverage는 과거 입력 증거로 보존한다. D2의 분류 원칙·여섯 묶음 분리는 확정했지만 전체 concept ID/alias·kind/관계 확장·매핑 목표와 D1 회사 수치는 아직 미확정이다. 따라서 기능은 drafting이며 등록·활성화하지 않는다.

v2의 alias는 출현 후보 연결용이다. “인증”이라는 단어의 출현으로 회사의 인증 보유/지원 실적을 확인하지 않는다. UI/UX만 등장해도 수행 경험이 증명되지는 않는다. 광범위한 '디자인'·'개발보안'은 분리한 특정 능력으로 자동 귀속시키지 않았다. 나머지 Java/JSP, SSL/TLS, CMS/콘텐츠 운영 등 관련어 묶음도 이 원칙으로 추가 검토해야 하며 그대로 승인된 것으로 취급하지 않는다.

오프라인 확인: 기존 ontology 검증기·제품 매퍼 통과, 동일198카드 입력에서 후보35개·매핑129/198·미매핑69건. 이전129/198과의 차이는 alias 분리 결과이며 정확도/충족률 점수로 해석하지 않는다. 전체 결과는 Git 밖 `hp-preparation-20261015/coverage.v3.json`에 보존.

## 가상회사 기본 설정 승인 — 2026-10-15

사용자가 직전 회사 설정 표에 “진행해”라고 답하여 가상 온웹서비스의 18명·연매출18억원·최근3년 홈페이지3건·최대단일2억원, CMS 구축/접근성 개선/업무시간 장애 대응 경험, ISMS 미보유·다국어 수행실적 없음·상주최대2명, Oracle/직접생산확인 유효범위/24시간 대응 미확인을 승인했다. 정본은 [company.scenario.approved.v1.json](../../preparation/company.scenario.approved.v1.json), SHA256 `c4d2c3cf5c004d14fc14d6b9a8e931044b500806941b982b0e78689ac9bc145b`. 이전 proposal은 당시 초안으로 보존한다.

D1 기본 시나리오는 확정됐다. 다국어 **실적 없음**은 능력 없음으로 바꾸지 않고 별도 experience 사실로 저장한다. unknown 세 항목은 value=null, 확인된 ISMS 미보유는 false로 분리했다. 승인 표에 없던 초안의 2018년 설립은 확정값에 넣지 않았다. 개별 실적의 역할/일자/금액과 기준일·인력 직군은 아직 미지정이며 임의로 생성하지 않는다.

준비 JSON은 14사실의 ID 고유성·unknown/null·자체 statement source_refs·경험/역량 구분을 검사했다. **등록 CLI의 company-knowledge-source 스키마 통과를 의미하지 않는다.** 현재 등록 계약은 qualification/technology가 문자열이고 capability가 scope+description이며, 금액·인원·boolean 사실을 임의 속성으로 넣을 수 없다(`app/core/company_ontology.py::_node_value`). 승인한 사실을 잃지 않도록 등록용 projection과 HP03 typed fact 대조 계약을 스펙에서 연결해야 한다. 미보유 자격을 holds_qualification의 양성 근거로 잘못 연결하지 않는다. 현재 DB/정책 변경 없음.


## 관련어 분리 후속 초안 — 2026-10-15

승인된 분류 원칙을 나머지 묶음에 적용한 [v3 후보](../../preparation/ontology.candidates.draft.v3.json)는51concept다. Java/JSP·SSL/TLS·CMS 구축/콘텐츠 운영/기술·ISMS/ISMS-P 등을 분리했다. 전체 ID·alias는 미확정이고 등록하지 않았다.

기존 validator와 실제198카드 매퍼 실행 성공: 출현118/198(59.6%)·미매핑80(`coverage.v4.json`). 넓은 alias를 줄여129건보다11건 감소했으며 정확도 변화로 해석하지 않는다. Java/JSP·SSL/TLS는 별도 concept로 매핑됐지만 ISMS-P는 현행 매퍼가 ISMS도 함께 반환한다. HP03에서 중첩 용어·자격 범위 대조를 검증해야 하며 사전만으로 의미 분리가 완료된 것은 아니다. 제품 매퍼 수정 없음.

## 등록 표현 최종 검토안 — 2026-10-15

[등록 초안](../../preparation/company.registration.draft.v1.json)과 [14사실 대응표](../../preparation/company.registration.review.v1.json)를 만들었다. 기존 company-knowledge-source 검증기 통과,10노드·5관계다. 승인 시나리오 hash는 그대로이며 회사 사실을 추가하거나 개별3개 프로젝트를 지어내지 않았다. DB/정책 등록은 하지 않았다.

추천 결정은 다음 세 가지다.

1. [51개 concept·ID·alias](vocabulary-candidates.md)를 초기 사전으로 동결한다. 기존4kind·11관계를 유지한다. 중첩 어휘는 후보 검색일 뿐이며 대상/숫자/자격 대조로 충족을 판단한다.
2. 승인된 CMS 구축·웹접근성 개선·업무시간 장애 대응을 등록 형식의 core 역량으로 표시한다. 이는 새 자격이나 모든 사업 수행 가능을 뜻하지 않는다. non_core로 두는 대안은 핵심역량 표시에 영향을 준다.
3. 설립연도, 회계연도, 실적 기준일·개별 역할/금액/기간, 직군·가용 기준일, 구체 업무시간은 미지정으로 둔다. 지금 가상의 상세 값을 추가하는 대안도 있으나 근거가 없는 조건은 unknown으로 남기는 안을 추천한다.

ISMS 미보유는 명시 문장으로 보존하고 holds_qualification 양성 관계를 생성하지 않았다. 다국어 실적 부재는 회사 요약과 승인 typed scenario에 유지하며 역량 부재로 바꾸지 않았다. Oracle·직접생산확인 범위·24시간 대응 노드는 unknown/null/빈 source_refs다. 인원18명과 상주최대2명은 각각 전체 인력과 상주 가용 인력 노드로 분리했고 날짜/직군을 임의로 특정하지 않았다.

기존 등록 계약에는 매출·집계 실적을 위한 typed 필드가 없다. 회사 요약에 문장을 보존하되 승인된14사실 JSON을 함께 고정해야 하며, 등록 그래프만으로 숫자·기간 대조가 완료됐다고 하지 않는다. 이 연결의 제품 구현·검증은 HP03 명세에 포함할 대상이다. 등록 초안의 core 분류와 전체 사전은 아직 사용자 최종 선택 전이다.

검증: 실제 parser 통과,14사실 대응 고유성, 미확인3값 보존, 양성 ISMS 관계 없음, 실제541카드 coverage 재생성 성공. 코드 변경이 없어 앱/23개 준비 도구 검사를 반복하지 않았다.

## 기준 동결 승인 — 2026-10-15

사용자 “확정할게”로 직전 세 가지 추천안을 확정했다. [온톨로지 v1](../../preparation/ontology.approved.v1.json)은51concept·4kind·11관계·ID/alias를 그대로 동결했다. [회사 등록 표현 v1](../../preparation/company.registration.approved.v1.json)은 CMS 구축·접근성 개선·업무시간 장애 대응 core3개를 확정하고, 미지정 상세를 계속 미확인으로 둔다. 초안과 비교해 버전 식별자와 온톨로지 결속 hash만 변경했으며 개념/관계·회사 노드/edge는 동일하다. 두 파일 모두 기존 parser 통과.

[회사 평가 기준](../../preparation/company.evaluation-basis.v1.json)은 승인 typed scenario의 파일 SHA와 등록 표현의 파일 SHA, ontology canonical SHA를 묶는다. **작성자료/예측의 company_sha256은 이 basis 파일 바이트의 SHA256**이며 등록 JSON의 단독 SHA와 혼동하지 않는다. ontology_sha256은 제품 parser의 canonical SHA다. [동결 기록](../../preparation/human-gold-inputs.frozen.v1.json)이 표본·회사·온톨로지·빈 작성자료를 연결한다.

이번 완료는 기준 동결·작성자료 발행이다. 회사 DB 등록·정책 활성화·HP02 제품 완료가 아니며 기능 상태 drafting을 유지한다. 수치 대조 제품 연결과 ISMS-P 중첩 처리의 한계는 그대로다.

## 실적 기반 회사 v2 재계획 — 2026-10-15

사용자 “그렇게 진행해보자”에 따라 요약 사실만으로 모든 카드를 대조하던 방식에서 **수행 범위 → 보유 역량 → 현재 수행 조건**을 분리하는 방향을 채택했다. 구체 수행 가정은 [v2 초안](../../preparation/company.experience.draft.v2.json)이며 사용자 확정 전이다. v1의14개 사실·회사명·인원·매출·집계 실적·미보유·unknown은 그대로 보존했다. 온톨로지51개도 유지한다.

| 가상 실적 | 담당 완료로 제안한 범위 | 자동 포함하지 않는 것 |
|---|---|---|
| 평생교육 포털 구축 | 반응형 페이지, 강좌 검색·수강신청, 결제 연계·강좌관리, 관리자 화면 | 서버 공급·결제 보안 인증·다국어 |
| 기관 홈페이지 기능·접근성 개선 | 메뉴/업무 기능·DB 개발, 웹표준·호환성·접근성 개선, 웹 취약점 수정 | 접근성 인증 취득·ISMS·특정 SLA |
| 통합 홈페이지 콘텐츠·CMS 유지관리 | 문의 대응, 콘텐츠 현행화, CMS 버그/템플릿 수정, 형상관리·보안약점 점검 | 24시간 운영·원문 전체 사이트 규모·인증 지원 |

참고 자료는 평가10건 밖의 notice3·46·158이다.7종 기능을 새로 보유한 실제 증거가 아니라 요구 유형 참고자료이며, 원문의2026/2027 발주를 과거 완료 실적으로 바꾸지 않는다. 위 이름은 별도의 가상 사업이고 **명시한 부분만 수행 완료했다는 시나리오 가정**이다. 실제 기관의 계약/검수서가 존재한다고 주장하지 않는다. 개별 날짜·금액·재직자·직군은 미지정으로 유지하여 기존 최근3년·3건·최대2억원 집계 사실과 임의 연결하지 않는다. 기존 CMS 구축 경험도 그대로 보존하며 참고 공고의 모든 기술을 수행한 것으로 확대하지 않는다.

표준 수행 절차는 요구사항/변경 관리·계획/정기보고/완료 산출물·버전관리·매뉴얼/교육/인수인계를 제안한다. 손해배상·IP 귀속·추가 비용·무상 기간·제출 기한·상주 환경은 별도 계약 조건이며 통상 의무라는 이유로 자동 수용하지 않는다.

| 영향 | 반영 및 남은 검증 |
|---|---|
| HP02 | v2 담당 범위 승인 뒤 단일 원본→등록 그래프/프로필 파생, 수행→역량 연결 및 미담당 제외 검증 |
| HP03 | 기능 유사성·현재 자격/인력/SLA·계약 조건 대조 분리, 원자 조건별 met/gap/unknown 집계. 원문 전체 수행·부분 met 확대 금지 검사 |
| HP04/05 | 새 회사/그래프 hash로 조회·실험 입력 재생성 필요. 기존 미구현·미실험 상태 유지 |
| HP06 | v2 동결 뒤 새 company hash로 작성자료 발행. v1 사람 응답·모델 초안 이관/자동 채점 금지. 폴리텍의 모델 선노출 표식 유지 |

새 기준은 평가 원문과 hash/사업이 분리됐으나 폴리텍 모델 초안을 이미 본 뒤 구성한 개발 시나리오다. 완전히 독립적인 회사/평가 설계라고 주장하지 않는다. 독립 인수에는 모델 답을 보지 않은 평가자 또는 별도 평가 표본 검토가 필요하다. 품질 임계값과 gold-check의 선작성 게이트는 유지한다.

검증:3원문 취득·ClamAV clean·네트워크 없는 기존 변환기 성공, 평가11원문과 SHA 중복0, 인용 block 일치·기존14사실 동일·concept ID 유효 확인. Git 밖 `hp-company-v2-20261015/validation.v1.json`. 새 형식은 준비 초안이며 제품 등록 parser 통과·실제 회사 역량 검증을 뜻하지 않는다. HP02/03/06은 drafting이고 spec/plan·STEP·완료 proof가 없어 invalidate/sync-plan 대상이 없다. 의존·구현 큐·활성 run 범위는 변경하지 않는다.

## 회사 v2 수행 범위 확정 — 2026-10-15

사용자 “확정해”로 가상3실적의 명시 담당 범위와 표준 수행 절차를 승인했다. [회사 v2](../../preparation/company.experience.approved.v2.json), [평가 기준 v2](../../preparation/company.evaluation-basis.v2.json), [입력 동결 v2](../../preparation/review-inputs.frozen.v2.json)를 발행했다. 기존14사실의 값/단위/상태와 현재 조건은 동일하다. self 참조는 새 retained_facts 경로로 맞추고, 기존 ‘사업명 미지정’ 설명만 새 가상명·담당 범위 연결로 정리했다. 개별 날짜·금액·실제 완료 증거는 null이다.

v2 company_sha256은 company.evaluation-basis.v2.json 파일 SHA다. 이 기준은 승인된 실적 원본과 기존 ontology를 결속하며, v2 등록 projection은 pending이므로 registration_file=null이다. v1 등록 JSON을 v2 제품 데이터로 표시하지 않는다. DB 등록·제품 대조 연결은 별도 미구현이다.

Git 밖 `hp-evaluation-20261015/index.company-v2.html`과 `assisted-review.worksheet.blank.v2.json`은 v2 기준의 공동 검토 자료다. 원문10사례·11파일·541카드와 정답 빈칸은 그대로이며 company hash만 새 기준으로 연결했다. 폴리텍 초안 노출로 written_before_model_output=false를 명시해 독립 gold와 구분한다. v1 사람 응답·모델 초안은 자동 이관하지 않았다. 기존 gold-check 게이트·인수 기준은 유지한다.

검증: 승인 범위·미확인 값 보존,14사실 값 동일, self 참조와 인용 일치,10사례 원문/카드 동일 확인. 자료·문서 변경뿐이므로 변환/앱 테스트를 반복하지 않았다.
