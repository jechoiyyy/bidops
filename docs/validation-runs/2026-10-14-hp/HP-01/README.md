# HP-01 requirement-card inventory evidence

- **Input conversion run began:** 2026-10-14.
- **Evidence recorded:** 2026-10-15. The folder date follows the conversion run, not the later evidence-script run.
- **Scope:** five existing isolated HWP/HWPX conversion artifacts. The source files, structures, page maps, and PDFs remain in the local runtime directory and are not committed.

## Inputs and provenance

The conversion metadata is in [`hp01-conversion.json`](../../../work/_runs/hp0001-20261014/hp01-conversion.json). It records worker `bidops-local-document-worker-1`, method `process_document(original_bytes, options={prepare_pdf: true, timeout_seconds: 120})`, and `model_calls=0`, along with each source hash and artifact name. The evidence run reused those outputs; it did not rerun conversion or call a model.

The inputs used by the script are the five matching `*.structure.json` and `*.para_page_map.json` pairs in `/Users/temp/orca/bidops/.sdlc/local-runtime/hp01-20261014-fixtures`. PDFs were used only for the separate visual spot check described below.

## Reproduce the inventory summary

```sh
PYTHONPATH=web/backend python3 scripts/hp-card-inventory-check.py \
  --dir /Users/temp/orca/bidops/.sdlc/local-runtime/hp01-20261014-fixtures \
  --out docs/validation-runs/2026-10-14-hp/HP-01/cards.json
```

The script reads existing JSON snapshots, calls `build_manifest_payload` and `resolve_card_pages`, and writes the JSON summary to stdout and [`cards.json`](./cards.json). It does not access PostgreSQL, MinIO, a network service, or the original documents. `--out` creates a new file and refuses to replace an existing path. The command above records the completed run; choose a new output filename when reproducing it.

## Observed result

The card-count target was 198 and the script found 198 cards. The page-availability target was 198/198; that target was **not met**. The product resolver found no direct card-cell mapping, inherited a page for 88 cards, and left 110 unavailable.

| Document | Cards | Direct mapped | Inherited | Unavailable |
|---|---:|---:|---:|---:|
| `doc1` | 27 | 0 | 0 | 27 |
| `gangwon` | 57 | 0 | 18 | 39 |
| `mofa` | 31 | 0 | 31 | 0 |
| `nyj` | 35 | 0 | 35 | 0 |
| `school` | 48 | 0 | 4 | 44 |
| **Total** | **198** | **0** | **88** | **110** |

The JSON preserves product warnings and duplicate IDs. `duplicate_ids` comes from the combined inventory; both inventory occurrences are preserved, while `card_count` counts only `label_value_table` cards. `gangwon` has 11 duplicate IDs and `school` has 9. No warning or unavailable page was converted into a successful mapping.

## Page-map diagnosis and PDF spot check

[`hp01-page-map-diagnosis.json`](../../../work/_runs/hp0001-20261014/hp01-page-map-diagnosis.json) records the prior per-document anchor diagnosis. [`hp01-pdf-spotcheck.json`](../../../work/_runs/hp0001-20261014/hp01-pdf-spotcheck.json) records a 10-card visual sample: six inherited pages matched the visible card location, while four samples with an unavailable product page remained unverified by the product locator. This is a spot check, not a 198-card accuracy claim. One `school` sample on PDF page 13 has overlapping text from another card; that limitation is already recorded in the [repository findings](../../../tracking/findings.md).

This evidence covers the local extraction and locator calculation only. It does not establish a successful database backfill, migration deployment, or production operation. For the 110 unavailable cards, the product resolver found neither a direct card-cell mapping nor a mapped key among that card's stored nearest three paragraph anchors, so it kept the page unavailable.


## Separate isolated deployment evidence

On 2026-10-15 KST, the leader completed the user-authorized `bidops-local` migration0037, one existing homepage structure backfill and idempotent rerun, and web/analysis-worker replacement. [Deployment evidence](../../../work/_runs/hp0001-20261014/hp01-deployment.md) links backup hashes, preservation checks, runtime settings and actual API results. Existing rows were unchanged; one manifest, 105 segments and 35 inventory cards were added. That DB source is distinct from the five T11 files: 35 cards, 13 inherited pages and 22 unavailable. The other three homepage pre-specs have no structure and were not backfilled. This establishes neither model quality nor human acceptance.
