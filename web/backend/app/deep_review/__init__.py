"""문서 준비·사전규격 개요 검토·심층 검토·입찰 delta와 최종 결정.

deep_review는 core와 lifecycle을 import하고, screening은 §6.3의 읽기 전용 seam
함수(`current_judgment`·`current_judgments`·`latest_corrected_grade`)로만 본다.

T6은 이 패키지에 ``models``만 두었다. 나머지 service·router·worker·agent의 폴더
이주와 이 `__init__`의 공개 표면 정리는 뒤의 task가 한다. 그 전까지 조립 계층은
`app.services`·`app.routers` 경로를 그대로 쓴다(경계 검사의 미구현 절 참고).
"""

from __future__ import annotations
