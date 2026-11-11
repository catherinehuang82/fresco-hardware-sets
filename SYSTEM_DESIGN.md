# Hardware-set extraction system

## Purpose and scope

The system turns construction specification PDFs into structured hardware-set records. Its implemented flow combines rule-based document preparation with local Qwen extraction. PDF discovery and segmentation run across the archive; LLM extraction is configured for selected sets and has not been run over every candidate in the archive.

## Pipeline

1. **Inspect PDFs** (`inspect_hardware_pages.py`). PyMuPDF reads PDFs directly from `data.zip`, one page at a time. Header, section, list, and table clues retain likely pages in `candidate_pages.jsonl` and `candidate_pages.md`, with the PDF name and 1-based page number. This is a recall-oriented filter, not a final classifier. OCR is not used.
2. **Prepare hardware-set regions** (`segment_hardware_sets.py`). Heuristics identify likely set/group headings, table set identifiers, component-like rows, and page continuations. The script writes `hardware_sections.jsonl` and `hardware_sets.jsonl`; unresolved candidate-page regions are retained separately for review. This deterministic stage finds and prepares likely source regions—it does not perform the final component-field extraction.
3. **Extract structured components with local Qwen** (`extract_mvp_llm.py`). The runner uses prepared set records, adjacent-page text, and available PDF table geometry as input to Qwen3-4B-Instruct-2507 through MLX-LM. The model extracts identifiers, door references, components, quantities, products/catalog values, manufacturers, finishes, notes, and source locations. Source-aligned post-processing can use printed table headers and explicit code legends; unsupported or unclear fields remain null.
4. **Validate and save output.** JSON parsing and schema checks reject malformed or invalid responses. The runner retries those failures up to two times, records raw responses and errors, and continues with other samples if one fails. Disagreement with the deterministic reference parser is recorded for review and does not trigger a retry. Run artifacts preserve source text, locations, validation status, and extraction output. The deterministic parser is a comparison aid, not authoritative ground truth.
5. **Review quality.** `qa_full_sample.py` compares representative output records against source PDF text and layout evidence and writes a separate discrepancy report. The saved manual review and evaluation reports document what was checked and what remains uncertain; none of these QA findings automatically edits extraction JSON.

## How to run and inspect the implementation

See [README.md](README.md) for dependencies, local model setup, and commands. `extract_sample_project_sets.py` is a supporting deterministic parser for JC Ryan 2 list schedules and Roselle Public Library tables; it is not the LLM extraction stage.

The checked-in runner configuration contains six selected sets. Saved evaluation artifacts also include 20 representative LLM records and a focused five-sample final result. These examples demonstrate the extraction stage, but the project does not currently run LLM extraction over all segmented sets automatically. The final five-sample JSON is [five_sample_rerun_final.json](five_sample_rerun_final.json); the broader representative output is [full_sample_representative_extractions.json](full_sample_representative_extractions.json).

## Evaluation and limitations

The archive contains 43 PDFs in 21 project folders (17,637 pages). Existing segmentation outputs contain 1,103 raw candidate records and 752 unresolved review regions. Exact repeated schedule copies across two projects reduce the estimated unique candidate count to 981; these are still heuristic candidates, not verified set totals.

The bounded manual review matched 31 of 31 extracted component rows against the source and found 31 of 33 source rows across four countable selected sets (about 94% row recall). These figures are small-sample results, not corpus-wide accuracy; a fifth reviewed set was excluded because its schedule mixes hardware with security and coordination entries. Schema validity confirms output shape only, not completeness or factual correctness.

Known limits include:

- Searchable hardware schedules in SJC Well Behavioral and StarHardware were missed by segmentation; Woodridge Public Works remains inconclusive.
- 299 pages had no extractable text. OCR was not used, so graphic-only schedules cannot be ruled out.
- Complex tables, merged cells, page continuations, unquantified rows, and manufacturer/product/finish mapping can still be mishandled. The latest Roselle sample omits two unquantified rows.
- Only selected sets have LLM output, and there is no comprehensive labeled reference set. Corpus-wide precision and recall are unknown.

See [SUBMISSION_SUMMARY.md](SUBMISSION_SUMMARY.md) for the project snapshot and [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for a walkthrough.
