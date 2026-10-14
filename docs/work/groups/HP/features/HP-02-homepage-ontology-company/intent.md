# 홈페이지 온톨로지·가상회사 1곳 — intent (초안, interview 전)

- 기능 ID: `HP-02-homepage-ontology-company`
- 상위 항목: [HP 로드맵](../../../../constitution/roadmap.md), [HP 공통 계약](../../../../hp-contract.md) §1·4·5
- 크기: L — 사용자 공동 설계, 새 fixture 2종, 매핑 검토 도구, 격리 스택 등록. 외부 호출 없음.
- 작성일: 2026-10-14 (초안; 결정 대기 D1·D2를 interview에서 닫은 뒤 spec으로 간다)

## 문제

기존 온톨로지(`bidops.company-ontology.v1`, 25 concept)와 3사 fixture는 공공 SI·데이터/AI·클라우드 어휘라서 홈페이지 공고의 요구(웹접근성·CMS·웹호스팅·상주 운영·취약점 점검·콘텐츠 운영 등)와 맞지 않는다.
회사가 없으면 HP-03의 대조와 HP-04의 판정이 비고, 어휘가 공고 쪽과 다르면 결정적 매핑이 실패한다.

## 기대 결과

사용자와 함께 확정한 홈페이지 온톨로지와 가상회사 1곳의 원본 파일이 저장소에 있고(동결 sha256 기록), 기존 CLI로 `bidops-local`에 등록·활성화되며, 카드 198장 중 어느 카드가 어느 concept에 매핑되는지(그리고 어느 카드가 미매핑인지) 보고서로 확인할 수 있다.

## 유즈케이스

| 유즈케이스 | 실행 방법(명령·화면·API) | 확인 기준 |
|---|---|---|
| 어휘 검토 | [vocabulary-candidates.md](./vocabulary-candidates.md)를 보고 결정 표(채택/병합/제외, kind, id, alias)를 만든다 | 결정 표가 이 폴더에 있고 모든 후보 행에 결정이 있다 |
| 온톨로지 검증 | 기존 ontology 검증기(DEMO §3 규칙)로 `docs/hp-fixtures/ontology.homepage-v1.json` | 중복 id/alias 없음, relation 집합 허용 범위, canonical sha256 기록 |
| 매핑 검토 | `scripts/hp-card-concept-coverage.py <카드 JSON> <온톨로지>` | 카드별 concept 후보와 미매핑 카드 목록; 매핑률 목표(결정 대기)를 만족하거나 사유 기록 |
| 회사 등록 | `python -m app.deep_review.cli import-company-knowledge` → `activate-company-knowledge`(DEMO §4) | 등록 성공, 프로필 projection에 confirmed/inferred/unknown 사실이 보이고 unknown value=null |
| 격차 확인 | 회사 프로필 화면(`/companies/{id}`) | 의도적 격차 3건 이상이 미보유 또는 unknown으로 구분되어 보인다 |
| 동결 | 승인 뒤 파일 sha256을 HP 공통 계약 §1·4·5와 validation-runs README에 기록 | 이후 변경은 새 버전 파일 |

## 선행·후속 기능

- 선행: HP-01-requirement-cards(카드 JSON이 매핑 검토 입력).
- 후속: HP-03-two-tier-analysis, HP-05-neo4j-experiment.

## 영향 범위

- 모듈·컴포넌트: `docs/hp-fixtures/`(신규), `scripts/hp-card-concept-coverage.py`(신규), 기존 ontology/company CLI·검증기(변경 없음이 목표; kind·관계 확장을 결정하면 검증기·DB 제약 변경이 생긴다).
- 큰 틀 문서의 절: HP 공통 계약 §1·4·5·11(D1·D2), DEMO 계약 §3·4(재사용).
- 데이터·저장소: `KnowledgeOntologyVersion`·`CompanyKnowledgeVersion` 새 row. kind·관계 확장 시 migration 가능성.
- 외부 서비스·호출: 없음.

## 제약

- (공통) feature.json constraints 전체를 따른다(HP-00 intent와 같은 목록).
- (기능별) 회사의 모든 사실은 `fictional_scenario`이며 실제 회사 자료를 섞지 않는다. 추정으로 사실을 만들지 않고 모르는 값은 unknown으로 둔다.
- (기능별) 온톨로지 스키마 버전을 바꾸지 않는 한 기존 3사 fixture·row는 그대로 둔다.

## 범위 밖

그래프 편집 UI, 문서에서 온톨로지 자동 추출 후 승인 UI, 실제 회사 자료 연계.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 온톨로지 작성 방식 | DEMO: 내가 초안 → 사용자 승인 | 2026-10-14 사용자: 함께 만든다 | 어휘 후보 → 결정 표 → 파일 순으로 공동 작업 |

## 미해결 질문 (interview 항목)

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| D1 회사명·slug·규모(인원·연매출 가정)·연혁·의도적 격차 3건 이상 | spec 작성 전 | 어휘 결정 뒤 초안 제시 → 사용자 선택 |
| D2 kind 확장(서비스 수준·인력 조건을 capability와 구분할지), 관계 확장, id 접두 규칙 | spec 작성 전 | 제안: kind 유지, 접두 `cap./tech./qual./dom.` |
| 매핑률 목표(카드 198장 중 concept 후보가 하나 이상인 비율) | spec 작성 전 | 제안: 80% 이상, 미매핑은 목록으로 보존 |
| fixture 디렉터리·파일명 | spec 작성 전 | 제안: `docs/hp-fixtures/ontology.homepage-v1.json`, `docs/hp-fixtures/companies/<slug>.v1.json` |
| 어휘 후보의 분류 단위(일곱 묶음 유지 여부) | 어휘 검토 중 | 사용자와 결정 |
