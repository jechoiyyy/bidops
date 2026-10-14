# 2층 분석 파이프라인 (카드 추출 → 결정적 대조 → 역할 판단·종합) — intent (초안, interview 전)

- 기능 ID: `HP-03-two-tier-analysis`
- 상위 항목: [HP 로드맵](../../../../constitution/roadmap.md), [HP 공통 계약](../../../../hp-contract.md) §6·7
- 크기: L — 새 정책·새 저장 테이블·새 stage 계약·worker 변경·실제 모델 호출.
- 작성일: 2026-10-14 (초안; 결정 대기 D4·D5와 아래 interview 항목을 닫은 뒤 spec으로 간다)

## 문제

현행 narrative-v2는 원문 조각마다 3단계를 돌려 100쪽 문서에 호출 50~80회·4~8시간이 들고, 결과가 서술 claim이라 카드 단위 충족/부족/미확인과 실무자 판정으로 바로 이어지지 않는다.
DEMO-05에서 Luna 96×3 실행이 1단계 결정적 검증에서 전부 실패한 것도 조각 단위 근거의 약함을 보여준다.

## 기대 결과

HP-01의 카드·segment를 unit으로 묶어 1층 타입화 추출을 호출하고, 코드가 온톨로지·회사 그래프와 결정적으로 대조한 뒤, 역할 셋과 종합 하나가 `bidops.practitioner-verdict.v1`을 만든다.
한 문서(100쪽·unit 70개 기준)가 40분 안에 끝나고 모든 quote·locator·ID가 결정적 검증을 지나며, 실패는 사람 검토로 간다. 대표 1건을 사용자 승인 뒤 `bidops-local`에서 실제로 돌린다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| unit 생성 | preview 생성(기존 회사 preview 경로 재사용) | unit 목록(card/segment), batch 수, 예상 호출 수·시간이 preview input에 고정 |
| 승인·실행 | 기존 건별 승인 → 공용 슬롯 worker | 단계 순서 extract→compare→roles→synthesis, 단계별 불변 row |
| 결정적 검증 | 각 모델 응답 | quote가 unit 원문 부분문자열, locator가 unit block, unit id·concept id가 입력 집합 안; 실패는 `needs_human_review`로 종결(자동 보정 없음) |
| 대조 | compare 단계 출력 | unit별 met/gap/unknown과 경로·사실 근거; unknown을 gap으로 바꾸지 않음 |
| 종합 조회 | `GET .../verdict`(경로명 D6) | 판정 enum, 체크리스트 5항목, 매트릭스, 주의, 다음 행동, conflicts |
| 시간·호출 상한 | 정책 값 | 상한 초과 시 `review_timeout`으로 종결, 부분 결과는 단계 row로 보존 |
| 대표 1건 실제 실행 | 사용자 건별 승인 | 40분 이내 완료 또는 실패 사유 기록(`real_data_run` 증거) |

## 선행·후속 기능

- 선행: HP-00-luna-model-identity, HP-02-homepage-ontology-company.
- 후속: HP-04-practitioner-verdict, HP-06-gold-acceptance.

## 영향 범위

- 모듈·컴포넌트: deep_review services(새 pipeline 모듈, worker 분기, 정책 loader), contracts(새 stage schema 3종), policies(`analysis-policy-hp-v1.json`), codex-runner(schema 파일 추가: 새 출력 계약을 strict schema로 실어야 한다), REST(preview 입력 확장·verdict 조회), migration(새 테이블)·runtime-privileges.
- 큰 틀 문서의 절: HP 공통 계약 §6·7·11, DEMO 계약 §9(재사용·확장), contracts.md, deep-review-erd.md, business-rules(판정은 보조 의견).
- 데이터·저장소: 새 테이블(추출·대조·역할·종합), attempt 연결.
- 외부 서비스·호출: codex-exec gpt-6-luna/high. 호출 수 = ceil(unit/batch)+4. 건별 승인.

## 제약

- (공통) feature.json constraints 전체를 따른다(HP-00 intent와 같은 목록).
- (기능별) 모델 출력은 판정이 아니라 보조 의견이며 추적 승인·Go/No-Go를 저장하지 않는다. 역할 간 충돌은 보존한다.
- (기능별) runner는 모델·schema를 요청에서 받지 않는다. 새 출력 계약은 runner 이미지에 파일로 싣는다.

## 범위 밖

화면(HP-04), gold 채점(HP-06), narrative-v2 경로 삭제(보존), 여러 문서 동시 실행(슬롯 1).

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 단계 구성 | narrative-v2 3단계 서술 | 2026-10-14 사용자: 항목별 sub-agent 분할·합치기 아이디어 | 공통 계약 §6·7의 2층 구조(사용자 확인 필요) |

## 미해결 질문 (interview 항목)

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| D4 batch_size·묶음 문자 상한·timeout·repair 횟수 | spec 작성 전 | 제안 8장/12,000자/3600초/1회 |
| D5 카드 아닌 segment를 unit으로 넣는 범위 | spec 작성 전 | 제안: 사업개요·일정·예산·참가자격·평가·계약 label segment |
| 역할 셋의 prompt 범위와 각 역할이 받는 type 집합 | spec 작성 전 | 제안: eligibility_economics=자격·실적·인력·계약·평가 / technical_fit=기술·기능·성능SLA·보안 / operations_risk=운영·성능SLA·보안·인력 |
| 응락수준 "선택"·"권장" 카드의 mandatory 처리 | spec 작성 전 | 제안: mandatory=false, 판정 가중 없음, 매트릭스에 표시 |
| 저장 테이블 설계(단계별 row vs 단일 JSON) | spec 작성 전 | 제안: 단계별 불변 row + attempt FK |
| 대표 1건 선택(fixture 5건 중 또는 로컬 수집 공고) | 구현 중 | 사용자 선택 |
