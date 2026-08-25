"""Safe errors raised by the isolated document processor.

Error messages in this module are deliberately independent of input names,
temporary paths, command lines, and document contents.  They can therefore be
returned to an API client and written to an audit event without leaking the
quarantine namespace.
"""

from __future__ import annotations


class DocumentProcessingError(RuntimeError):
    """A deterministic, safe-to-display document processing failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        blocking: bool = True,
        source_preserved: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.blocking = blocking
        self.source_preserved = source_preserved
        super().__init__(message)


class DocumentLimitError(DocumentProcessingError):
    """Input exceeded a processor limit."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, blocking=True)
