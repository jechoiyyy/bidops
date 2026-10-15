# HP-06 사람 작성 자료·채점 준비 (정답·인수 미작성)

> 승인 전 제안과 준비 경과 기록이다. 현재 실행 계약·결정 상태는 [intent](intent.md)·[spec](spec.md)·[plan](plan.md)을 따른다.

Git 밖 `.../.sdlc/local-runtime/hp-preparation-20261015/human-worksheet.blank.v3.json`에 실제 5문서·198카드의 제목/원문 표 셀/block locator/출처 hash/쪽 상태만 넣었다. 모델 답, concept 추천, 적합성 추천, 차단 추천은 없다. 판정·차단·충족·부족·주의·카드상태·작성자·회사hash·ontologyhash는 빈칸이다. 카드상태10개는 사람이 선택해야 하며 임의10개를 정답 표본으로 확정하지 않았다. 110카드의 쪽은 미확인으로 남는다.

현재 평가 표본은 세종 교육포털 교체를 반영한10사례로 선택·원문 해시 동결 완료다. 회사·전체 온톨로지 동결과 사람 정답 작성은 아직이다. 아래 최신 선택 확정 기록을 따른다.

준비 도구 [hp_prepare.py](../../preparation/hp_prepare.py):

- `blank-gold cards.json --out <Git밖 새 파일>`: 입력 whitelist로 source-only 자료 생성, 정답은 null. 기존 파일 덮어쓰기 금지.
- `gold-check gold.json --out check.json`: 10문서, source/company/ontology hash, 사람 작성 표식·시각·모델출력 전 작성 선언, 판정 enum, 개수 제한 없는 충족/부족 source unit ID, 서로 모순 없는 카드10상태, 차단조건 ID/문장/근거를 검사. 빈 자료는 exit2. 사람의 실제 작성 시점을 도구가 증명하는 것은 아니므로 감사 기록과 함께 확인한다.
- `score gold.json predictions.json --out score.json`: 문서집합·출처·회사/온톨로지 binding 일치, 누락·중복 ID 차단. 판정 일치율, 차단 조건 recall, 충족/부족 reference precision(모델이 제시한 항목 수가 분모), 카드상태 일치율·불일치 ID를 반환. 분모0은 null. 입력파일+도구 SHA로 scoring_input_sha256을 고정한다. 자동 인수 결과는 항상 not_decided다.

초안 JSON 형식은 blind pack과 도구의 `check_gold`가 정본이다. gold의 `status=human_completed`와 작성자/시간/모델출력전 선언은 사람이 실제 작성 후 넣는다. source_cards를 임의 수정하지 말고 별도 원본 pack의 hash와 대조한다. 회사·온톨로지·표본 선택 이후 정식 JSONSchema와 서명/동결 manifest를 HP06 spec에서 고정한다.

prediction 초안은 `{company_sha256,ontology_sha256,documents:[{document_id,source_sha256,verdict,blocking_condition_ids,met:[unit_id...],gap:[unit_id...],card_states:[{unit_id,status}]}]}`. 원본 모델 출력을 그대로 이 형식이라고 가정하지 않는다. 제품 export와 사람의 condition ID alignment가 필요하다. 자유 문장은 fuzzy matching으로 같다고 채점하지 않는다. 새로운/미일치 차단조건은 사람 판정 대기 목록에 남긴다.

**참조 정답의 한계**: 사람이 확인한 항목만 기록하며 각각5개 필수 조건은 폐기했다(2026-10-15 승인). 정답 집합이 전수라는 보장은 없으므로 모델의 비일치 항목을 곧바로 오답으로 확정하지 않는다. `unmatched_met_need_human_adjudication`·`unmatched_gap_need_human_adjudication`을 모델오류/gold누락/해석차이로 사람이 검토한다. 도구가 정답을 보충하지 않는다. 미작성은 null이고 사람이 확인한 뒤 해당 항목이 없으면 []로 적는다. 빈 모델 제시 목록의 precision 분모는0/value=null이며 통과로 처리하지 않는다.

D7은 2026-10-15 확정됐다: 종합 판정8/10 이상·차단조건recall0.8 이상·카드일치0.7 이상·명백한 필수자격 미충족을 충족으로 판단한 사례0건. met/gap precision은 수치 문턱 없이 측정·불일치 사람 검토한다. 사람 gold 동결 → 모델10건 입력/중단조건 계획 승인 → 실제 실행 → 제품밖 채점 → 불일치 사람검토 → 최종 인수 순서다. 이번에는 모델10건 실행과 품질/인수 판단을 하지 않았다.


## 공동 검토 결정 — 2026-10-15

사용자가 직전 작성 방식 제안에 “진행해”로 승인했다. 회사·용어 기준 동결 후 모델 출력을 보기 전에 사람이 작성한다. 최종10문서를 평가하며 현재 준비된5문서부터 작성하고 나머지를 보충한다. 종합 판정·참여를 막는 조건·충족/부족 근거·주의·카드10상태를 작성한다. 충족/부족은 각각5개를 강제하지 않고 확인된 항목만 기록한다. 불일치는 모델오류/사람정답누락/해석차이로 함께 검토한다. 통과 점수는 모델 실행 전 별도 확정하며 이번 승인은 점수나 실제 정답 승인으로 확대하지 않는다.

준비 스키마를 `bidops.hp-human-gold-preparation.v2`, 채점 출력을 `bidops.hp-preparation-score.v2`로 올렸다. 기존 v1 작성자료·채점 결과는 수정하지 않는다. 새 도구는 v1 gold를 명시적으로 거부하며 필요하면 사람이 검토한 새 버전으로 옮긴다. 기존 정책·제품 API는 변경하지 않았다.

검증: 관련 준비 도구16검사 통과(가변 개수·빈 목록의 null 지표·미작성 null 거부·중복/외부 ID 거부 포함). 5문서198카드 새 빈 양식 생성, 기존 source_cards 동일·정답 null 유지 확인. 제품 테스트·모델 실행·사람 정답 작성은 하지 않았다. 최종 gold-check의10문서 요건은 유지하므로 처음5문서 작성만으로 최종 인수를 통과하지 않는다.


## 품질 기준 확정 — 2026-10-15

사용자 “확정해”에 따라 [acceptance-criteria.approved.v1.json](../../preparation/acceptance-criteria.approved.v1.json)에 네 기준을 고정했다. 기준 승인과 실제 품질 통과는 별개다. 최종10문서에서 종합판정8건 이상 일치, 사람이 표시한 차단조건의80% 이상 발견, 카드상태70% 이상 일치, 명백한 필수자격 미충족을 충족으로 판정한 사례0건을 요구한다. 초기 데모 인수 후보 기준이며 운영 품질 보증이 아니다.

집계 구현은 문서별 수치와 전체 micro 합계를 함께 내며 차단조건은 전체 정답 조건 수, 카드상태는 문서별10개 표본의 전체 수를 분모로 쓴다. 분모0은 unmeasured이며 pass로 만들지 않는다. 충족/부족 reference precision과 비일치 목록도 제공하되 사람 정답 누락/해석 차이를 사람이 검토해야 한다. 중대한 오류의 존재 여부는 사람 검토 전 null/pending으로 남기며 자동으로0을 기입하지 않는다.

채점 출력은 `bidops.hp-preparation-score.v3`이다. candidate_assessment는 숫자 기준 pass/fail/unmeasured와 중대한 오류 검토 대기를 분리하고 acceptance는 항상 not_decided로 둔다. 기준 파일 hash도 scoring_input_sha256에 결합한다. 새 도구를 실행하지 않은 기존 증거의 tool hash는 소급 수정하지 않는다. 사람 검토 결과와 최종 인수는 입력·결과 hash를 연결한 별도 기록으로 남긴다.

검증: 관련 준비 도구19검사 통과. 8/10·80%·70% 경계값과 각각 직전 미달, 분모0, 5건으로10건 기준 통과 불가, 사람 검토 미완료 시 자동 인수 금지를 확인했다. 실제 모델 결과·사람 gold는 아직 없고 합성 검사만 실행했다.

기준 파일 SHA256: `e7148fb47dc283f90a03d0c36b15c152311a570dfd2ece99e722e1e1348c760c`.


## 평가 문서 후보 선정 — 2026-10-15

사용자가 기존5건 포함·구축/운영 범위 다양화 기준을 승인했다. [후보10건](../../preparation/evaluation-documents.candidates.v1.json)은 최종 표본 승인이나 사람 정답이 아니다. 기존 수집 목록179건에서 제목·첨부 메타데이터로 선정했으며 모델 판정은 선정 기준으로 쓰지 않았다.

| notice | 추가 추천 | 범위(제목 기준) |
|---|---|---|
| 151 | 수원 국제회의복합지구 플랫폼(웹사이트) 구축 | 웹사이트 신규 구축 |
| 57 | 2027년 대전광역시 누리집 기능개선 및 유지관리 사업 | 누리집 기능개선 |
| 129 | 국가데이터처 업무포털(UBIS) 및 홈페이지 유지관리(2027) | 업무포털 결합 |
| 156 | 2027년 교육저작권지원센터 홈페이지, 폰트점검 프로그램 운영 및 유지관리 | 폰트점검 프로그램 결합 |
| 116 | 국가슈퍼컴퓨팅센터 홈페이지/정보관리시스템 유지보수 및 운영관리 | 연구정보시스템 결합 |

추가5건은 원문 취득·변환·카드 검증 전이다. 제목에서 추론한 범위는 원문에서 RFP 여부·중복과 함께 확인해야 한다. notice79는 기존 학교 웹호스팅과 같은 사업 가능성으로 제외했다. 대안은 통합누리집158·옴부즈만46·교육포털73이다. 후보 조합 검토 후 원문 준비·중복 확인, 최종10건 source hash 동결, 회사·온톨로지 동결과 연결, source-only 작성자료 발행 순으로 진행한다. 이번에는 다운로드 작업 생성·변환·모델 호출·사람 정답 작성을 하지 않았다.

## 원문 준비와 다중 첨부 계약 보완 — 2026-10-15

후속 “계속 진행해”에 따라 기존 제품의 allowlist/DNS 고정/크기·시간 제한을 가진 ProviderConnector로 추가5건의 첨부6개를 취득했다. bidops-local ClamAV에서 정확한 바이트의 clean·SHA를 확인한 뒤 네트워크 없는 local document-worker의 기존 process_document로 변환했다. DB 작업 생성·자동 분석·정책 변경·모델 전송 없이 Git 밖 전용 디렉터리에0600으로 저장했다.

- 수원151: 과업지시서43카드+제안요청서0카드. 과업지시서 paragraph-1-44~49의 CMS 구축·클라우드 홈페이지 범위 확인. 같은 사업의 두 파일을 하나의 평가 사례로 묶고 평가·제안 절차 원문도 보존한다.
- 대전57:76카드. paragraph-1-64~71에서 신규 사이트와 기능개선·운영 범위 확인.
- 국가데이터처129:102카드. paragraph-1-69~76의 UBIS·행정지원시스템 운영 범위 확인.
- 교육저작권156:79카드. paragraph-1-25~32에서 홈페이지·폰트점검·통합관리·통계조회 범위 확인.
- 국가슈퍼컴퓨팅센터116: 원문 취득·악성코드 검사 통과, `hwpx_verify_failed`로 구조 변환 차단. 원본 보존, 검증 우회·변환 성공 처리 없음.
- 교체안 교육포털73:43카드. 세종교육청교육원 사업으로 기존 서울교육청 학교 웹호스팅과 다른 기관·사업이며 원본 해시도 다르다. 다만 학교 누리집 운영 범위는 겹친다. 연구정보시스템 평가 폭이 줄어드는 교체안이며 사용자 선택은 아직이다.

현재 [후보 v2](../../preparation/evaluation-documents.candidates.v2.json)는 원래 후보와 차단·교체안을 구분한다. 원래9건+교육포털 교체안을 대상으로 **10사례·11원문·541카드**의 검토용 묶음을 준비했다. 상속312·쪽미확인229이며 정확히 mapped인 카드는0이다. 다중 파일 해시11개 고유성, 기존5개 원본 hash 불변, 카드별 근거·원문 위치와 빈 정답을 검사했다. 다른 기관·사업으로 구별했으나 공통 과업/서식 유사성까지 제거한 독립 표본이나 대표성을 보증하지 않는다.

Git 밖 `hp-evaluation-20261015/index.html`은 원본·PDF·전체 텍스트/block 위치 자료 색인이다. `cards.candidate10.v1.json`과 `human-worksheet.blank.candidate10.v1.json`에는 모델 답·추천 판정이 없다. 모든 사업 판정·차단조건·충족/부족·카드10상태는 미작성이다. 회사·온톨로지 hash도 미확정 상태다. artifact-manifest.json이 경로와 hash를 연결한다.

준비 도구 계약은 cards **v2**, blank/gold **v3**, score **v4**다. sources.json의 각 사례는 기본 원문과 선택적 companions를 가진다. source_documents는 각 원문의 source/structure/page_map SHA와 원문 block을 보존하고 sources_sha256은 정렬한 원문 묶음의 세 hash를 결속한다. prediction도 사례별 sources_sha256을 제출해야 하며 별도 첨부 누락·변경을 거부한다. 카드 밖 참가자격 등은 `block:<source_sha>:<block_key>` 근거로 차단/충족/부족에 연결할 수 있다. 카드상태10개는 여전히 실제 카드 ID만 허용한다. 이전 v1/v2 gold는 새 도구에서 거부하며 옛 자료는 덮어쓰지 않는다. 원문 텍스트가 실제 근거를 뒷받침하는지는 사람이 확인해야 한다.

검증: 관련23검사 통과(별도 첨부 근거·묶음 hash 불일치·외부 block 거부·카드 밖 근거를 카드상태로 사용 금지·구버전 거부·추천 제외 포함). 실제 교체안 자료 생성,10사례 모두 카드10개 이상·원문 hash11개 고유·정답null·빈 gold 거부 확인. `validation.v1.json`은 준비 증거이며 인수/품질 증거가 아니다. 제품 코드·REST·DB 변경이 없어 앱 배포·전체 검증은 하지 않았다.

## 평가 표본 선택 확정 — 2026-10-15

사용자 “대안으로 진행해봐”에 따라 국가슈퍼컴퓨팅센터116을 세종교육포털73으로 교체했다. [확정 표본](../../preparation/evaluation-documents.selected.v1.json)에10사례·11원문 각각의 source/structure/page_map SHA, 사례별 sources_sha256, 기존 카드 묶음·빈 작성자료 SHA를 고정했다. 수원의 두 첨부는 한 사례다. 학교 누리집 운영 범위 일부 중복이라는 한계를 유지한다.

기존 후보·실패 원문·검사·작성자료는 변경하지 않았다. 내용이 동일한 카드541개·상속312·미확인229의 기존 준비 결과를 재사용했다. 읽기 색인은 Git 밖 `hp-evaluation-20261015/index.selected.v1.html`이다. 표본 선택만 확정했으며 기존 빈 정답을 채우거나 회사/온톨로지 미확정 hash를 추정하지 않았다.

검증은 기존 artifact SHA 일치와10개 사례/11개 원문,73포함·116제외, 선택 기록과 자료 연결을 확인했다. 코드 변경이 없어23검사·변환·앱 빌드를 반복하지 않았다. 다음은 전체 concept ID/alias와 승인된 회사 사실의 등록 표현을 동결한 뒤 그 hash로 사람 작성자료를 발행하는 단계다.

## 사람 작성 시작 기준 발행 — 2026-10-15

회사·온톨로지 최종안이 사용자 “확정할게”로 승인되어 [동결 기록](../../preparation/human-gold-inputs.frozen.v1.json)을 발행했다. Git 밖 `hp-evaluation-20261015/human-worksheet.blank.frozen.v1.json`에 company_sha256과 ontology_sha256을 넣었으며10사례 원문·카드·모든 정답 빈칸은 기존 작성자료와 동일하다. 회사 hash는 등록 표현 단독이 아니라 typed scenario까지 연결한 company.evaluation-basis.v1.json 파일 SHA다. 이후 prediction도 같은 값과 사례별 sources_sha256을 사용한다.

`index.frozen.v1.html`에서 고정 회사 사실과 원문/PDF/block을 함께 읽을 수 있다. 사람은 모델 출력 전에 사업별 종합 판정·차단조건·충족/부족·주의, 직접 선택한 카드10상태를 작성하고 실제 작성자/시각을 기록한다. 미작성 null과 확인 후 없음 []를 구분한다. 시작 순서는 기존 폴리텍 → 강원대 → 외교부 → 남양주 → 학교 웹호스팅, 이후 추가5건을 권장한다. 정답이나 예시 판정은 생성하지 않았다.

검증: 승인된 ontology/company parser 통과, 초안 대비 개념·관계/회사 사실 동일, 표본10사례의 source content 동일·근거 집합 유효·정답null 유지, 빈 gold 거부 확인. source 변환·기존23검사·앱 빌드는 변경이 없어 반복하지 않았다. 기존 후보/선택 색인·빈 양식은 불변 보존한다. 실제 gold 완료0건·모델 평가0건이며 최종 인수는 미작성이다.

## 폴리텍 공동 작성 방식 변경 — 2026-10-15

사용자는 참가자격 구간에 대해 “차단 항목도, 추가 확인할 항목도 없다”는 선택2를 답했다. Git 밖 `hp-evaluation-20261015/human-responses/doc1.qualification.v1.json`에 구간 한정 사람 입력으로 기록했으며 회사 미확인 사실이나 전체 사업 판정을 바꾸지 않았다.

이후 “너가 먼저 판단해보고 모호한 부분에 대해서만 나아게 물어봐”로 모델 선검토를 요청했다. 폴리텍27카드 대조를 `assisted-review/doc1.draft.v1.json`에 원문 block 인용과 함께 별도 기록했다. 전체 카드 기준의 임시 판정은 unknown27이며 일부 조건 대응(상주 인원 상한·CMS/접근성 경험)을 전체 충족으로 올리지 않았다. 일반 계약 의무의 수용/이행 계획 없이 충족으로 볼지에 대한 업무 기준만 질문한다. 모델이 고른10카드는 제안 표본이며 사람이 선택한 것으로 기록하지 않는다.

이 문서에서 모델 판정을 본 뒤 작성하는 응답은 model-assisted review이며 `written_before_model_output=false`, 독립 blind gold 자격 없음이다. 기존 gold-check의 모델출력 전 작성 게이트를 완화하지 않았고 동결 빈 양식·입력·기존 사람 응답은 보존했다. 폴리텍을 포함하는 기존10건의 독립 gold 완료/통과를 주장하지 않는다. 이후 독립 평가를 유지하려면 모델 결과를 보지 않은 평가자가 해당 문서를 작성하거나 표본을 별도 변경해야 한다. 다른 문서는 이번에 모델 판정을 생성하지 않았다.

## 회사 v2 수행 범위 확정 — 2026-10-15

사용자 “확정해”로 가상3실적의 명시 담당 범위와 표준 수행 절차를 승인했다. [회사 v2](../../preparation/company.experience.approved.v2.json), [평가 기준 v2](../../preparation/company.evaluation-basis.v2.json), [입력 동결 v2](../../preparation/review-inputs.frozen.v2.json)를 발행했다. 기존14사실의 값/단위/상태와 현재 조건은 동일하다. self 참조는 새 retained_facts 경로로 맞추고, 기존 ‘사업명 미지정’ 설명만 새 가상명·담당 범위 연결로 정리했다. 개별 날짜·금액·실제 완료 증거는 null이다.

v2 company_sha256은 company.evaluation-basis.v2.json 파일 SHA다. 이 기준은 승인된 실적 원본과 기존 ontology를 결속하며, v2 등록 projection은 pending이므로 registration_file=null이다. v1 등록 JSON을 v2 제품 데이터로 표시하지 않는다. DB 등록·제품 대조 연결은 별도 미구현이다.

Git 밖 `hp-evaluation-20261015/index.company-v2.html`과 `assisted-review.worksheet.blank.v2.json`은 v2 기준의 공동 검토 자료다. 원문10사례·11파일·541카드와 정답 빈칸은 그대로이며 company hash만 새 기준으로 연결했다. 폴리텍 초안 노출로 written_before_model_output=false를 명시해 독립 gold와 구분한다. v1 사람 응답·모델 초안은 자동 이관하지 않았다. 기존 gold-check 게이트·인수 기준은 유지한다.

검증: 승인 범위·미확인 값 보존,14사실 값 동일, self 참조와 인용 일치,10사례 원문/카드 동일 확인. 자료·문서 변경뿐이므로 변환/앱 테스트를 반복하지 않았다.
