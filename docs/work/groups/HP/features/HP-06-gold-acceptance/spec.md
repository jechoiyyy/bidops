# HP-06 — spec

근거: intent.md, HP 공통 계약 §9, acceptance-criteria.approved.v1.json, review-inputs.frozen.v2.json. 독립 정답을 모델 보조 검토와 섞지 않는다.

## 정본·계약

선정10사업·11원문·541카드는 evaluation-documents.selected.v1.json 및 외부 hp-evaluation-20261015의 동결 source bundle을 따른다. 모든 준비 양식은 model 답/추천판정 없이 원문 위치·회사 v2 승인 사실만 담는다. 기존 assisted-review/doc1.draft.v1.json과 qualification 응답은 역사 기록이며 v2 독립 정답에 자동복사하지 않는다.

기존 hp_prepare.py의 `bidops.hp-human-gold-preparation.v3` 및 score v4 계약을 정본으로 재사용한다. 정확 schema_version은 도구 상수/blank-gold 출력과 일치시킨다. 정답키·필수값·CLI 옵션은 해당 함수/CLI를 유지하고 새로운 호환되지 않는 동일버전 포맷을 만들지 않는다. 새 스키마가 필요한 경우 새 버전+명시적 소비자 변환만 허용한다.

공통 binding: company_sha256=company.evaluation-basis.v2.json bytes SHA, ontology_sha256=parser canonical SHA, sources_sha256=정렬된 source/structure/page_map hash 목록 canonical SHA. DB graph SHA를 company_sha256에 대신 쓰지 않는다. HP03의 registry binding이 이를 실제 attempt provenance와 연결해야 채점 가능하다.

status="human_completed", written_before_model_output=true, annotator/작성시각, 문서10건, 각 문서 verdict(HP03 4값), blocking_conditions, met/gap, cautions, 정확히10개의 서로 다른 card ID+met/gap/unknown을 사람이 채운다. 미작성 null과 확인 후 없음[]은 다르다. met/gap 개수 강제 없음. 카드 상태에는 card ID만, 조건 근거에는 카드 또는 block ID 허용. foreign source/block·중복·met/gap 중첩·binding불일치는 거부한다. 정답을 바꾸면 새 버전 디렉터리+SHA, 옛 버전 불변.

현재 폴리텍의 모델 초안 노출로 기존 작성자는 이 문서를 blind gold로 작성할 수 없다. 독립 평가 착수 전에 (A) 모델 답 미노출 평가자가 동일10건 작성 또는 (B) 별도 미노출 holdout을 사용자와 선정해 새 selection/company binding 양식 생성 중 결정한다. 권장 A는 기존 선정·자료 재사용, B는 새 표본 준비가 필요하다. 회사 조건·독립성 기준을 바꿔 우회하지 않는다. 기존 공동 검토는 written_before_model_output=false로 유지한다.

모델 출력은 별도 actual 파일: 같은 doc ID·company/ontology/source binding, attempt ID·정책·모델 identity·도구SHA 및 각 unit 결과를 HP03 출력에서 adapter로 변환한다. 기존 scorer가 요구하는 정확필드로 변환하되 원본 모델 결과를 수정하지 않는다. actual에서 요구사항 ID만으로 매칭하지 않고 source를 포함한 card ID를 쓴다. partial/failed/mock/reference 구분을 보존하며 incomplete는 완전한 측정 대상이 아니다. reference를 운영 measured로 올리지 않는다.

## 측정과 사람 판정

기존 gold-check 후 score. 판정 일치≥8/10, blocking micro recall≥0.8, 카드상태 micro accuracy≥0.7, 명백한 필수자격 미충족을 met로 판정한 사례0건. 마지막 지표는 사람이 원문·모델을 읽고 작성하며 미작성null은0이 아니다. met/gap reference precision은 측정하되 unmatched는 사람이 검토하고 수치 임계값 없음. 분모0은unmeasured, 자동 통과 금지. 불일치 분류 enum=model_error|gold_omission|interpretation_difference, actor/reason/source IDs 필수. gold_omission 수정도 새 정답 버전이며 측정 뒤 수정 사실을 보고한다.

인수 기록은 criteria_sha256, gold_sha256, actual_sha256, scoring_tool_sha256, scoring_input_sha256, metrics, adjudication_file_sha256, decision=accept|reject|defer|null, decided_by/decided_at/reason(null허용)을 갖는 새 외부 artifact다. 도구는 decision=null만 생성한다. 사람 인수 전 HP06 done 금지. 기존 참조실행/초안/자료 준비는 품질 완료 증거가 아니다.

## 인터페이스·저장

준비 도구의 blank-gold/gold-check/score를 유지하고 신규 `scripts/hp-export-evaluation.py --attempts <manifest> --out <새파일>`에서 HP03 결과를 읽기 전용 export한다. 새 CLI는 성공0/잘못된 입력2/서비스오류1, 불완전attempt·hash불일치·외부경로 거부. 실제 REST 읽기는 approved bidops-local만, 모델실행 없음. 원문·사람답·모델답·보고서는 Git 밖 `.sdlc/local-runtime/hp-evaluation-<date>/`에 저장, Git에는 비민감 hash와 결과 위치만 남긴다. DB migration·제품 UI·모델 자동전송 N/A.

## 테스트 케이스

| ID | 입력 | 기대 결과 |
|---|---|---|
| T1 | blank/assisted gold/작성자없음/10건미만 | 독립gold로 거부; 실제사람값 자동생성 없음 |
| T2 | foreign block/card·동반첨부·binding변경 | 출처검증·카드상태 제약·입력동일성 |
| T3 | complete/partial/mock·v1회사 attempt export | 명시 분리, v2측정에 불완전/다른binding 사용금지 |
| T4 | 8/10·0.8·0.7경계·분모0·중대오류null | 채점정확·미측정/미판정 보존 |
| T5 | 불일치 분류·gold수정·최종인수null | 새버전·hash추적, 자동승인 없음 |
| T6 | 실제사람10건+승인된실제10attempt | 독립성확인·채점·사람최종결정, 미완료면validating 유지 |

현재 T6 입력은 준비되지 않았다. 이는 loop 전 문서 누락이 아니라 사용자 참여가 필요한 실제 인수 단계다. T1~T5와 도구 구현은 먼저 할 수 있다.

## actual·차단 조건 대응 계약 (독립 리뷰 보완)

기존 gold v3의 human-assigned condition_id와 모델 unit_id는 다른 식별자다. 자동 문자열 교집합을 사용하지 않는다. 새 export는 원시 모델 판단을 먼저 보존하고, 사람이 작성한 alignment를 검증한 뒤 **scorer용 prediction**으로 변환한다. 정답을 모델에 전송하거나 모델이 gold ID를 추측하도록 하지 않는다.

`bidops.hp-evaluation-actual.v1`의 정확 필수 키={schema_version,company_sha256,ontology_sha256,selection_sha256,documents,export_tool_sha256}. documents={document_id,source_sha256,sources_sha256,attempt_id,policy_id,policy_sha256,model,reasoning_effort,cli_version,quality_status,status,verdict,met,gap,card_states,blocking_units,unit_sources,unit_decisions}[]이며 선정10건과 정확히 일치한다. ID UUID/hash는 HP03/04와 동일, quality_status=measured|unmeasured_reference|mock_reference|null, status=completed|failed|running|queued|superseded. verdict=HP03 enum|null. met/gap은 source card 또는 block ID[], card_states={unit_id,status:met|gap|unknown}[], blocking_units는 HP03 mandatory gap unit_id[]. unit_sources={unit_id,source_unit_ids:string[]}[]는 card면 같은 card ID, segment면 그 segment 소유 block ID 전부다. block ID=`block:<source_sha256>:<block_key>`. unit_decisions={unit_id,normalized_requirement,mandatory:bool|null,fit_status:met|gap|unknown,reason_codes:string[],evidence_refs:HP03 Evidence[]}[]는 원본 추출/대조의 유효 값 그대로이며 사람 alignment 검토에 제공한다. 정렬은 frozen unit/source 순서다. 실제 채점은 completed, model/effort/CLI가 고정 HP 정책과 일치, quality_status=unmeasured_reference인 결과만 받는다. mock/null/measured/다른policy는 별도자료로 export 가능하지만 이번 참조 인수 채점에는 거부한다. 실제 quality를 임의 바꾸지 않는다.

`bidops.hp-condition-alignment.v1`={schema_version,gold_sha256,actual_sha256,annotator,authored_at,documents}. documents={document_id,mappings}[], mappings={model_unit_id,gold_condition_ids:string[],reason:string}[]는 blocking_units의 각 ID를 정확히1회 포함한다. source 겹침은 후보 표시일 뿐 자동 동등성 아님. 사람은 원문 조건과 모델 판단을 읽고 같은 조건에만 gold ID를 연결한다. 미매칭은 []+이유, 누락 mapping은 미작성으로 거부한다. gold ID는 같은 문서에 실제 존재하며 그 condition.source_unit_ids와 unit_sources가 하나 이상 교차해야 한다. 복수 ID 연결도 각 조건이 명시적으로 발견됐다는 사람 이유가 필요하다. 모델에 없는 gold 조건은 발견으로 채우지 않는다.

scorer 입력 prediction의 정확 키={company_sha256,ontology_sha256,documents}; documents={document_id,source_sha256,sources_sha256,verdict,met,gap,card_states,blocking_condition_ids}. met/gap/card_states는 validated actual 그대로, blocking_condition_ids는 alignment의 gold ID 합집합(정렬)과 미매칭 모델 조건의 `unmatched:<model_unit_id>` 합집합이다. gold condition ID에 unmatched: 접두어를 예약해 금지한다. 양쪽 집합을 섞지 않으며 scorer의 unmatched 목록에서 false positive를 보존한다. 이후 기존 score 함수로 교집합 recall을 계산한다. alignment가 없으면 raw actual만 출력하고 blocking recall은 채점하지 않는다. actual의 정책/품질/상태·binding 검증은 export CLI가 소유하며 score CLI 직접 입력도 새 wrapper가 검증한 prediction/receipt 없이는 실제 인수 증거로 인정하지 않는다.

CLI는 `--condition-alignment <file>`과 `--gold <file>`을 선택 인수로 받는다. 둘 다 없으면 위 actual만, 둘 다 있고 검증되면 새 출력 디렉터리에 actual/prediction/receipt를 exclusive create한다. 하나만 있으면 입력오류2. receipt={schema_version:"bidops.hp-evaluation-export-receipt.v1",gold_sha256,actual_sha256,alignment_sha256,prediction_sha256,tool_sha256,selection_sha256}. 최종 인수 scoring_input_sha256은 이 receipt와 criteria/tool hash의 canonical SHA로 결속한다. evidence artifact는 원본을 덮어쓰지 않는다.

T3에 wrong policy/quality/attempt state와 source unit 변조를, T5에 arbitrary gold condition ID와 unit ID 차이·false positive·다중조건·alignment 미작성·다른 actual hash를 포함한다. 이 alignment는 결과 후 사람 불일치 검토이며 독립 gold 자체의 선작성 요건을 바꾸지 않는다.
