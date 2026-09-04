"""이름이 바뀌기 전 경로를 위한 재수출 (명세 §6.6).

유일한 모델 transport는 `app.core.model_client`다. 이 모듈은 `VllmClient`
이름으로 들던 호출부가 그대로 돌아가도록 공개 이름만 다시 내보낸다. **새
코드는 `app.core.model_client`를 직접 import한다.**
"""

from __future__ import annotations

from .model_client import (
    APPROVED_GENERATION,
    APPROVED_RETRIES,
    APPROVED_TIMEOUT_SECONDS,
    MAX_COMPLETION_TOKENS,
    MAX_RESPONSE_BYTES,
    MODEL_PURPOSES,
    EncryptedObjectStore,
    InvocationResult,
    ModelClient,
    ModelEndpoint,
    ModelEndpointError,
    ModelIdentity,
    ModelIdentityError,
    ModelInvocationError,
    ResponseTooLargeError,
    StructuredOutputContract,
    VllmClient,
    VllmInvocationError,
    build_prompt,
    resolve_model_endpoint,
    sanitize_for_prompt,
)

__all__ = [
    "APPROVED_GENERATION",
    "APPROVED_RETRIES",
    "APPROVED_TIMEOUT_SECONDS",
    "MAX_COMPLETION_TOKENS",
    "MAX_RESPONSE_BYTES",
    "MODEL_PURPOSES",
    "EncryptedObjectStore",
    "InvocationResult",
    "ModelClient",
    "ModelEndpoint",
    "ModelEndpointError",
    "ModelIdentity",
    "ModelIdentityError",
    "ModelInvocationError",
    "ResponseTooLargeError",
    "StructuredOutputContract",
    "VllmClient",
    "VllmInvocationError",
    "build_prompt",
    "resolve_model_endpoint",
    "sanitize_for_prompt",
]
