# Baseline failure comparison

- Baseline main: c2428508ff728b9039158474bafae5bb5357a3d4.
- Leader cwd: /Users/temp/orca/bidops/web/backend.
- Command: `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=true /tmp/bidops-demo00-verify-venv/bin/python -m pytest tests/deep_review/test_auto_preparation.py::test_the_flag_opens_preparation_for_sw_business_without_a_grade -q`
- Actual result: exit 1, 1 failed, 3 warnings, 0.81s. Assertion `service.created == [notice.id]`: actual `[]`, expected `[1]`.
- Feature has identical assertion failure: step002-legacy-enabled-delta.log. maybe_auto_prepare is unchanged; this is a pre-existing failure, not a new company-boundary regression. Full automatic preparation success is not claimed.
- The other 13 automatic deep-review cases passed with their intended enabled branch explicitly selected in an isolated test process. The running app, its environment, DB and model were not modified.
