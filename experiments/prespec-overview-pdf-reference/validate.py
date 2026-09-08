"""Reference producer adapter to the shared page-evidence validator.

Frozen run/code copies keep their historical validator. New runs use the same
schema and evidence checks as the DB importer; no prompt or output is repaired.
"""
from app.deep_review.schemas.page_overview import PageOverviewPayload as PageReview
from app.deep_review.services.page_overview_validation import (
    FACT_SECTIONS, VALIDATOR_VERSION, fold_space, validate_page_overview,
)


def validate(output, record, schema):
    blocks = record['model_input']['blocks']
    if len({block['pdf_page'] for block in blocks}) != len(blocks):
        return ['ambiguous_input_page']
    return validate_page_overview(output, {block['pdf_page']: block['text'] for block in blocks})
