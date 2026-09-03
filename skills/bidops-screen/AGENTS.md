# 구조화 1차 판정 모듈 작업 규칙

## 책임

이 모듈은 고정된 수집 입력과 승인된 회사 프로필을 대조해 구조화 판정을 만들고, 판정 파일을 검증·병합하는 계약을 소유한다. 현재 공고 판정의 다섯 관점·반론·종합을 유지하며, 향후 사전규격 저비용 선별을 추가할 때도 별도 version과 같은 검증 원칙을 적용한다.

원천 수집, 첨부 변환, 심층 문서 분석, 웹 DB 적재, HTML 표현, 최종 사람 결정은 여기서 수행하지 않는다.

## 경계

- 입력의 공고 사실, 후보군, 회사 프로필을 수정하지 않는다.
- 회사 프로필의 `unknown`을 외부 지식이나 모델 추론으로 확정하지 않는다.
- 병합기는 모델 SDK, 웹 DB, 객체 저장소에 의존하지 않는다. 입력·출력 JSON만 읽고 결정적으로 검증한다.
- 누락 관점, 반론, 확인 항목, 근거를 UI 편의 때문에 생성하지 않는다.
- 모델 장애를 hosted OpenAI 호출이나 다른 모델의 암묵적 결과로 대체하지 않는다.

## 판정 불변 조건

- 기술 적합성, 실적 정합성, 공공 SI 적합성, 사업성·자격 제약, 전략 부합을 정확히 한 번씩 포함한다.
- 각 관점은 관점 고유의 이유와 `confirmed|inferred|unknown` 근거를 한 건 이상 가진다.
- 등급과 참여 준비 상태를 독립적으로 판단하고 교차 조건을 검증한다. `부분 확인 필요`에는 확인 항목이 필요하다.
- 자격 미확인만으로 적합성 등급을 낮추지 않는다. 적합성이 높아도 자격을 확인 완료로 바꾸지 않는다.
- 공고별 반론은 한 건 이상이며 같은 상투문이 전체 판정의 40%를 넘으면 실패한다.
- 수행실적 신호에는 매칭 이유와 한계를 남긴다. 유사도는 법적 실적 인정이 아니다.
- 근거는 입력 레코드나 원문 locator를 포함한다. 숫자·날짜·요구사항을 모델 설명만으로 확정하지 않는다.

## 실행과 실패

- 신규·재판정은 다섯 관점, 반론, 종합의 분리된 span을 사용한다. 자유 Markdown 한 번으로 전체 판정을 만들지 않는다.
- execution에 policy, prompt, model name·digest, profile, input digest를 고정한다.
- timeout, truncated output, schema 위반, evidence 누락, 반론 반복은 제한된 재시도 뒤 사람 검토 대기로 남긴다.
- 승계는 model call 없이 `carried_over`, 최초 판정 run, 현재 기록 run을 보존한다. 승계 검증 실패를 신규 성공 판정으로 만들지 않는다.
- 일부 공고만 성공하면 성공 subset과 failure artifact를 함께 보존한다. 유효 판정이 없으면 성공 결과를 발행하지 않는다.

## 버전과 병합

- 과거 경로는 `bidops.validation-set.v2 + bidops.decisions.v2 → bidops.screening.v2`다.
- 현재 경로는 `bidops.screening-input.v1 + bidops.decisions.v3 → bidops.screening.v3`다.
- failure는 `bidops.screening-failures.v1`, telemetry는 `bidops.screening-telemetry.v1`, 재판정 출처는 `bidops.screening-replacement.v1`로 남긴다.
- 표본과 판정 ID를 일대일 대조한다. 세대를 섞거나 값을 추가·보정하지 않는다.
- 새 의미나 상태를 추가하면 새 schema version을 만들고 과거 파일을 소급 수정하지 않는다.

## 검증

```bash
python3 -m unittest discover -s skills/bidops-screen/tests -p 'test_*.py' -t skills/bidops-screen -v
```

다섯 관점 누락·중복, enum, 등급·준비 상태 조합, 차단 확인 항목, 반론 반복 40% 경계, 수행실적 근거, 표본 ID 누락·중복, v2/v3 혼합 거부, 부분 실패와 승계 provenance를 검사한다. 계약 변경은 루트 `./run-tests.sh`도 실행한다.

## 발주계획 C-2 Phase 0 경계

발주계획 `relevant|not_relevant|uncertain` 선별은 공고 다섯 관점 판정과 다른 제품 계약이다.
전용 schema는 `contracts/`에 있고, 현재 고정 입력·raw record source hash·review-input manifest·
선정 증거·부분 C-1 gold·정책·binding은 다음 read-only validator로 확인한다.

```bash
python3 skills/bidops-screen/scripts/validate_order_plan_phase0.py --json
```

validator의 `valid_but_blocked`는 구조·digest 검증 성공일 뿐 실행·활성화 승인이 아니다. 현재
C-1은 human 22건, draft 603건, 잔여 확인 87건이며 이를 자동으로 human gold로 승격하지 않는다.
이 모듈은 C-2 수집·모델 호출·DB 적재·REST·최종 추적/Go-No-Go를 수행하지 않는다. Phase 1
생산자는 input/ranking/decisions/failures/telemetry/result v1의 producer·consumer와 binding을
그대로 소비하고, 기존 `screening.v3` 또는 `ScreeningExecution` 의미를 확장하지 않는다.
