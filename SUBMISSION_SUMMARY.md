# Submission summary

## Functionality

- Reads PDFs inside `data.zip` with PyMuPDF and records 1-based page locations.
- Uses heuristic page filtering and set segmentation, followed by deterministic sample parsing for JC Ryan 2 and Roselle Public Library.
- Includes a separate local-only Qwen/MLX extraction experiment and source-grounded output artifacts.

## Evaluation snapshot

- Corpus inventory: 43 PDFs, 17,637 pages, grouped in 21 project folders.
- Original LLM evaluation: one representative set from each of 20 segmented PDFs; all 20 outputs were schema-valid. This is not evidence of 20 correct extractions.
- Latest five-sample source review: across four countable selected sets, 31/31 extracted component rows matched source rows (100% row precision) and 31/33 source rows were represented (about 94% row recall). Gerrard was excluded from those counts because its schedule mixes hardware and coordination/security entries.
- These are small, selected-sample results. No corpus-wide precision or recall has been measured.

## Known limitations

- Segmentation misses searchable schedules in SJC Well Behavioral and StarHardware. Woodridge Public Works remains inconclusive.
- 299 pages had no extractable text; OCR was not used.
- The latest Roselle sample still misses two unquantified rows. Table continuations, merged cells, component notes, and manufacturer/product/finish mapping remain uncertain.
- JSON/schema validity and automated QA flags do not establish completeness or factual correctness.

See [README.md](README.md) for setup and commands, [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) for the architecture, and [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for a short presentation walkthrough.
