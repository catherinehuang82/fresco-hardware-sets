# Hardware-set extraction: implemented design

## Pipeline

The source archive `data.zip` is read without modifying its PDFs. The reproducible rule-based flow is:

1. **Inspect pages** (`inspect_hardware_pages.py`): PyMuPDF reads pages individually, extracts text and uses broad section/header/table clues to retain likely pages in `candidate_pages.jsonl` and `candidate_pages.md`. Each retained record includes PDF identity and a 1-based page number. No OCR is performed.
2. **Segment sets** (`segment_hardware_sets.py`): heuristic headings, list/table clues, and page context produce `hardware_sections.jsonl`, `hardware_sets.jsonl`, and `hardware_set_segmentation_report.md`.
3. **Deterministic sample extraction** (`extract_sample_project_sets.py`): selected list/table parsers produce prototype JSON for JC Ryan 2 and Roselle Public Library in `sample_hardware_sets.json`.

Commands and setup are in [README.md](README.md). These stages overwrite their default outputs when rerun.

## Separate LLM experiment

`extract_mvp_llm.py` is an optional local Qwen3-4B-Instruct-2507 MLX experiment. It reuses existing segmented regions and runs six configured samples; it is not the discovery or segmentation stage. It requires Apple Silicon/macOS with Metal, MLX-LM, and local model weights. Runtime sets offline flags and uses no hosted inference service.

The original 20-sample run is preserved in [full_sample_representative_extractions.json](full_sample_representative_extractions.json). It sampled one set from each of 20 segmented PDFs. The latest focused five-sample result is [five_sample_rerun_final.json](five_sample_rerun_final.json), with comparison in [five_sample_manual_review.md](five_sample_manual_review.md). Neither is a full extraction of the archive.

## Current evidence and limits

The archive contains 43 PDFs in 21 project folders (17,637 pages). The inspector found 1,378 candidate pages; segmentation produced 1,103 set candidates across 20 PDFs. These are heuristic counts, not accuracy measurements. The full-sample report, per-PDF inventory, and independent source QA are in [full_sample_evaluation_report.md](full_sample_evaluation_report.md), [full_sample_pdf_inventory.json](full_sample_pdf_inventory.json), and [full_sample_source_qa.jsonl](full_sample_source_qa.jsonl).

The bounded five-sample review matched 31 of 31 extracted rows against the source across four countable sets and found 31 of 33 source rows (about 94% row recall). These selected examples do not estimate corpus performance. The 20 original LLM samples were schema-valid, but schema validity is not factual correctness.

Known gaps and limits:

- Searchable hardware schedules in SJC Well Behavioral and StarHardware were missed by segmentation; Woodridge Public Works is inconclusive.
- 299 pages had no extractable text. They were not OCR’d, and graphic-only schedules cannot be ruled out.
- Table cell geometry, merged cells, unquantified rows, manufacturer/product/finish mapping, and page continuations remain error-prone. The latest Roselle sample still omits two unquantified rows.
- There is no comprehensive labeled reference set. Corpus-wide precision and recall have not been measured.

See [SUBMISSION_SUMMARY.md](SUBMISSION_SUMMARY.md) for the concise submission status and [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for a short walkthrough.
