# Sol·Luna 불확실 판정 사람 검토 작업 기록

- 상태: 전체 모집단 997건 사람 gold 검토 완료.
- 원본 reference run: `20260824-20260826-sol200-luna797-xhigh-b100-reference-v1`
- 원본 reference 역할: `silver_reference_only`
- 고정 모집단 run: `20260824-20260826-interim-v4`
- 모집단 SHA-256: `3a91dab71cd483faa45de393f1cbea990f7b543cc7a7b686e6fae5b18ab4d28f`
- 검토 범위: 원본 `uncertain` 99건. 원본 점수 내림차순, 동점은 `plan_id` 오름차순이다.
- 리뷰 작성자 표식: `interactive-user`. 인증된 신원이나 권한을 뜻하지 않는다.

`uncertain-adjudication.tsv`에는 사용자가 확정한 99건을 기록했다. 결과는
`관련` 1건, `판단보류` 3건, `비관련` 95건이다. 허용 사람 판정은
`관련`, `판단보류`, `비관련`이며 우선순위 조합은 기존 실험 계약과 동일하게
`관련+높음|보통|낮음`, `판단보류+낮음`, `비관련+해당없음`만 사용한다.

`audit-adjudication.tsv`에는 원본 `not_relevant` 중 모델 간 이견 42건과
`audit-random-v1` 결정 순서로 뽑은 무작위 8건을 기록했다. 50건 모두 사람
`비관련` 판정이다. 원본 JSON은 수정하지 않았다.

`relevant-adjudication.tsv`에는 원본 `relevant` 114건의 사람 판정을 기록했다.
결과는 `관련` 89건, `판단보류` 3건, `비관련` 22건이다. 관련 판정의 우선순위는
직접적인 AI·데이터·통합시스템 과업 `높음`, 일반 SI·운영 `보통`, GIS·연구·전략
등 인접 과업 `낮음`으로 기록했다.

사람 gold와 운영 후보 정책은 분리한다. gold에는 실제 판정을 보존하고, 고재현율
운영 후보에서는 `관련`과 `판단보류`를 함께 포함해 false positive를 허용한다.

## 결합 결과

`human-gold.tsv`는 최초 세 검토 파일을 결합한 263건의 범위 제한 사람 정답 셋이다.
아래 수치는 전수 검토 전의 중간 결과로 보존한다.

- 표본 역할: `silver_uncertain` 99건, `silver_relevant` 114건, `audit` 50건
- 사람 relevance: `관련` 90건, `판단보류` 6건, `비관련` 167건
- 사람 priority: `높음` 27건, `보통` 43건, `낮음` 26건, `해당없음` 167건
- 모델 `relevant` precision: 판단보류 제외 `89 / 111 = 80.2%`
- 고재현율 후보(`relevant + uncertain`) precision: 판단보류 제외 `90 / 207 = 43.5%`
- 고재현율 후보의 사람 검토 유지율: 관련·판단보류 포함 `96 / 213 = 45.1%`
- 감사 표본에서 발견된 사람 관련: `0 / 50`
- 검토 범위 안 후보 recall: `90 / 90 = 100%`
- 전체 모집단 recall: 계산 불가. 원본 `not_relevant` 784건 중 50건만 감사했다.

## 전체 모집단 gold

`remaining-population-review-queue.tsv`는 기존 263건을 제외한 734건을
`184 + 184 + 183 + 183`으로 나눈 전수 검토 작업 기록이다. 네 묶음을 모두
검토했으며 734건은 전부 사람 `비관련`으로 확정됐다.

`human-gold-full-population.tsv`는 기존 263건과 추가 734건을 결합한 전체
997건의 사람 정답 셋이다.

- 사람 relevance: `관련` 90건, `판단보류` 6건, `비관련` 901건
- 사람 priority: `높음` 27건, `보통` 43건, `낮음` 26건, `해당없음` 901건
- mixed `relevant`만 후보: TP 89, FP 22, 판단보류 3, FN 1
- mixed `relevant` precision: 판단보류 제외 `89 / 111 = 80.2%`
- mixed `relevant` recall: `89 / 90 = 98.9%`
- mixed `relevant + uncertain` 후보: TP 90, FP 117, 판단보류 6, FN 0
- 고재현율 후보 precision: 판단보류 제외 `90 / 207 = 43.5%`
- 고재현율 후보 recall: `90 / 90 = 100%`
- mixed `relevant`만 사용할 때의 유일한 FN: `R26DD20852774` `노사누리 기능개선 사업`

같은 gold에서 Top 50 결과는 다음과 같다. 판단보류는 precision 분모에서 제외했다.

- TF-IDF: precision `75.5%`, recall `41.1%`
- BGE-M3 dense: precision `65.3%`, recall `35.6%`
- Qwen: precision `95.9%`, recall `52.2%`

파일 SHA-256은 다음과 같다.

- `uncertain-adjudication.tsv`: `344148c6897f1487740fb100a88f096c72da995987f744764bdfb3b84e935e6c`
- `relevant-adjudication.tsv`: `bda9bd455b130ad1d3a2e7d10b3860abe7cd0153b8785be130acb5a900d25081`
- `audit-adjudication.tsv`: `c1e151f96acc0c9fc5c4435d51f8d4a300e43c12b89129e82a5e3508f8044fe2`
- `human-gold.tsv`: `2a46a4b863d249ece8438dc6d300225f561591388ecbffa44d8d24d55b8f855e`
- `remaining-population-review-queue.tsv`: `ecb2c3c110cbc3c0b7fad4f66b8c1d072fabd4e3c44931feb3fd8bd5f5223556`
- `human-gold-full-population.tsv`: `cd3b9bc04bbbf37c9a2b5df5c3caac8de3a6a1f0a15cc609e8b4062356654cbd`
