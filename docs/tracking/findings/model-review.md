# 모델 판정·근거 대조 문제 기록

[전체 색인](../findings.md). 미해결 또는 일부 조치 뒤 검증이 남은 항목이다. 제목의 날짜는 마지막 관측·기록 시점이며 2026-10-21에 다시 재현했다는 뜻이 아니다. 과거 기능명·정책·환경을 현재에 적용하기 전에 소스와 마지막 실행 증거를 확인한다.

## RL-03 결정적 대조가 요구사항을 회사 사실에 연결하지 못해 gap을 하나도 찾지 못한다 (2026-10-20, 미해결)

- 재현: RL-05 실제 10건(정책 v11, 회사 근거 v4) — 10건 모두 판정 완료했지만 모델 카드 상태 447개가 전부 `unknown`, met·gap 0, 차단 조건 0. gold는 7개 차단 조건(대구 외 상주 5·회사 제외 분야 HW 2)을 기록했다.
- 영향: RL-05 인수 reject(판정 일치 3/10, 차단 조건 재현율 0.0). 상주 지역·제외 분야처럼 회사 사실이 confirmed인데도 판정이 "조건부 진행"·"판단 불가"에 머문다.
- 원인(추정, 확인 필요): 대조는 추출 항목의 concept 후보 → 온톨로지 → 회사 그래프 경로가 있어야 fit을 내는데, 상주 지역 요구("원주시청 상주")와 `staff:onsite`·`pref:onsite_cap`, HW 유지관리와 제외 분야(`domain` excluded) 사이 경로·규칙이 없다.
- 후속: 대조 단계 개념 매핑·규칙 범위 개선(상주 지역, 제외 분야, 직접생산 품명, 지역 제한) 뒤 같은 gold(`gold.v1.json`)로 재측정. RL-05 채점 도구·gold는 그대로 재사용한다.
- 2026-10-20 읽기 전용 코드 조사: 위 원인 추정은 개념 경로에 한정된다. `card_compare.constraint_comparison`은 그래프 경로 없이 fact_key·앵커·허용 값 경로로도 대조한다. 확인된 공백은 `excl:*`·`pref:onsite_cap`의 대조 allowlist 부재, 시·도 문자열만 인식하는 `_regions`, 다른 상주 지역을 `scope_unverified`로 남기는 분기다. 회사 source v4에는 `supports_capability` 관계도 없다. 개념·규칙·입력의 공백을 함께 고쳐야 하며, 실제 447개 항목별 원인 기여도는 아직 재생하지 않았다. 근거·수정 우선순위·반례는 [온톨로지 비교분석](../../research/2026-10-20-bidops-ontology-assessment.md)에 정리했다. 기존 10건은 수정 회귀에 쓰되 일반화는 새 holdout에서 평가하고, 회사·온톨로지 binding 변경 시 gold의 의미와 버전 정합성을 먼저 확인한다.
- 2026-11-19 [D-2 분해](../../validation-runs/20261119-rl05-unknown-breakdown/README.md): 447개 중 대조 `gap` 0, 놓친 차단 7개는 이상적 추출이어도 대조 분기에서 멈춘다(a1 상주 장소·a2 제외 분야·a3 계약 우선·a4 다중 앵커).
- 2026-11-19 부분 해소(코드만, 종단 미증명) — [RL-10](../../work/groups/RL/features/RL-10-compare-blockers/spec.md) 대조 규칙 v2·정책 v12(브랜치 `feat/rl03-compare-blockers`, 미병합·미배포·DB import 없음): 행정구역 지명 표로 상주 장소를 시·도로 정하고 사람이 확인한 상주 가능 지역 전체 목록 밖이면 `gap`, 확인된 제외 분야의 요구사항 수준 용어로만 이루어진 요구면 `gap`, 역할어가 장소 비교를 막지 않고 모순이 계약 유형보다 먼저다. [탐침 재생](../../validation-runs/20261119-rl10-compare-blockers/README.md): 회사 근거 v4 그대로는 v2도 **0/7**(상주 4개 `unknown_fact` — 구조화 값 없음, 1개 `place_unresolved`, 제외 분야 2개 용어 없음). 테스트 fixture(사람 미확인)를 넣으면 4/7·5/7. 284019(장소 미지정)·284956 B9(하드웨어+SW 혼합)는 결정적으로 `gap`이 될 수 없다. v4 `keywords`를 그대로 용어로 쓰면 인증 수단·법령 이름이 차단되는 과잉 차단이 확인됐다. **남은 것**: (1) 사람이 `pref:onsite_cap.params.onsite_regions`와 `excl:hardware.requirement_terms`를 확인해 새 회사 근거 버전 등록, (2) 실제 추출이 상주 장소를 제약 절에 담는지 확인(`bidops_rla` 제약 단위 행 필요), (3) 같은 gold 재측정(Luna 전송 — 사용자 승인), (4) 추출 전 결정적 사전 검사는 단계 행 migration·차단 조건 규칙 재정의가 필요한 후속(RL-10 spec E5). 이 항목은 재측정 전까지 닫지 않는다.


- 인수 절차·입력/산출물 hash·사람 reject는 [RL-05 실행 기록](../../validation-runs/2026-10-19-rl/RL-05/README.md)에 있다. 이번 문서 정리에서 모델 재호출·규칙 수정은 하지 않았다. RL-07은 프런트엔드 범위라 이 대조 공백을 해결하지 않는다.

## RL-03 카드 판정은 제약 하나의 검증 실패로 판정 전체가 사람 검토로 끝난다 (2026-10-18, 설계·구현됨, 실제 증명 대기)

- 재현: bidops-local `bidops_rla` 폴리텍 사전규격(notice 362, opportunity 353, 원문 HWP SHA `8b6cbf1a…005a1e`), 정책 v3~v5 실제 Luna 판정 T12 4~7차(attempt `6dd54a57…`·`bd0fe0a3…`·`28086c87…`·`ff63bc6e…`). 4차 이후 매번 묶음 응답의 제약 1개(5차 `다음 달 10일까지` 단위, 6차 잘린 인용 `5`, 7차 날짜 범위에서 계산한 기간 12)가 결정적 추출 검증에 걸려 `card_extract_invalid`·`needs_human_review`로 끝났다. 진단과 재생 근거는 `docs/validation-runs/2026-10-17-rl/RL-03/README.md` T12 절, 결정 B30~B37.
- 영향: 한 판정이 검증하는 인용·제약이 60개 이상이고 하나라도 틀리면 묶음과 판정 전체가 실패한다. 항목 정확도가 높아도 전체 통과 확률이 낮아(98%/항목이면 약 30% 추정) 실제 판정과 RL-04 실제 초안(T11)을 얻지 못했다.
- 지금 해결하지 않는 이유: 틀린 제약만 그 항목의 사람 검토 대상으로 격리하고 나머지로 판정을 이어가는 방식은 판정 의미·완료 조건·화면 표시를 바꾸는 spec 변경이다. 자동 보정(제약 삭제·값 수정)은 강제 게이트상 금지라 대안이 아니다.
- 후속: 항목 단위 실패 설계(실패 항목 표시, 그 항목이 판정 근거에서 빠질 때 판정 상한, 사람 검토 흐름, 감사)를 별도 기능으로 설계하고 승인 뒤 실제 판정 1건으로 증명한다. 검증기 결함(인용 위치·범위 기호)은 B37에서 고쳤다.
- 상태(2026-10-18, 결정 B51): RL-03 STEP-011로 설계·구현됨 — 정책 v7에서 증거 규칙 위반 항목만 격리(`rejected_units`, 대조 `extract_rejected`, 판정 상한 "조건부 진행", 25% 초과 시 판정 실패, 자동 보정 없음), 판정 탭 "검증 실패 — 사람 확인 필요" 목록. 저장된 실제 답 재생에서 5~7차의 batch 단위 실패는 격리(2~7개, 32 unit의 25% 이하)로 바뀐다(RL-03 spec B51 절). 2026-10-18 실제 10차(9차 종합 재실행, B55)에서 첫 실제 판정이 completed(`667bf04d…`, 격리 2건, "판단 불가")됐다. 남은 것은 `real_data_run`의 사람 확인(B57)이며, 그 전까지 이 항목은 닫지 않는다.

## 실제 Qwen 회사 대조가 근거 ID와 주장 ID를 혼용한다 (2026-09-22, 미해결)

- 재현: 참조 심층검토 `835e686e-c8c5-42c7-b5b0-3131faf787b8`의 네 번째 실행에서
  원문 대조 off로 문서 분석은 완료됐지만 회사 대조가 실패했다. 저장된 암호화 응답을
  재검사하니 입력에 제공한 회사 근거 ID 3개를 `premise_claim_ids`에 사용했다.
  해석 문장의 근거 연결 누락과 `unknown_shape` 위반도 확인했다.
- 별도의 과도한 검사: 정상적인 선행 주장 7개를 `considered_claim_ids`에 기재한 것을
  회사 대조라는 이유만으로 거부했다. 이 제약은 입력 범위 안이면 허용하도록 완화했다.
  관련 검사 10개를 통과했지만 실제 저장 응답은 여전히 참조/근거/미확인 형식 검사에 실패한다.
- 영향: 완성 보고서가 생성되지 않는다. 원문 인용·숫자 검사를 끄는 것과 보고서 연결
  계약을 무시하는 것은 다르므로 이를 자동 보정하거나 실패 응답을 보고서로 발행하지 않는다.
- 현재 범위와 후속: 검증 스위치와 연속 문단 허용은 적용했다. 모델의 ID 종류 혼동·근거
  작성 방식을 해결하려면 새 불변 정책의 명시적인 출력 예시와 생성 품질 검증이 필요하다.
  기존 실행/정책/응답은 보존하고, 후속 품질 작업에서 고정 응답 재검사와 실제 전체 생성을
  구분해 확인한다. [실제 검증 기록](../../validation-runs/20260922-narrative-review/live-validation.md).

## 심층 보고서의 빈 결과·서버 설명에도 무관한 claim 연결이 필요해진다 (2026-09-22, 미해결)

- 확인: Fable 독립 검토 지적을 소스에서 재확인했다. `deep_review_validation.py:947–957`은
  본문이나 셀이 있으면 claim ID를 요구한다. `reports.py`는 위험 없음·미확인·다음 행동에
  전체 claim을 연결하고, 묶음 제외 설명에도 절별 fallback claim을 연결한다.
- 영향: claim 연결 존재가 문장 근거를 보증하지 않으며, `or claims`만 제거하면 서버의
  묶음 제한 설명이 검증을 통과하지 못할 수 있다. renderer와 validator를 함께 고쳐야 한다.
- 현재 범위와 후속: 계획 작업이므로 제품 변경은 하지 않았다. 서버 상태 설명과 원문 사실을
  구분하는 새 계약을 정의하고, 임의 note로 사실 검증을 우회하지 않게 한다.
  수정 순서와 인수 기준은 [심층검토 수정 계획](../../0922_deep-review-improvement/plan.md)에 있다.

## 심층 재실행 상태가 이전 완료 보고서 조회를 막고 문서 기준 차이를 설명하지 않는다 (2026-09-22, 미해결)

- 재현 조건(코드): 완료된 review에도 `create_attempt`가 새 attempt를 만들 수 있다.
  `reports.py::get_report`는 현재 attempt의 완료를 먼저 요구하므로 새 실행이 대기·진행·실패면
  이전 report revision이 남아 있어도 `review_not_ready`로 거부한다. 두 화면도 completed에서만
  report 조회를 켠다. DB·운영 실행을 통한 재현은 이번에 하지 않았다.
- 추가 확인: `PreSpecDetailPage.tsx`의 보고서 요약은 `report.bundle_id`와 화면의 문서 묶음
  기준 차이를 표시하지 않는다. 새 묶음 존재만으로 옛 보고서가 틀렸다고 단정할 수는 없다.
- 영향: 이전 판단 근거·의견이 조회 경로에서 사라지거나 다른 문서 기준의 조건이 현재처럼 보일 수 있다.
- 현재 범위와 후속: 실행 상태와 열람할 snapshot을 분리하고, 미확정/실패 묶음·확정 원문 변경·
  같은 입력 재시도를 구별한다. 기존 결과는 보존하며 새 조회 계약과 연속 회귀 사례로 수정한다.

## 심층 화면의 수정본 표시와 초안 갱신이 현재 보고서에 정확히 결합되지 않는다 (2026-09-22, 미해결)

- 확인(코드): `DeepReviewPage.tsx:363`은 `history[0].sequence`를 현재 수정본처럼 표시하지만
  `reports.py::_view`는 이력을 오름차순으로 반환한다. revision 2가 있어도 1차로 표시된다.
  같은 화면 `190–195`는 새 report 응답마다 draft와 dirty flag를 초기화한다.
- 재현 조건: 수정본이 둘 이상인 보고서를 열거나, 사용자가 편집하는 동안 다른 사용자의 저장으로
  재조회 응답이 달라진다. 후자는 화면 조작 재현 전이며 effect에 의한 덮어쓰기 경로를 확인했다.
- 영향: 보는 수정본을 잘못 파악하거나 미저장 초안이 사라질 수 있다.
- 현재 범위와 후속: 현재 revision ID로 차수를 찾고 초안의 기준 revision을 고정한다.
  재조회 변경은 알림과 충돌 처리로 연결하고 초안을 자동 교체하지 않는다.

## 심층 종합 조각 간 근거 중복 제거가 뒤 호출의 근거를 없앤다 (2026-09-22, 미해결)

- 재현: `DeepReviewService._stage_slices('synthesis_and_validation', ...)`에 본문 8,000자인
  claim 2개와 두 claim이 함께 참조하는 evidence 1개를 넣었다. 조각은 2개였으며 첫 조각은
  evidence를 받고 둘째 조각은 evidence ID만 참조한 채 `prior_evidence=[]`였다.
- 원인: `deep_reviews.py:1045`의 `seen_evidence_ids`를 전체 claim에서 공유한 뒤 조각을 나눈다.
  실제 호출은 `prior_stages=()`여서 빠진 근거를 별도 입력으로 보충하지 않는다.
- 영향: 전체 단계에서 근거가 존재하더라도 해당 종합 호출은 인용 내용·위치를 읽지 못한다.
  기존 테스트는 작은 단일 조각의 중복 제거만 확인하며 실제 모델 오판율은 미측정이다.
- 현재 범위와 후속: 모델·DB 호출 없이 합성 helper로 재현했다. 조각별 참조 근거를 완결하고
  프롬프트 예산을 다시 검사한다. 공유 근거가 조각 경계를 넘는 회귀 사례를 추가한다.

## 심층 보고서가 사업 위험과 근거 검증 실패를 같은 것으로 요약한다 (2026-09-22, 미해결)

- 재현: `services/reports.py::_render_report`에 `status=supported`인 보안·계약 위험 claim을
  주면 결정 카드의 차단 위험은 `확인된 차단 위험이 없습니다.`가 된다. 합성 입력으로 확인했다.
  해당 행은 위험 심각도가 아니라 `unsupported|conflicting` claim만 모은다.
- 영향: 원문 근거가 충분한 사업상 차단 조건이 요약에서 빠질 수 있다. 사전규격 상세도
  심층 보고서의 `unknowns`만 위험 목록으로 옮겨, 확인된 기술·계약 위험을 전달하지 않는다
  (`PreSpecDetailPage.tsx`의 `risks` projection).
- 현재 범위와 후속: 이번 요청은 기능·UX 점검이므로 기존 보고서·정책을 바꾸지 않았다.
  근거 검증 상태와 사업 위험의 심각도를 분리하고, 확인된 위험·미확인·미분석을 별도로
  표시하는 출력 계약과 두 화면의 공통 projection이 필요하다. 실제 운영 발생 빈도는 미측정이다.

## 심층 보고서의 절별 조립이 무관한 결과를 채우고 일부 본문을 생략한다 (2026-09-22, 미해결)

- 재현: `reports.py::_render_report`에 같은 보안·계약 category의 claim 2개만 전달한다.
  category가 없는 자격·요구사항 표에는 두 claim이 모두 복제되고, 경제성에는 첫 위험이
  들어가며, 보안·계약 위험 본문에도 첫 claim만 출력된다. 합성 입력으로 확인했다.
- 원인: `_section_claims(...) or claims`와 `first_body`를 쓰며, matrix·결정 카드 외에는
  `rows=[]`다. 프런트는 일반 block의 `claim_ids`를 본문·근거 버튼으로 렌더하지 않는다.
- 영향: 13개 필수 절의 존재가 해당 영역의 분석 완료를 뜻하지 않는다. 누락을 다른 영역의
  내용으로 덮고, 저장된 후속 claim은 해당 절에서 읽을 수 없다.
- 현재 범위와 후속: 점검 범위여서 제품 수정은 하지 않았다. 영역별 분석 상태·명시적 매핑,
  전체 claim 표시와 문장별 근거 연결을 정의하고, 없는 영역은 미분석으로 보존해야 한다.

## 심층 회사 적합성 입력이 문서 조각과 프로필 조각을 순번으로만 짝짓는다 (2026-09-22, 미해결)

- 재현: `deep_reviews.py::_stage_slices`의 2단계에 문서 6쪽(쪽마다 합성 문구 1,300회 반복)과
  회사 fact 1개를 준다. 생성된 6개 slice 중 첫 slice만 fact 1개를 받고 나머지 5개는 0개다.
- 원인: 요구사항 slice와 프로필 slice를 각각 분할한 뒤 같은 index끼리만 결합한다.
  2단계에는 앞 단계의 추출 결과도 입력으로 전달하지 않는다.
- 영향: 전체 입력에 존재하는 회사 근거라도 해당 요구사항을 분석하는 호출에서는 빠질 수
  있다. 입력 전송 완료만으로 요구사항과 회사 역량의 대조 범위를 보장할 수 없다.
- 현재 범위와 후속: 모델 호출 없이 입력 생성만 재현했다. 실제 오판율은 미측정이다.
  요구사항별 관련 회사 근거 연결과 누락 검사, 조각 전체를 종합하는 단계를 설계해야 한다.

## 심층 검증 요약 건수가 실제 검사 목록과 다른 기준으로 계산된다 (2026-09-22, 미해결)

- 재현: `reports.py::_render_report`에 unknowns가 없는 passed 입력을 주면 warnings=0이다.
  같은 입력의 inventory가 비어 있으면 `build_segment_checks({}, [])`는 warning 1개를 만든다.
- 원인: 요약의 warnings는 `len(unknowns)`, failed는 상태에 따른 0/1이며, 실제 검사 목록은
  `_validation_result`에서 별도로 만들어진다. `_insert_revision_and_validation`은 요약을
  실제 check 건수로 바꾸지 않는다.
- 영향: 상단의 실패·경고 건수와 본문의 검사 목록이 다를 수 있다. 검사들은 대체로
  `related_claim_ids/related_evidence_ids=[]`여서 행별 검증 표시와 실패 원문 이동도 제한된다.
- 현재 범위와 후속: 점검 범위여서 계약·기존 결과를 수정하지 않았다. 미확인 업무 항목 수와
  검증 check 건수를 구분하고, 건수·상태·이동 대상이 같은 검사 결과에서 나오게 해야 한다.

## C-2 stage 2 구현이 측정된 방법과 어긋나 있었다

- 확인: 2026-09-03
- 상태: **해결** (2026-09-03, [ADR-0044](../decisions/0044-c2-stage2-matches-the-measured-method.md))
- 재현 조건: 제품이 보내던 요청이 ADR-0037이 625건으로 측정한
  `experiments/order-plan-screening/scripts/methods.py::QwenAdapter._score_batch`와
  네 곳에서 달랐다. ① `plan_id`/`company` vs 승인 prompt가 계약한 `item_id`/
  `company_capabilities` ② `json_object` vs strict `json_schema`
  ③ `chat_template_kwargs`가 `extra_body`에 중첩돼 vLLM이 무시
  ④ generation config를 읽지 않고 하드코딩.
- 원인: stage 1 BM25와 병합은 `skills/` 스크립트를 subprocess로 부르지만 stage 2만
  백엔드가 재구현했고, 그 구현을 실제 서버로 검증한 적이 없었다. 기존 테스트는 오히려
  잘못된 모양(`extra_body` 중첩)을 단언해 네 건을 모두 통과시켰다.
- 해결: 요청 조립을 측정된 방법과 같게 맞추고, 승인 generation config를 아티팩트로
  복원해 실제로 읽게 했으며, 두 body가 같은지 단언하는 적합성 테스트를 넣었다.
  발주계획 1,040건 회차 재실행에서 300/300 완료·실패 0건.
- 남은 공백: BM25와 Qwen 요청 조립이 `experiments/`와 `web/backend/`에 각각 존재한다.
  적합성 테스트가 드리프트를 잡지만 구현이 하나가 된 것은 아니다. stage 2를 stage 1처럼
  subprocess 계약으로 내리는 것은 raw 응답 전달과 실패 코드 계약을 새로 설계해야 해서
  이번 범위에서 하지 않았다.

## 발주계획 Qwen 잘림 응답의 실패 token 계측이 보존되지 않는다

- 재현 조건: 실행 `20260824-20260826-interim-v4`의 동결 모집단 997건을 Qwen `qwen3.8:27b`, 고정 batch 25, `think="high"`, `num_predict=4096`으로 판정한다. 40개 중 10개 batch에서 Ollama가 `done_reason=length`를 반환한다.
- 증상: adapter가 `done_reason=length`를 확인하자마자 `truncated_output` 예외를 발생시켜 실패 응답의 `prompt_eval_count`, `eval_count`, thinking/content 길이와 duration을 결과에 옮기지 못한다. 해당 batch의 25건은 오류와 분배 latency만 갖고 input/output token은 `null`로 남는다.
- 영향: 생성 길이 제한이 직접 종료 원인이라는 것은 확인할 수 있지만, batch 크기, thinking 길이, 최종 JSON 길이가 각각 한도 소진에 얼마나 기여했는지 분해할 수 없다. 현재 실행은 747/997건만 성공했으므로 Qwen을 운영 후보로 승인하거나 안전한 batch·token 값을 결정할 근거가 부족하다.
- 지금 해결할 수 없는 이유: 현재 범위는 기존 불변 실행의 사후 결과 기록이다. 실패 batch telemetry를 추가하려면 method-result 계약의 batch 진단 표현, 비밀·본문 비보존 경계, renderer와 단위 테스트를 함께 변경하고 새 run ID로 live 재검증해야 한다.
- 접근 방법: 실패 응답 본문은 저장하지 않고 `done_reason`, prompt/eval token count, total/eval duration, thinking/content 문자 수만 안전한 batch 진단으로 보존한다. 동일 실패 batch에서 기준 설정을 재현한 뒤 batch 10, `num_predict=8192`, 모델이 지원하는 thinking 설정을 한 변수씩 분리해 비교한다. 상세 증거와 artifact hash는 [`20260828-order-plan-screening-interim-v4.md`](../../validation-runs/20260828-order-plan-screening-interim-v4.md)에 기록했다.

## 현재 보고서 renderer가 screening v3를 처리하지 못한다

- 재현 조건: `bidops.screening.v3`의 `screening-results.json`을 현재 report stage 또는 `render_report.py`에 전달한다.
- 증상: current screening runtime은 v3를 만들고 적재기는 v3를 받지만 report renderer는 `bidops.screening.v2`만 허용해 즉시 종료한다.
- 영향: 새 판정 실행의 결과를 기존 HTML·feedback 흐름으로 연결할 수 없고 자동 pipeline에서 판정과 보고 사이가 끊긴다.
- 지금 해결할 수 없는 이유: v3의 partial/failure·execution binding을 HTML과 feedback에 어떻게 표시할지 소비자 계약과 회귀 기준이 필요하다.
- 접근 방법: v2 의미를 바꾸지 않은 채 renderer에 명시적 v3 adapter를 추가하고 부분 성공·failure artifact·승계 provenance를 표시한다. v2와 v3 fixture의 결정성을 각각 검증한다.

## 실제 심층 검토 품질 corpus와 사람 gold가 부족하다

- 재현 조건: 대표 HWP/PDF에서 요구사항 recall, 사람 일치율, unsupported claim 비율을 계산하려 한다.
- 증상: 55개 요구사항 기대 ID 사례는 있으나 원문·claim별 gold mapping과 다양한 기관·문서 형식의 사람 adjudication이 충분하지 않다.
- 영향: Mock E2E와 단일 후보 호출은 실제 사업 판단 품질이나 0.80/0.70/0.10 activation 기준을 증명하지 못한다.
- 지금 해결할 수 없는 이유: 완료 사업의 사용 승인된 첨부와 담당자 기준 답안이 더 필요하다.
- 접근 방법: 공공 SI와 AI·데이터 또는 블록체인 축에서 서로 다른 HWP/PDF 사례를 선정하고 source hash, requirement·자격·배점·위험 gold, claim별 사람 판정을 만든다. 실제 immutable model로 gate를 측정한다.

## C-1과 C-2가 모델 호출 경계를 서로 반대로 잡는다

- 확인: 2026-09-03
- 재현 조건: 같은 "선별" 업무의 두 사례가 모델을 부르는 방식을 비교한다.
- 증상: C-2(발주계획)는 `web/backend/app/core/config.py:351,353`이
  `skills/bidops-screen/scripts/rank_order_plans_bm25.py`와
  `build_order_plan_screening_results.py`를 subprocess로 호출한다.
  [ADR-0001](../decisions/0001-artifact-boundary.md)의 경계 그대로다.
  반면 C-1(공고)은 `web/backend/app/screening/orchestrator.py`에서 웹 프로세스 안의 판정
  어댑터(`ScreeningModelClient`)를 직접 생성하고, `app/screening/`에 `model_adapter.py`·
  `prompts.py`·`worker.py`가 들어와 있다.
- 2026-09-05 정정: [ADR-0050](../decisions/0050-unified-openai-compatible-model-client.md)이
  C-1·개요·심층의 **transport**를 `app/core/model_client.py` 하나로 합쳤다. 그래서 전송 경계와
  fail-closed 규칙은 이제 한 벌이다. **그러나 이 항목이 말하는 경계 차이는 그대로다** — C-1은
  여전히 웹 프로세스 안에서 모델을 부르고 C-2는 subprocess 파일 계약으로 부른다. 위 재현
  조건의 파일 이름만 현재 값으로 고쳤다.
- 영향: 같은 업무 규칙이 두 경계에 나뉘어 있어 모델 전송 감사·테스트 격리·정책 pinning의
  확인 지점이 사례마다 다르다. 새 선별 흐름을 추가할 때 어느 쪽을 따라야 하는지 규칙이 없다.
- 지금 해결할 수 없는 이유: C-1은 [ADR-0013](../decisions/0013-screening-orchestrator-boundary.md)이
  판정 단계만 애플리케이션 오케스트레이터로 옮긴 결과이고 이미 운영 중인 흐름이다.
  경계를 되돌리려면 정책 활성화·품질 게이트·큐 재실행 경로를 함께 옮겨야 하며
  [ADR-0043](../decisions/0043-screening-deep-review-module-boundary.md)·[ADR-0045](../decisions/0045-backend-module-layout.md)의 모듈 이주 범위를 넘는다.
- 접근 방법: 모듈 경계 이주가 끝난 뒤 C-1 오케스트레이터의 모델 호출부만 떼어
  C-2와 같은 subprocess 계약으로 맞출 수 있는지 별도로 판단한다. 그 전까지는 두 경계가
  다르다는 사실을 `ARCHITECTURE.md`에 명시해 새 흐름이 임의로 한쪽을 고르지 않게 한다.

## C-1 모델명이 바뀌어 기존 실행·판정 row가 새 실행에서 거부된다

- 확인: 2026-09-05
- 재현 조건: 옛 이름(`qwen3.8:27b`)으로 기록된 `ScreeningExecution`과 그 판정이 있는 DB에서
  새 회차를 판정하거나 재판정한다. `web/backend/app/core/model_binding.py`의 `MODEL_NAME`은
  이제 `qwen3.8-27B`이고 C-1이 부르는 이름은
  `settings.vllm_screening_model`(`BIDOPS_VLLM_SCREENING_MODEL`, 기본 `qwen3.8-27B`)이다.
- 증상: carry-over 검증과 재판정 검증이 실행 binding의 모델명을 대조하므로 옛 이름의 row는
  이어지지 않고, `queue.enqueue`도 현재 이름과 다른 binding을 거부한다.
- 영향: 이전 회차의 판정을 승계하려는 재판정이 승계 대신 새 판정으로 떨어지거나 거부된다.
  `docs/model-quality-gate.md`가 고정 입력으로 못 박은 40건 표본도 옛 이름으로 기록돼 있으면
  그 execution을 새 A/B의 baseline으로 재사용할 수 없다.
- 지금 해결할 수 없는 이유: 실행 binding은 불변이다([ADR-0007](../decisions/0007-immutable-runs.md)).
  저장된 모델명을 사후에 새 이름으로 고쳐 쓰는 것은 "회차 원본을 덮어쓰지 않는다"는 게이트를
  깬다. 옛 데이터를 이어 쓸지, 새 이름으로 다시 측정할지는 담당자의 판단이 필요하다.
- 접근 방법: (1) 새 이름으로 A/B를 다시 측정하고 옛 execution은 이력으로만 둔다(권장), 또는
  (2) 옛 이름을 새 이름의 별칭으로 인정하는 명시적 매핑을 binding 검증에 도입하고 그 결정을
  ADR로 남긴다. (2)를 고르면 어느 실행이 어느 실제 배포에서 나왔는지 감사에서 구분할 수
  있어야 한다.

## `policy_quality` snapshot 모양이 바뀌어 이전에 만든 미실행 심층 검토가 503으로 닫힌다

- 확인: 2026-09-05
- 재현 조건: 이 변경 **전에** 생성돼 아직 실행되지 않은 심층 검토를 worker가 claim한다.
- 증상: `web/backend/app/deep_review/services/deep_reviews.py`의 `run_claim`이 생성 감사의
  `policy_quality`를 현재 계산값과 **정확히 같은지** 비교한다. 참조 실행 표식을 위해
  snapshot에 `deployable` 키가 항상 붙게 됐으므로 옛 snapshot과 모양이 달라지고
  `service_unavailable`(503, "pinned deep review 입력이 변경되었습니다")로 닫힌다.
- 영향: 변경 시점에 큐에 남아 있던 심층 검토는 실행되지 않는다. 결과가 틀리게 나오는 것이
  아니라 **아예 실행되지 않는** 것이므로 조용한 오염은 없다.
- 지금 해결할 수 없는 이유: 옛 snapshot을 새 모양으로 다시 쓰면 감사 이벤트를 덮어쓰게
  된다. append-only 감사 계약을 깨는 조치라 하지 않는다. 비교를 느슨하게 만들면 pinned 입력
  대조 자체가 약해진다.
- 접근 방법: 해당 review에 **새 attempt를 만든다.** 새 attempt는 현재 모양의 snapshot으로
  다시 고정된다. 운영 절차의 참조 실행 6단계에 이 중단 기준을 적어 두었다.

## 개요 attempt와 암호화된 원응답 사이에 직접 FK가 없다

- 확인: 2026-09-05
- 재현 조건: 개요 검토 attempt 하나가 어느 모델 응답 객체에서 나왔는지 DB만으로 찾으려 한다.
- 증상: 원응답은 `ContentObject`와 `ContentObjectLocation('model-response')`로 암호화 저장되지만
  `prespec_overview_attempt`에는 그것을 가리키는 열이 없다. 대조는 감사 이벤트
  `prespec_overview.attempt_run`의 `safe_metadata.response_sha256`으로만 가능하다.
- 영향: 감사 이벤트가 없거나 지워지면 attempt와 원응답의 연결을 DB에서 복원할 수 없다.
  응답 객체 자체는 남지만 어느 attempt의 것인지 확정할 수 없다.
- 지금 해결할 수 없는 이유: 이 표에 열을 더하는 것을 명세가 이번 범위에서 두 개
  (`lease_owner`, `lease_expires_at`)로 제한했다. FK를 더하면 그 경계를 넘고, 기존 row의
  backfill 정책도 함께 정해야 한다.
- 접근 방법: nullable `response_content_object_id` FK를 다음 migration에서 더하고, 기존 row는
  추정 없이 `null`로 둔다. 감사 이벤트의 `response_sha256`은 그대로 유지해 두 경로가 서로를
  검증하게 한다.

## 요구사항 대조 검사가 ID 체계를 가진 실제 문서에서 구조적으로 실패한다

- 확인: 2026-09-05
- 재현 조건: 요구사항 ID 체계를 가진 제안요청서로 심층 검토를 완주시키고 보고서의
  `validation_summary`를 본다. `tests/fixtures/.../fire_prevention_55.json`이 기대하는
  유일 ID는 55개다.
- 증상: stage 1 claim 상한이 8개(`app/core/model_client.py`의 `bounded_output_rule`)라
  모델이 문서의 ID를 다 언급할 수 없다. `deep_review_validation`의 `requirement_inventory`가
  `missing = expected - observed`를 `failed`(중대)로 올리고, `reports.py`가 그것을 보고서
  `validation_status = "failed"`로 승격한다. `system_recommendation`은 `보류`가 된다.
- 영향: 첫 참조 실행부터 ID 체계가 있는 문서의 보고서가 **구조적으로** 실패로 나온다.
  이것은 "문서를 잘못 읽었다"가 아니라 "검사 기대치와 모델 출력 예산이 맞지 않는다"는 뜻이다.
- 지금 해결할 수 없는 이유: 명세 §6.7이 "누락·예상 밖 ID가 있으면 `failed`(중대)"로 정했다.
  claim 상한을 올리면 참조 실행 비용과 프롬프트 경계가 함께 바뀌고, 기대 집합을 좁히면
  명세를 고쳐야 한다. 담당자가 2026-09-05에 이번 차수에는 명세대로 두기로 결정했다.
- 접근 방법: 다음 차수에 셋 중 하나를 명세 개정과 함께 정한다.
  (a) 기대 집합을 stage가 실제로 다룬 구간으로 좁힌다.
  (b) 누락을 경고로 낮추고 누락 목록만 보고서에 싣는다.
  (c) claim 상한을 문서 규모에 맞게 연다.

- 2026-09-22 소스 재검토 보정: 현재의 8 claim은 **slice별 프롬프트 지시**이며 schema의
  `maxItems`나 전체 문서 상한이 아니다. 하나의 claim이 여러 요구사항 ID를 포함할 수도 있어
  위의 "모델이 ID를 다 언급할 수 없다/구조적으로 반드시 실패한다"는 설명을 일반화하지 않는다.
  요약 위주 출력과 전수 분석 사이의 불일치 위험은 남는다. 새 수정 계획은 조각별 입력 ID와
  전체 inventory 합집합을 함께 검사하고 출력 예산을 맞추며, 누락의 경고 하향이나 검사 범위
  축소를 채택하지 않는다. 기존 사람 결정·정책을 이 보정만으로 변경한 것은 아니다.

## mock 종단의 개요 검토가 실제 참조 실행과 응답에서 구분되지 않는다

- 확인: 2026-09-05
- 재현 조건: `python -m app.deep_review.cli run-prespec-e2e`로 mock 종단을 완주시키고
  개요 attempt의 `quality_status`를 본다. `unmeasured_reference`가 나오며, 이는 실제
  승인 사설 vLLM 참조 실행과 같은 값이다.
- 원인: 명세 §6.3이 `reference_only=true`인 attempt의 완료를 금지하고(§7의
  `ck_prespec_overview_attempt_completed_binding`도 같다), §8이 `quality_status`를
  `reference_only` 하나로만 가른다. 그래서 저장소만으로 개요를 완주시키려면 mock을
  provider가 아니라 **transport 계층**에 두어야 하고, 그때 binding은 `reference_only=false`가
  되어 표식이 `unmeasured_reference`로 남는다.
- 영향: 화면·응답만으로는 mock 종단이 만든 개요 결과와 실제 참조 실행 결과를 가릴 수 없다.
  현재는 mock 종단이 테스트·검증 경로에서만 돌고 운영 화면에 그 데이터가 생기지 않아
  실제 혼동은 일어나지 않는다. 심층 검토의 `mock_reference`는 provider에서 나오므로
  이 제약과 무관하다.
- 지금 해결할 수 없는 이유: 세 번째 판별자(attempt에 transport 표식)를 넣으려면 명세 §8이
  허용한 응답·DB 변경 목록 밖의 열과 필드가 필요하다. 담당자가 2026-09-05에 이번 차수에는
  기록만 남기기로 결정했다.
- 접근 방법: 다음 차수에 attempt에 transport 표식을 더하고 `quality_status` 계산을
  `reference_only`와 transport 두 축으로 가른다.
- 종결(2026-09-11): `prespec_overview_attempt`·`reference_only`·`ck_prespec_overview_attempt_completed_binding`이
  참조하던 v4/v5 개요 attempt 테이블을 [ADR-0054](../decisions/0054-prespec-overview-mvp-rewrite.md)로
  삭제했다. 새 `prespec_overview_run`은 `quality_status` 필드 자체를 두지 않으므로(계약은
  [contracts.md](../../contracts/prespec-overview.md#사전규격-개요-검토와-예비-적합성-판단-mvp-2026-09-21)) 이 판별 문제가 해당 스택
  폐기로 종결됐다.

## 회사 프로필 원문 일부가 심층 모델 fact 입력에서 빠진다

- 확인: 2026-09-07, 미해결.
- 재현: `docs/reference/company-profile.md`를 `app.core.company_profile.parse_profile`과
  `app.deep_review.services.input_versions._profile_payload_and_facts`로 읽는다.
  43 facts(confirmed 24, inferred 4, unknown 15)와 `profile_section_unstructured`가 나온다.
- 영향: 대표 실적·인증·솔루션 등 일부 서술/표는 원문에 있어도 모델 fact로 들어가지 않는다.
  파일 보유나 import 성공을 정보 충분성으로 해석할 수 없다.
- 이번 범위: 사용자가 요청한 프로필 충분성 점검과 실제 첨부·개요 실행이다.
  원문 보유 사실의 구조화 계약과 미확인 정보의 담당자 확인이 필요하므로
  추정 보완이나 기존 snapshot 변경으로 해결하지 않았다.
- 후속: 근거 위치를 보존한 구조화와 새 버전 import, 원문 대비 fact 포함 범위 검사,
  자격·인력·실적 증빙의 정보 공백 확인.
- 상세: [실행 범위와 프로필 점검](../../validation-runs/20260907-prespec-overview-profile-check.md).
- 후속 실행: 기존 43 facts를 모두 보존한 별도 구조화 후보 117 facts를 profile version 2로
  가져왔다. 원문의 명시적 confirmed 항목과 unknown 후보를 구분했고 활성화하지 않았다.
  실제 자격·실적·가용 인력의 정보 공백은 남아 있다.
  [실제 실행 기록](../../validation-runs/20260907-prespec-overview-live.md) 참고.

## 개요의 조건부 권고가 확인 기한을 생성하고 위치 검증이 주장 의미를 보장하지 않는다

- 확인: 2026-09-07, 미해결. SW사업대상=Y 10건의 실제 Qwen 개요 테스트에서 재현했다.
- 재현: 개선된 개요 범위의 원문만 제공하고 기존 결과 schema로 Qwen thinking 꺼짐 호출을 한다. 회사 프로필과 승인된 확인 기한은 제공하지 않는다.
- 증상: 10건 모두 조건부 권고와 임의 확인 기한을 생성했고, 7건은 실행일보다 과거였다. 최소 5건에서 실제 존재하는 한 문단의 범위보다 넓은 내용을 claim에 묶었다. 1건에서는 이미 수행한 절차를 앞으로 필요한 절차로 summary에서 바꿨다.
- 원인과 영향: 조건부 권고는 기한을 필수로 요구하지만 입력에는 승인된 기한이 없다. `validate_overview_result`는 schema와 ordinal/block_key를 검사하며 기한의 출처·claim 전체의 의미·summary의 완료 상태까지 검증하지 않는다. 형식·위치 통과를 사실 정확성이나 후속 자동 분석 승인으로 사용할 수 없다.
- 이번 조치: 별도 실험의 최종 결과 10건을 `needs_human_review`로 분류하고 validation 감사에 사유를 남겼다. 운영 리뷰·정책·snapshot에 반영하지 않았으며 원응답을 수정하지 않았다.
- 현재 해결하지 않은 이유: 요청 범위는 10건 실제 테스트다. 확인 기한의 소유권과 조건부 권고 계약, 다중 문단 근거 및 의미 검증을 함께 정해야 하므로 기한을 임의 보정하거나 출력 계약을 조용히 변경하지 않았다.
- 후속: 승인된 확인 기한이 없는 경우의 권고 규칙을 명시하고, claim별 다중 근거·숫자·날짜·완료 상태의 검증과 사람 확인 경계를 보완한다.
- 증거: [Qwen 10건 개요 검토 실험](../../validation-runs/20260907-prespec-overview-qwen-10.md).
- 종결(2026-09-11): `추진 검토|조건부 추진 검토|보류|검토 종료` 권고와 `verification_due_at`
  필드 자체가 [ADR-0054](../decisions/0054-prespec-overview-mvp-rewrite.md)로 삭제됐다. 새
  `prespec_overview_run`의 result에는 권고·확인 기한이 없고 claim별 인용 대조·필수 섹션만
  결정적으로 검사하므로(계약은 [contracts.md](../../contracts/prespec-overview.md#사전규격-개요-검토와-예비-적합성-판단-mvp-2026-09-21))
  이 문제는 해당 스택 폐기로 종결됐다.

## 2026-09-03~09-07 실제 참조 실행의 개요 검증 실패

- 확인: 2026-09-07. 실행 근거: [기간별 실제 실행](../../validation-runs/20260907-pipeline-20260903-20260907-live.md).
- 재현: 문서 범위가 `ready`인 R26BD00271850·R26BD00271607·R26BD00271523을
  승인 사설 Ollama `qwen3.8:27b`의 고정 digest·개요 정책으로 실행했다.
- 결과: 앞의 2건은 `validation_failed`, 마지막 1건은 `prompt_rejected`로 종료됐다.
  개요 완료 결과가 없어 자동 심층 검토의 필수 조건을 만족하지 않는다.
- 경계: 이번 작업은 기간 수집과 실제 참조 경로 확인이다. 응답 계약을 느슨하게 하거나
  입력을 임의 절단해 완료 상태로 만들지 않는다. 실패 attempt와 원응답을 보존했다.
- 후속: 보존된 응답을 대상으로 값이 아닌 검증 경로·오류 유형만 추출하여 정책/출력 계약
  불일치를 분석하고, 입력 크기·프롬프트 거부 조건을 별도로 재현한다. 정책 변경이 필요하면
  새 버전과 새 참조 실행으로 검증하며 기존 실패나 품질 상태를 소급 변경하지 않는다.

## lifecycle projection의 Protocol 요구 메서드와 구현 불일치

- 2026-09-08 회사 핏 구현의 전체·집중 회귀에서도 같은 2개가 재현됐다. 이번 변경의
  회사 핏/설정/슬롯/경계 74개와 PostgreSQL 집중 44개는 통과했으며, 기존 Protocol 공백은
  별도 수정 대상으로 유지한다([검증 기록](../../validation-runs/20260908-prespec-company-fit.md)).
- 확인: 2026-09-07 전체 백엔드 검사에서 1,528 통과·2 실패·5 skip. 실패 2건만
  다시 실행해 동일하게 재현했다.
- 실패: `tests/deep_review/test_prespec_projection.py::test_projection_satisfies_the_lifecycle_protocol`,
  `tests/screening/test_projection.py::test_projection_and_hook_satisfy_the_lifecycle_protocols`.
- 원인: 개요 구현에 `notice_ids_for_auto_preparation_status`, 판정 구현에
  `notice_ids_with_open_blocking_items`·`open_blocking_item_counts`가 없다.
  Protocol, 두 구현, 두 검사 파일은 작업 전 HEAD와 동일하다.
- 영향: runtime Protocol 적합성 검사가 실패하며 관련 필터·blocking 집계 제공 계약을
  완전히 충족한다고 말할 수 없다. 이번 수집·기본 목록 HTTP 검증은 통과했다.
- 범위: 기간 수집과 참조 실행 중 발견한 기존 기능 계약 공백이다. 빈 값을 반환하는
  메서드로 감추지 않고, 각 모듈의 정본 조회·필터 동작을 구현하는 별도 변경에서
  실제 데이터 기반 회귀와 함께 해결한다.

## Qwen v5 실표본4건이 모두 결정적 검사에서 종료된다 (2026-09-11, 미완료)

- 재현/범위: 승인된744·749·759·761의 고정 전체 선택 원문과 v5 binding으로 실제 Qwen 초안을 각1회 받았다. 네 응답 모두 파싱되며 형식 재생성·timeout·용량 초과는 없었다. 결정적 검사에서 모두 needs_human_review, semantic0·최종 개요0이다. 실행 증거 (`../../.dryforge/prespec-qwen-0911-mHF0bO/README.md`, 실행 당시 로컬 산출물·현재 checkout 없음).
- 관측: 744·749·761의8개 주장 모두 business_overview로 분류되어 필수 main_tasks가 없다. 759는 두 필수 섹션이 있지만 수치 metadata/단위, 분석 전제 및 unknown 사유 검사가 실패했다. 전체32주장 중 결정적15 통과/17 실패이며 의미 검토 전이므로 통과15도 최종 검증 문장이 아니다. 수치·단위·관계·날짜 대조 오류 코드는 실제 사실 오류와 검증기 과탐을 구별한 사람 판정이 아니다.
- 종결(2026-09-11): 이 관측은 policy v5·`bidops.prespec-overview-claims.v1`(8개 주장 상한 포함)·
  activation v2·call ledger 스택 전체를 대상으로 한다. [ADR-0054](../decisions/0054-prespec-overview-mvp-rewrite.md)로
  이 스택을 삭제하고 정책 v6(`max_claims 12`)로 다시 썼으므로, 여기 기록된 8/32주장 비율과
  실패 사유 개수는 새 스택에 그대로 적용되지 않는다. 새 실행 결과는 별도 참조 실행으로
  다시 측정한다. 이 항목은 해당 스택 폐기로 종결한다.

## 개요 worker의 claim 루프가 재시도 상한을 무시한다 (2026-09-16, 코드 수정 진행 중)

- 재현: 운영 `work_job`에서 `max_attempts=3`인 개요 job의 `attempt_count`가
  205(실행 중)·321(9/15 `lease_expired` 실패). 대기 38건이 처리되지 않았다.
- 원인: `overview_runs._claim_next`가 claim 시 `attempt_count`를 올리고,
  `verify_identity()` 실패를 `_release`로 `queued`에 되돌리며 카운터·상한을 보지
  않는다. `max_attempts`는 `work_job` 경로 어디서도 읽히지 않고
  `deep_reviews.claim_next_job`의 만료 reclaim도 같다. 사람이 run을 닫는
  REST·CLI가 없다.
- 영향: 모델 endpoint가 죽어 있으면 한 작업이 1초 poll마다 재점유돼 대기열
  머리를 영구히 막는다.
- 후속: 브랜치 `feat/overview-claim-guard`가 상한 게이트·`_release` 복원·identity
  backoff·`close-overview-run` CLI를 추가한다.

## 회사 핏은 심층 검토를 막는데 품질을 잴 장치가 없다 (2026-09-18, 미해결)

- 재현 조건: `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED=true`(기본 false, `web/backend/app/core/config.py:197`)와
  참조 실행 모드에서 사전규격 개요가 `completed`인 공고의 회사 핏 결과가 `matched`가 아니면
  `web/backend/app/deep_review/services/company_fit.py:272-273`이 `company_fit_<decision>` 사유를 내고,
  `web/backend/app/deep_review/services/auto_preparation.py:460-461`이 그 사유로 심층 검토 자동 시작을 막는다.
  회사 핏 시도 table의 `quality_status`는 CHECK로 `unmeasured_reference`·`mock_reference`만 허용한다
  (`web/backend/app/deep_review/models.py:1723`). 회사 핏에는 gold·임계값·활성화 게이트가 없다.
- 영향: 모델 출력이 사람 눈에 닿기 전에 다음 단계를 막는 지점인데, 떨어진 건이 맞게 떨어졌는지 잴 방법이 없다.
  `quality_status`가 `measured`가 될 수 없는 구조라 측정을 해도 기록할 자리가 없다. 핏에서 떨어진 공고도 목록에는
  남으므로 C-2 탈락보다는 피해가 작다. 지금은 기본 비활성이고, 켜도 참조 실행 모드가 아니면
  `company_fit_reference_only`로 닫히므로(`company_fit.py:245-246`) 운영에 닿지 않는다.
- 지금 해결할 수 없는 이유: 일일 운영 고도화 계획은 C-2 게이트만 구현하고 C-2 밖의 품질 장치는 지도와 선행조건만
  기록하기로 했다([`0918_daily-operation/intent.md` §6](../../0918_daily-operation/intent.md) 결정 26). 회사 핏 gold를
  만들 표본과 사람 정답이 아직 없고 임계값은 사람 결정이다.
- 후속 방향: 회사 핏을 운영에서 켜기 전에 게이트를 먼저 만든다(별도 계획). C-2 게이트 구조 — 승인된 사람 gold,
  NULL이면 `미측정`인 임계값, 같은 묶음 2 pass, append-only evaluation — 를 다시 쓸 수 있다. `quality_status` CHECK에
  측정값을 담을 자리를 함께 설계한다.

## 사전규격 개요는 운영 중인데 표본 점검 라벨을 담을 자리가 없다 (2026-09-18, 미해결)

- 재현 조건: 운영의 web·분석 워커·첨부 워커는 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`로 개요를 자동으로 돌린다
  (2026-09-18 컨테이너 확인). 개요 run의 `quality_status`는 항상 `unmeasured_reference`(모델명이 `mock`이면
  `mock_reference`)다(`web/backend/app/deep_review/services/overview_runs.py:481-483`). 개요 결과에 사람이 정답·오답을
  다는 table·REST가 없다 — 개요의 쓰기 REST는 쪽 범위 확정(`POST /api/pre-specs/{notice_id}/overview/range-confirmations`,
  `web/backend/app/deep_review/routers/overviews.py:91`)뿐이다. 수량·날짜 불일치 일부(`quantity_mismatch`·
  `quantity_metadata_mismatch`·`quantity_relation_ambiguous`·`quantity_unit_missing`·`date_mismatch` 등)는 실패가 아니라
  경고로 분류된다(`web/backend/app/deep_review/services/prespec_overview_claim_validation.py:37-49`).
- 영향: 개요는 건을 거르지 않는다 — 대상은 나라장터 SW 대상 표시로 정해지고 모델 판단이 아니다
  (`web/backend/app/deep_review/services/effective_grade.py:135-169`). 인용문·쪽수를 원문과 대조하는 결정적 검증이 있고
  실패하면 `needs_human_review`다. 그러나 경고로 완화된 수량·날짜 불일치가 담당자에게 얼마나 자주 틀린 정보로
  닿는지 셀 방법이 없고, 품질 표식이 참조 표식에서 벗어날 근거도 쌓이지 않는다.
- 지금 해결할 수 없는 이유: 사람이 근거와 함께 읽는 지점이라 정식 게이트보다 표본 점검이 맞다고 판단했지만
  ([`0918_daily-operation/intent.md` §6](../../0918_daily-operation/intent.md)), 라벨 축·저장 table·REST·화면을 새로
  설계해야 하고 일일 운영 고도화 계획은 C-2만 구현한다(결정 26).
- 후속 방향: 별도 계획으로 개요 run 단위의 표본 점검 라벨(주장별 맞음·틀림·원문 없음 등)을 append-only로 담을 자리를
  만들고, 경고 코드별 발생률과 라벨을 대조해 경고로 둘지 실패로 올릴지 다시 정한다. 라벨이 쌓이기 전까지
  `unmeasured_reference`를 측정으로 승격시키지 않는다.

## 개요 완료→심층검토의 실행 상태와 실무자 동선 불일치 (2026-09-22, 미해결)

현재 작업 트리(기존 narrative-v2 미커밋 변경 포함)와 실행 중인 서버의 읽기 전용 REST를
점검했다. 새 모델 호출·재시도·설정 변경·배포는 수행하지 않았다. 운영 관측은 조회 시점의
사전규격 기본 목록 145건이며, 전체 DB나 모든 과거 실행의 성공률을 뜻하지 않는다.

- **자동 실행은 현재 꺼진 회사 핏 게이트에서 멈춘다.** web·analysis-worker 모두
  `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED=false`, 개요 enabled와 reference mode는 true다.
  목록 52건은 `company_fit_disabled`로 클릭 대기다. 이는 설정에 따른 정상 차단이며
  자동 종단 흐름을 실증했다는 근거가 아니다. PoC에서 자동 실행을 시험할 범위와 기존
  회사 핏 게이트의 역할을 결정해야 하므로 이번 점검에서 켜지 않았다.
- **개요 완료와 자동화용 검증 완료의 안내가 충돌한다.** 목록 6건은 개요 `completed`와
  `overview_not_completed`를 동시에 반환한다(예: notice 1485).
  `overview_runs.automation_completed_result`는 legacy `checks.overall=passed` 또는
  새 계약의 전체 개요 의미 검증 통과를 추가로 요구한다. 화면의
  `preSpecAutoPreparation.ts`는 이를 “개요 run이 completed가 아닙니다”로 번역한다.
  실제 미완료와 검증 조건 부족을 구별하고 수동 실행 가능 여부를 함께 안내해야 한다.
- **심층검토가 존재하기만 하면 자동 시작됨으로 보인다.**
  `auto_preparation._status_for`는 생성 주체·현재 attempt 상태·현재 묶음과의 일치 여부를
  보지 않고 review ID만 있으면 `deep_review_started`를 반환한다.
  `PreSpecDetailPage`는 이를 완료 단계 표시와 “자동 시작된 … 보고서 열기”에 사용한다.
  실제 조회된 notice 1443·1430·1428의 최신 심층검토는 모두 `failed`인데 이 상태였다.
  1430·1428은 `validation_failed`, 1443은 current attempt 오류 코드가 null이다.
  생성 주체, 실행 상태, 입력 현재성을 분리하고 실패 복구를 상세에서 바로 안내해야 한다.
- **수동 진입 버튼이 접힌 패널을 열지 않는다.** 상세의 클릭 대기 링크는
  `href="#document-preparation"`뿐이고 대상은 `documentPanelOpen`일 때만 mount된다.
  패널을 닫은 뒤 링크를 누르면 시작 폼으로 갈 수 없다. 또한 문서 준비 패널은
  “우선 검토가 아니면 거부”라고 안내하지만 서버는 개요 플래그가 켜진 사전규격의
  `SW사업대상=Y`도 허용한다. 시작 동선과 자격 안내를 서버 계약에 맞춰야 한다.
- **개요 범위 조정이 항상 필수 작업처럼 노출된다.** 상세는 `range_review`가 있으면
  패널 밖에 항상 폼을 표시한다. 자동 선택 ready도 사람 confirmation이 없으면
  `RangeReviewPending`이며, 서버 `can_confirm`은 활성 개요 run 부재와 snapshot 안전성을
  본다. 개요 완료는 편집을 막지 않고 확정은 새 개요 run을 enqueue한다.
  정상 완료는 읽기 요약과 선택적 “범위 변경 후 개요 다시 실행”, 범위 미확정은 펼친
  필수 조치로 나누는 것이 필요하다. 실행 중에는 실제 입력/확정이 잠기므로 항상
  제출 가능한 버튼이라는 뜻은 아니다.
- **개요에서 심층검토로 전달되는 데이터의 설명이 필요하다.** 개요 결과는 회사 핏과
  자동 시작 판단에 쓰이며, 심층 실행 `DeepReviewService.run_claim`은 고정 묶음의 원문
  구조·프로필·정책을 읽는다. 개요 결과나 overview run ID를 분석 입력으로 넘기지 않는다.
  수동 `create_review`는 개요 완료·회사 핏을 요구하지 않는다. 원문 전체를 독립 분석하는
  설계 자체는 타당하지만, 개요 요약을 이어받는 것으로 설명해서는 안 된다.
  `business-rules.md`의 “구조화 결과가 심층 검토 입력의 참고 자료” 문장과 구현의
  관계 및 개요/심층 문서 버전 연결 계약은 후속 정리가 필요하다.

이번 요청은 점검이므로 위 제품 동작·계약은 수정하지 않았다. PoC 개선 우선순위는
실행 상태·다음 행동의 정확한 표시 → 수동 시작 동선 → 범위 재실행의 선택적 노출 →
자동 실행 실증 조건과 개요/심층 입력 연결 계약 확정이다.

검증:

- backend에서 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false BIDOPS_DATABASE_URL=sqlite:///:memory:
  .venv/bin/pytest -q tests/app/test_auto_deep_review_start.py tests/app/test_deep_reviews.py
  tests/deep_review/test_company_fit.py tests/deep_review/test_overview_runs.py
  tests/app/test_narrative_review.py`: **165 passed, 11 failed, 7 skipped**.
  실패 11건은 자동 시작 fixture가 완료 run에 `checks_json`을 넣지 않아 새 자동화 검증에서
  `overview_not_completed`로 막힌다. 테스트와 제품 계약 불일치이며 자동 경로 정상 증거로
  처리하지 않았다. 회사 핏 검사 일부는 생성 service를 fake로 바꾸므로 이 공백을 대신하지
  못한다. PostgreSQL 7건은 격리 PostgreSQL URL 미지정으로 skip했다.
- frontend production build 통과. 분리 preview(4197, `/tmp/bidops-flow-audit-dist`)에서
  `playwright test --project=app page-overview.spec.ts document-preparation.spec.ts
  deep-review.spec.ts narrative-report.spec.ts --workers=4`: **52 passed**.
  API mock이며 관련 1280/1440 사례, 수동 요청, 범위 확정, 오류·재시도·초안 보호를 포함한다.
  생성된 1280 보고서 캡처도 확인했다. 실제 모델→보고서 종단 성공이나 운영 데이터의
  의미 정확도를 증명하지 않는다. 테스트가 현재 동작을 기대하므로 위 UX 문제는 남는다.

## 2026-09-22 심층검토 고도화의 처리 범위


이번 심층검토 점검 사항은 새 선택형 `narrative-v2` 경로에서 입력 관련도 선택·공유 근거 보존·전체 종합·명시적 절/역할·본문 전량 보존·실제 검증 집계로 보완했다. 이전 보고서 읽기와 초안 보호도 제품 코드에 반영했다. [구현 기록](../../0922_deep-review-improvement/plan.md). 이후 사용자 요청으로 운영에 적용해 실제 참조 검증을 진행했다([실행 기록](../../validation-runs/20260922-narrative-review/live-validation.md)). v1 생성 경로와 저장 결과는 그대로이므로 기존 형식의 문제까지 해결 완료로 닫지 않는다. 회사 자료 선택의 의미 회수율, 큰 원문/예외의 누락, 문서 기준 최신성, 실제 사용성은 후속 평가로 남는다.
