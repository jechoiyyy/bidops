"""조립 계층이 앱 객체를 만들 때 deep_review 확장점을 등록한다 (명세 §6·§9)."""

from __future__ import annotations

from app.lifecycle import extension_registry
from app.main import app  # noqa: F401 — import 자체가 등록 시점이다
from app.services.deep_review_hooks import PreSpecAttachmentEligibilityHook
from app.services.prespec_projection import PreSpecOverviewDocumentProjection


def test_app_assembly_registers_the_overview_document_projection():
    registry = extension_registry()

    assert registry.overview_filters_supported is True
    assert isinstance(registry.overview_document_projection, PreSpecOverviewDocumentProjection)


def test_app_assembly_registers_the_prespec_attachment_hooks():
    registry = extension_registry()

    assert registry.run_ingest_hook_count >= 1
    assert registry.tracking_decision_hook_count >= 1
    assert any(
        isinstance(hook, PreSpecAttachmentEligibilityHook) for hook in registry._run_ingest_hooks
    )
    assert any(
        isinstance(hook, PreSpecAttachmentEligibilityHook) for hook in registry._tracking_hooks
    )
