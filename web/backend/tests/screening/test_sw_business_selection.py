from copy import deepcopy

from app.screening.orchestrator import _full_run_selection
from app.screening.policy import canonical_policy_bytes, load_policy_file


def sw_policy():
    body = deepcopy(load_policy_file())
    body['policy_version'] = 'screening-policy.sw-business.v1'
    body['candidate_selection'].update(
        rules_version='sw-business-selection.v1', mode='sw_business_all',
        include_collection_buckets=[],
    )
    return body


def test_sw_selection_includes_audit_y_and_excludes_n_and_unknown():
    body = sw_policy()
    assert canonical_policy_bytes(body)
    rows = [
        {'notice_id': 'y-audit', 'collection_bucket': 'audit_pool', 'qualification_flags': {'sw_business_status': 'Y'}},
        {'notice_id': 'n-candidate', 'collection_bucket': 'candidate_pool', 'qualification_flags': {'sw_business_status': 'N'}},
        {'notice_id': 'y-candidate', 'collection_bucket': 'candidate_pool', 'qualification_flags': {'sw_business_status': 'Y'}},
        {'notice_id': 'unknown', 'collection_bucket': 'candidate_pool', 'qualification_flags': None},
    ]
    assert [r['notice_id'] for r in _full_run_selection(rows, body)] == ['y-audit', 'y-candidate']
    assert [r['notice_id'] for r in _full_run_selection(rows, load_policy_file())] == ['n-candidate', 'y-candidate', 'unknown']
