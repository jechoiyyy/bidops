---
name: bidops-collect
description: Collect and normalize Korean G2B service bid notices and pre-specifications, then create a high-recall BidOps validation sample. Use for BidOps collection, filtering, or validation-set preparation; do not make semantic fit or bid-participation judgments.
---

# BidOps Collect

Collect official G2B records deterministically and preserve enough raw evidence to reproduce every later decision.

Read [the workflow contract](../references/workflow-contract.md) before producing artifacts.
For candidate retrieval, also use the company-introduction project-title reference at
`../../docs/reference/company-performance-titles.tsv` (PDF pages 41–46).

## Workflow

1. Confirm the exact collection window and output directory. For the initial validation use `2026-08-17` through `2026-08-23`, inclusive, in `Asia/Seoul`.
2. Run `scripts/collect_notices.py` from the `bidops-agent` directory. It reads `BIDOPS_G2B_API_KEY` from the environment or a git-ignored `.env` file. Never print or persist the key.
3. Inspect collection counts and warnings. Preserve raw API pages under the run directory.
4. Run `scripts/select_validation_sample.py` to select up to 30 analysis records and 10 audit records.
5. Report underfilled strata or missing fields; do not silently invent or backfill data.

```bash
python3 skills/bidops-collect/scripts/collect_notices.py \
  --from-date 2026-08-17 --to-date 2026-08-23 \
  --output-dir data/runs/20260817-20260823

python3 skills/bidops-collect/scripts/select_validation_sample.py \
  data/runs/20260817-20260823/collected-notices.json \
  --output data/runs/20260817-20260823/validation-set.json
```

Changing a retrieval rule does not require a new API call. `--from-raw` re-normalizes the preserved pages in the run directory, so a rule change can be measured against the identical record set:

```bash
python3 skills/bidops-collect/scripts/collect_notices.py \
  --from-date 2026-08-17 --to-date 2026-08-23 \
  --output-dir data/runs/20260817-20260823 --from-raw
```

## Filtering boundary

Candidate retrieval is the union of two independent signals:

1. A normalized Korean/English focus-concept match.
2. A sufficiently specific project-title similarity to the company performances on PDF pages 41–46.

Normalize Unicode width, case, punctuation, and separators before concept matching. Treat `AI Agent`, `ai-agent`, and full-width variants as the same concept. Maintain Korean/English aliases for concepts such as `온톨로지`/`ontology`, `지식그래프`/`knowledge graph`, and `블록체인`/`blockchain`. Short English abbreviations require token boundaries so `AI` does not match inside `G-Fair` or `KAIST`.

Match each API field on its own and record where every signal came from. A concept must not be formed from the tail of one field and the head of the next.

Performance similarity is a discovery signal, not proof that the new notice has the same scope. Require a digital-deliverable context and suppress matches caused only by generic words such as system, platform, maintenance, or project support. Preserve the top matching titles, source pages, similarity values, and legal-qualification status on the notice. That status remains `unknown`.

A record without either signal belongs to the audit pool, not a definitive exclusion set. Keep ambiguous records for semantic screening. Do not filter on budget, region, company qualification, or unconfirmed negative keywords during this validation.

The three equal-priority focus axes are `AI/데이터`, `블록체인·DID`, and `공공 SI·통합관리`.

## Signal provenance

Procurement classification labels (`pubPrcrmntLrgClsfcNm`, `pubPrcrmntMidClsfcNm`, `pubPrcrmntClsfcNm`) are attached to every service notice by the procurement office. They are useful for retrieval but they are not evidence about the scope of one notice. Record `field_kind` on every signal so the screening step can weigh a title concept differently from a classification label, and report how many sampled records were retrieved by classification alone.

## Fields that later steps depend on

Preserve these API values on the normalized record even when the current validation does not filter on them. They answer questions the screening step would otherwise raise as verification items, and they carry the lifecycle the design depends on.

| 필드 | 목적 |
|---|---|
| `rgnLmtBidLocplcJdgmBssNm`, `jntcontrctDutyRgnNm1..3` | 지역 제한과 지역의무공동도급 조건 |
| `pubPrcrmnt*ClsfcNm` | 과업 성격 구분. 첨부 문서 없이도 행사·연구·감리를 분리할 수 있다 |
| `bfSpecRgstNo` | 사전규격에서 본공고로 이어지는 연결 고리 |
| `reNtceYn`, `befBidBbancNo`, `chgDt`, `chgNtceRsn` | 재공고와 정정 이력 추적 |
| `arsltCmptYn`, `pqEvalYn`, `tpEvalYn`, `techAbltEvlRt` | 실적제한경쟁과 기술평가 여부 |

`rgnLmtBidLocplcJdgmBssNm`이 비어 있다는 사실은 지역 제한이 없다는 뜻이 아니다. 값이 없으면 `API 미표기`로 다루고 확인 항목으로 넘긴다.

## Sampling

When selecting a small validation sample, rotate the analysis records through the three axes and a fourth `수행실적 유사` retrieval stratum. Report how many sampled records were retrieved only by performance similarity.

The audit sample exists to find records the first filter missed, so it is not drawn at random. Rotate it through three strata:

1. `분류 근접`: the procurement classification describes a digital deliverable, yet retrieval failed.
2. `실적 유사 근접`: portfolio similarity landed just below the acceptance threshold.
3. `무작위`: everything else.

Ten records drawn uniformly from more than two thousand unrelated notices cannot measure recall. Targeted strata can.
