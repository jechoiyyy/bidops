# HP-01 STEP-004 결과 — taxonomy v2

`document_segments.py`의 taxonomy identity를 `bidops.segment-taxonomy.v2`로 올렸다. HP 공통 계약 §3.4의 category 표를 정확 일치 규칙으로 연결하고, 공백과 끝의 `요구사항`을 정규화한다. segment 안에 인식된 카드 category label이 있으면 그 합집합을 사용하며 제목·접두사 후보와의 충돌로 표시하지 않는다. 인식된 카드 label이 없으면 기존 제목 키워드·접두사 분류와 충돌 시 사람 확인 규칙을 유지한다.

`_RULES`에 `category_taxonomy`를 포함해 binding hash가 분류표를 고정하도록 했다. 접두사 `ECR`, `STR`, `MAR`, `MPR`, `MHR`와 `operations_maintenance` 제목 키워드도 추가했다. `test_document_bundles.py`의 API taxonomy literal을 v2로 맞췄다.

T6 단위 검사는 §3.4의 category 표 전체 매핑과 공백·접미 정규화·미지 category, 여러 카드 label 합집합, 카드 label 우선, 다섯 접두사, `장애 대응` 제목 키워드 및 미지 category의 기존 충돌 검토를 포함한다.

검사는 실행하지 않았다. 루트 실행 selector:

```sh
cd web/backend
python -m pytest tests/deep_review/test_document_segments.py tests/app/test_document_bundles.py -q
```

실측 198개 카드 중 쪽 상속 88건이라는 T11 한계는 분류 변경으로 보정하지 않았으며, 별도 T11 범위로 남긴다.
