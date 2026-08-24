---
name: bidops-screen
description: Screen normalized Korean public-service opportunities against Rootlab's company profile, producing evidence-backed grades, readiness, counterarguments, and verification items. Use after bidops-collect; do not treat inferred or unknown company facts as confirmed eligibility.
---

# BidOps Screen

Read these sources before judging:

- [workflow contract](../references/workflow-contract.md) — the `bidops.decisions.v2` section defines every field you must write
- `../../docs/reference/company-profile.md`
- `../../docs/skill-workflow-validation.md`

Use `validation-set.json` as input and write `screening-decisions.json`. That file is the only artifact in this workflow authored by an agent, and nothing downstream fills in what it omits. A judgment missing a perspective, a piece of evidence, a counterargument, or a verification item is rejected, and no report is produced.

```bash
python3 skills/bidops-screen/scripts/build_screening_results.py \
  data/runs/20260817-20260823/validation-set.json \
  data/runs/20260817-20260823/screening-decisions.json \
  --output data/runs/20260817-20260823/screening-results.json
```

## Independent review passes

Write all five perspectives for every record, under exactly these names:

| 관점 | 답해야 하는 질문 |
|---|---|
| `기술 적합성` | Required technology and delivery role versus confirmed capabilities |
| `실적 정합성` | Similarity to named performances, including the mismatch as well as the match |
| `공공 SI 적합성` | System build, enhancement, operations, integration, ISP/BPR, portal, or data-platform relevance |
| `사업성·자격 제약` | Budget, region, licences, direct-production certificates, software-business registration, staffing, participation form |
| `전략 부합` | Alignment to the three priority axes and to declared new-entry areas |

Each perspective carries its own `assessment` (`적합`, `부분 적합`, `부적합`, `확인 불가`), its own reason, and at least one piece of evidence. Do not let one pass copy another pass's conclusion; a perspective that only restates the summary tells the reviewer nothing about where the judgment is weak. Synthesize only after all five and the counterarguments are written.

Then write the counterargument pass separately into `counterarguments`. Look for reasons the positive assessment may be overstated or unsupported. A counterargument that would fit any notice in the sample is not a counterargument, and repeating one sentence across most records is rejected by the merge step.

## Evidence rules

- Cite the notice field or source text used for every material notice claim.
- Cite the company-profile section and its `confirmed`, `inferred`, or `unknown` status for every company claim.
- Company-introduction performances prove technical/domain experience only. Their legal recognition for bid qualification is `unknown`.
- Treat `notice.performance_matches` as retrieval suggestions. Verify the substantive match independently; never copy the similarity score into the final grade as if it proved scope equivalence. When the collector attached such a signal, record what it does *not* establish in `mismatch_or_limit`.
- Check `focus_matches[].field_kind`. A concept found only in `pubPrcrmnt*ClsfcNm` is a procurement office's classification label, not a statement about this notice's scope.
- Read `procurement_class`, `region_limit`, `lifecycle`, and `qualification_flags` before raising a verification item. Asking the reviewer to confirm something the API already answered wastes the reviewer's attention.
- Missing attachment text is an information gap, not a negative fact.
- Never infer a certificate, registration, staffing level, budget preference, regional feasibility, or legal performance qualification.

## Two-dimensional result

Assign opportunity grade separately from participation readiness.

- `우선 검토`: strong fit to at least one priority axis and no verified disqualifier.
- `검토 권장`: plausible fit, but the current notice text is too weak or mixed for immediate prioritization.
- `관찰 대상`: not actionable now, but institution, topic, or expected follow-up has tracking value.
- `제외`: clear domain mismatch or a verified disqualifier. Unknown information alone never justifies exclusion.

Readiness is one of `확인 완료`, `부분 확인 필요`, `참여 불가 확인`, or `해당 없음`. A strong opportunity may be `우선 검토` and `부분 확인 필요` at the same time.

A `제외` record takes `해당 없음` or `참여 불가 확인`. Never `확인 완료`: nothing was verified on a notice you decided not to pursue, and the report would read as "checked and clear to bid". Every `제외` also needs an `exclusion_category` from the contract's list, because the weekly report summarizes exclusion reasons from that field and never guesses them from the title.

For each verification item, distinguish whether it blocks actual bid participation. Keep it visible beside the grade and include a concrete next action.
