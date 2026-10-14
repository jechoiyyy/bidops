# HP-06 사람 작성 자료·채점 준비 (정답·인수 미작성)

Git 밖 `.../.sdlc/local-runtime/hp-preparation-20261015/human-worksheet.blank.v2.json`에 실제 5문서·198카드의 제목/원문 표 셀/block locator/출처 hash/쪽 상태만 넣었다. 모델 답, concept 추천, 적합성 추천, 차단 추천은 없다. 판정·차단·충족5·부족5·주의·카드상태·작성자·회사hash·ontologyhash는 빈칸이다. 카드상태10개는 사람이 선택해야 하며 임의10개를 정답 표본으로 확정하지 않았다. 110카드의 쪽은 미확인으로 남는다.

문서10건은 미완성이다. fixture5개는 작성 자료 준비 완료, 로컬 홈페이지 후보4개 중 notice79만 구조가 있고 나머지3개는 구조 부재, 열 번째 문서는 미선정이다. notice79는 이번 blind pack에 합치지 않았다. 다섯 자료만으로 인수10건을 충족했다고 하지 않는다. 회사/온톨로지 동결 전 사람 작성도 시작하지 않는 편이 좋다.

준비 도구 [hp_prepare.py](../../preparation/hp_prepare.py):

- `blank-gold cards.json --out <Git밖 새 파일>`: 입력 whitelist로 source-only 자료 생성, 정답은 null. 기존 파일 덮어쓰기 금지.
- `gold-check gold.json --out check.json`: 10문서, source/company/ontology hash, 사람 작성 표식·시각·모델출력 전 작성 선언, 판정 enum, 충족5/부족5 source unit ID, 서로 모순 없는 카드10상태, 차단조건 ID/문장/근거를 검사. 빈 자료는 exit2. 사람의 실제 작성 시점을 도구가 증명하는 것은 아니므로 감사 기록과 함께 확인한다.
- `score gold.json predictions.json --out score.json`: 문서집합·출처·회사/온톨로지 binding 일치, 누락·중복 ID 차단. 판정 일치율, 차단 조건 recall, 충족/부족 top5 reference precision, 카드상태 일치율·불일치 ID를 반환. 분모0은 null. 입력파일+도구 SHA로 scoring_input_sha256을 고정한다. 자동 인수 결과는 항상 not_decided다.

초안 JSON 형식은 blind pack과 도구의 `check_gold`가 정본이다. gold의 `status=human_completed`와 작성자/시간/모델출력전 선언은 사람이 실제 작성 후 넣는다. source_cards를 임의 수정하지 말고 별도 원본 pack의 hash와 대조한다. 회사·온톨로지·표본 선택 이후 정식 JSONSchema와 서명/동결 manifest를 HP06 spec에서 고정한다.

prediction 초안은 `{company_sha256,ontology_sha256,documents:[{document_id,source_sha256,verdict,blocking_condition_ids,met:[unit_id×5],gap:[unit_id×5],card_states:[{unit_id,status}]}]}`. 원본 모델 출력을 그대로 이 형식이라고 가정하지 않는다. 제품 export와 사람의 condition ID alignment가 필요하다. 자유 문장은 fuzzy matching으로 같다고 채점하지 않는다. 새로운/미일치 차단조건은 사람 판정 대기 목록에 남긴다.

**top5 한계**: gold가 충족/부족 전체 목록이 아니라5개씩이면 다른 올바른 항목을 고른 모델이 낮은 점수를 받을 수 있다. 현재 지표 이름을 reference_precision_at_5로 한정했다. 추천은 사람이 채점 가능한 전체 집합을 확장하거나, 비일치 항목을 모델오류/gold누락/해석차이로 블라인드 재판정한 뒤 별도 점수를 내는 것. 도구가 정답을 보충하지 않는다. 부족5개가 실제로 없으면 지어내지 말고 양식의 최소개수 조건을 사용자와 바꿔야 한다.

D7 제안 8/10·차단recall0.8·카드일치0.7은 미승인이다. met/gap precision 기준·문서별 필수 통과 vs 전체 평균·unknown 평가·추가 차단 오탐 처리까지 먼저 정한다. 사람 gold 동결 → 모델10건 입력/중단조건 계획 승인 → 실제 실행 → 제품밖 채점 → 불일치 사람검토 → 최종 인수 순서다. 이번에는 모델10건 실행과 품질/인수 판단을 하지 않았다.
