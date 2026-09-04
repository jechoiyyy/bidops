"""회차 산출물(JSON/YAML) 적재기와 그 계약 (lifecycle, 명세 §5.2).

`contracts`는 회차 산출물의 선언적 계약이라 형제 모듈이 직접 받는 공개
표면이고, `loader`는 동작이라 `app/lifecycle/__init__.py`의 이름으로만
내보낸다. 판정·리뷰·C-2 선별 결과의 적재는 T5a가 screening으로 옮겼다.
"""
