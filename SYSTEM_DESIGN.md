# Hardware-set extraction system

## Purpose and scope

The system turns construction specification PDFs into structured hardware-set records. Its implemented flow combines rule-based document preparation with local Qwen extraction. PDF discovery and segmentation run across the archive; LLM extraction is configured for selected sets and has not been run over every candidate in the archive. The supplied `data.zip` must be placed in the project root; it is not tracked in this repository.

## Pipeline

1. **Inspect PDFs** (`inspect_hardware_pages.py`). PyMuPDF reads PDFs directly from `data.zip`, one page at a time. Header, section, list, and table clues retain likely pages in `candidate_pages.jsonl` and `candidate_pages.md`, with the PDF name and 1-based page number. This is a recall-oriented filter, not a final classifier. OCR is not used.
2. **Prepare hardware-set regions** (`segment_hardware_sets.py`). Heuristics identify likely set/group headings, table set identifiers, component-like rows, and page continuations. The script writes `hardware_sections.jsonl` and `hardware_sets.jsonl`; unresolved candidate-page regions are retained separately for review. This deterministic stage finds and prepares likely source regions—it does not perform the final component-field extraction.
3. **Extract structured components with local Qwen** (`extract_mvp_llm.py`). The runner uses prepared set records, adjacent-page text, and available PDF table geometry as input to Qwen3-4B-Instruct-2507 through MLX-LM. The model extracts identifiers, door references, components, quantities, products/catalog values, manufacturers, finishes, notes, and source locations. Source-aligned post-processing can use printed table headers and explicit code legends; unsupported or unclear fields remain null.
4. **Validate and save output.** JSON parsing and schema checks reject malformed or invalid responses. The runner retries those failures up to two times, records raw responses and errors, and continues with other samples if one fails. Disagreement with the deterministic reference parser is recorded for review and does not trigger a retry. Run artifacts preserve source text, locations, validation status, and extraction output. The deterministic parser is a comparison aid, not authoritative ground truth.
5. **Review quality.** `qa_full_sample.py` compares representative output records against source PDF text and layout evidence and writes a separate discrepancy report. It requires generated candidate/segment files and the 20-sample extraction JSON, which are not included in this repository; the summarized findings are in `SUBMISSION_SUMMARY.md`. QA findings do not edit extraction JSON.

## How to run and inspect the implementation

See [README.md](README.md) for dependencies, local model setup, and commands. `extract_sample_project_sets.py` is a supporting deterministic parser for JC Ryan 2 list schedules and Roselle Public Library tables; it is not the LLM extraction stage.

The checked-in runner configuration contains six selected sets. A separate 20-PDF representative evaluation and a focused five-sample review were completed, but the detailed 20-sample JSON and QA files are not included in this repository. The tracked [five-sample JSON](five_sample_rerun_final.json) is available for inspection. The project does not currently run LLM extraction over all segmented sets automatically.

## Evaluation and limitations

The archive scan covered 43 PDFs in 21 project folders and 17,637 pages. PyMuPDF extracted text from 17,338 pages; 299 had no extractable text. The inspector retained 1,378 candidate pages. Segmentation produced 1,103 raw set-candidate records and 752 unresolved review regions. Removing exact repeated schedule copies within the Gerrard and Bridgeport project folders gives an adjusted estimate of 981 candidate records; none of these counts are verified set totals.

In the separate 20-PDF representative run, one set was sampled from each of the 20 PDFs with segmented set candidates. All 20 responses passed JSON/schema validation. The other 23 PDFs had no segmented set candidate and were skipped for that run; zero PDFs with set candidates were left unsampled. This does not establish that the skipped PDFs contain no hardware sets.

The bounded manual review matched 31 of 31 extracted component rows against the source and found 31 of 33 source rows across four countable selected sets (about 94% row recall). These figures are small-sample results, not corpus-wide accuracy; a fifth reviewed set was excluded because its schedule mixes hardware with security and coordination entries. Schema validity confirms output shape only, not completeness or factual correctness.

Known limits include:

- Searchable hardware schedules in SJC Well Behavioral and StarHardware were missed by segmentation; Woodridge Public Works remains inconclusive.
- OCR was not used, so hardware schedules present only as page images remain unverified.
- Complex tables, merged cells, page continuations, unquantified rows, and manufacturer/product/finish mapping can still be mishandled. The latest Roselle sample omits two unquantified rows.
- Only selected sets have LLM output, and there is no comprehensive labeled reference set. Corpus-wide precision and recall are unknown.

See [SUBMISSION_SUMMARY.md](SUBMISSION_SUMMARY.md) for the project snapshot and evaluation details.
