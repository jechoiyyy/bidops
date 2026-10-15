# 독립 사람 정답과 데모 인수 — intent

- 기능 ID: `HP-06-gold-acceptance`
- 상위: [로드맵](../../../../constitution/roadmap.md), [HP 공통 계약](../../../../hp-contract.md)
- 크기: L — 새 데이터 계약·검증 또는 제품 경계를 다룬다.
- 작성일: 2026-10-15. 현재는 구현 전 명세다.

## 문제와 기대 결과

독립 사람 정답과 데모 인수를 현재 제품에서 완료로 볼 증거가 없다. 아래 유즈케이스를 구현·검증하고 실제 실행과 문서 준비를 구분한다. 승인 원본은 `../../preparation/company.experience.approved.v2.json`과 `ontology.approved.v1.json`이다. 상세 범위는 spec이 정본이며 preparation은 의사결정 경과다.

## 유즈케이스

| 유즈케이스 | 실행 방법 | 확인 기준 |
|---|---|---|
| 사람 정답 작성 | 모델 답 없는 자료·gold-check | 10건·각10카드·동결 binding·작성자·노출 이력 검증 |
| 평가 채점 | hp_prepare.py score | 판정·차단 recall·카드 정확도·reference precision 재현 |
| 인수 판단 | 불일치 자료와 최종 사람 기록 | 모델오류/정답누락/해석차이 구분, 자동 인수 없음 |

## 선행·후속 기능

- 선행: HP-04-practitioner-verdict.
- 후속: 없음.

## 영향 범위

spec·plan의 파일 표를 따른다. 원본·기존 회사·narrative-v2 산출물은 불변이다. 실제 변경은 demo/local-20261009와 bidops-local에 한정한다. 이번 문서 사이클은 DB·모델·실험을 실행하지 않는다.

## 제약

- 원문·프로필·정책·모델 입력과 결과·사람 리뷰는 불변/append-only로 보존한다.
- unknown/null·적합성·참여 준비·추적·Go/No-Go를 서로 대신하지 않는다.
- 외부 모델은 승인 payload만 건별 전송하며 전역 fallback과 자동 추적 결정을 금지한다.
- PostgreSQL 17·versioned MinIO·합성 analysis worker의 슬롯 1개와 모듈 의존 방향을 유지한다.
- 문서 변경은 diff/문서 검사만, 제품 변경은 직접 영향 검사만 실행하고 성공 후 반복하지 않는다.
- 운영 변경·실제 모델 호출은 직전 확인 대상이며 문서화 승인을 실행 승인으로 사용하지 않는다.
- HP 기능은 데모 브랜치 demo/local-20261009와 bidops-local 격리 자원에서만 구현·검증하며 main 병합·운영 전환은 별도 작업이다(ADR-0071).
- HP의 모델 호출은 codex-exec gpt-6-luna/high 하나다. LiteLLM local-agent-main·Qwen·Terra를 쓰지 않고, 기존 정책 파일·실행 row는 바꾸지 않는다(ADR-0071).
- HWP/HWPX 원본이 입력 정본이며 PDF는 PDF 전용 첨부와 쪽 locator에만 쓴다. OCR은 범위 밖이다(ADR-0071).
- 새 DB 테이블·열 권한은 scripts/runtime-privileges.sql에 등록하고 migration에 GRANT를 쓰지 않는다.
- 사용자 요청 없이 commit·merge·push·브랜치 삭제하지 않는다.
- 회사 v2는 가상 실적의 명시 담당 범위만 역량 근거로 연결하고 현재 인력·자격·SLA·계약 수용을 별도 대조한다. 참고 공고는 완료 증거가 아니며 v1/v2 입력·사람 응답 hash를 혼용하지 않는다(HP02 preparation 실적 기반 회사 v2 재계획, 2026-10-15).

추가로 AGENTS.md, docs/standards.md, docs/business-rules.md, docs/contracts.md, docs/operations.md와 변경 경로의 AGENTS.md를 따른다. [실행 입력 해시](../../preparation/source-baseline.preloop.json)에 이번 문서 입력의 해시를 기록한다.

## 결정과 범위 밖

회사 v2의 세 가상 수행 범위와 표준 절차, 51concept·4kind·11관계, 평가10사례, 품질·Neo4j 후보 기준은 2026-10-15 사용자 확정이다. 기술 세부는 사용자의 “너가 먼저 판단” 및 “loop 전 모든 작업” 위임에 따라 spec에 고정한다. 실제 회사의 완료 실적, 현재 자격·가용 인력·계약 수용을 추정하지 않는다. main·운영 변경, origin push, 브랜치 삭제, 자동 Go/No-Go는 범위 밖이다.

## 출처 간 차이

초기 preparation의 D1/D2/v2 초안 표기는 승인 이전 경과다. 현재 승인 파일과 spec을 따른다. 폴리텍 모델 선검토는 독립 gold가 아니다. 기존 승인·사람 응답을 v2로 자동 승격하지 않는다.

## 남은 사람 참여

모델 출력을 보지 않은 평가자 또는 별도 holdout 선택은 독립 평가 전 필요하다. 사람 정답·중대 오류 판정·최종 인수는 대행하지 않는다. 도구 구현은 먼저 가능하다.
