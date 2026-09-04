"""문서 준비·사전규격 개요 검토·심층 검토·입찰 delta와 최종 결정.

deep_review는 core와 lifecycle을 import하고, screening은 §6.3의 읽기 전용 seam
함수(`current_judgment`·`current_judgments`·`latest_corrected_grade`)로만 본다.

T7 1단계가 이 패키지로 service·router·worker·agent·document_mcp·contracts·
policies·cli·schemas를 옮겼다. 모듈 진입점과 `__init__`의 공개 표면 정리는
아직 하지 않았고, 조립 계층은 여전히 `app.deep_review.<하위 경로>`를 직접
들고 있다(경계 검사의 미구현 절 참고). 그 정리는 T8이 한다.
"""

from __future__ import annotations
