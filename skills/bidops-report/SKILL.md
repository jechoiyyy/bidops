---
name: bidops-report
description: Render BidOps screening JSON into a weekly monitoring report, per-notice analysis pages, and a reviewer feedback template. Use after bidops-screen; do not change judgments while rendering.
---

# BidOps Report

Read [the workflow contract](../references/workflow-contract.md), validate the input shape, and run the deterministic renderer.

```bash
python3 skills/bidops-report/scripts/render_report.py \
  data/runs/20260817-20260823/screening-results.json \
  --output-dir reports/20260817-20260823
```

The renderer creates:

- `weekly-monitoring.html`: counts, priority queue, deadlines, pre-specifications, and verification requests.
- `details/<notice-id>.html`: judgment, readiness, perspectives, matched performances, counterarguments, evidence, retrieval signals, and next action.
- `review-feedback.yaml`: blank structured review entries for each notice.

Keep grade and readiness visually separate. Show verification counts beside the grade. Do not hide `unknown` evidence or convert it into positive or negative claims.

HTML is a presentation of the screening JSON, never a second judgment pass. Every value on the page must be traceable to a field in the input. In particular, exclusion reasons come from `judgment.exclusion_category`; when that field is missing the page says `사유 미기재` rather than guessing a reason from the notice title. Keyword rules that classify a notice belong in the screening step, where they are recorded as a judgment with evidence.

The default queue holds analysis-sample records graded `우선 검토`, `검토 권장`, or `관찰 대상`. Keep semantic-screen exclusions and filter-audit samples in separate collapsed sections, retain their detail pages for traceability, and summarize exclusion reasons above those sections.

Audit-sample records never enter the review queue, whatever their grade. An audit record that screening did *not* exclude is a first-filter miss, which is the one number this sample exists to produce: show it in the statistics row and mark the record itself.
