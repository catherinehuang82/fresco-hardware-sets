# Hardware-set extraction

This project reads construction specification PDFs from `data.zip`, finds likely hardware schedules and set regions, and uses a local Qwen model to extract structured component records. The saved results cover selected examples; they are not a complete extraction of every hardware set in the archive. The input archive is not tracked in this repository; place the supplied `data.zip` in the project root before running the scripts.

## Setup

The PDF inspection and segmentation stages require Python 3.10+ and PyMuPDF. The tested environment used Python 3.12.1 and PyMuPDF 1.28.2. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The structured extraction stage uses Qwen3-4B-Instruct-2507 locally through MLX-LM. Running it requires an Apple Silicon Mac with macOS/Metal, MLX-LM, and local 4-bit model weights (about 2.1 GB, plus runtime memory). The tested MLX-LM version was 0.32.2. The project does not call a hosted inference API.

Install MLX-LM into the project virtual environment:

```bash
.venv/bin/python -m pip install mlx-lm
```

Download the model once if it is not already at `.models/Qwen3-4B-Instruct-2507-4bit`:

```bash
.venv/bin/hf download mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --local-dir .models/Qwen3-4B-Instruct-2507-4bit
```

## Run the extraction pipeline

Run from the project root. The first two stages prepare candidates across the PDFs. The last stage runs local LLM extraction on the six sets in its current sample configuration:

```bash
.venv/bin/python inspect_hardware_pages.py
.venv/bin/python segment_hardware_sets.py
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python extract_mvp_llm.py
```

The Qwen stage reads the saved `hardware_sets.jsonl` regions, adds source-page context and available table geometry, validates the model's structured JSON, and saves source and validation details. It retries malformed or schema-invalid responses up to two times. Deterministic-parser disagreements are reported for review and do not trigger retries. The current runner processes its configured examples; it does **not** run LLM extraction over every segmented candidate in the archive.

| Stage | Main outputs |
|---|---|
| PDF page inspection | `candidate_pages.jsonl`, `candidate_pages.md` |
| Hardware-set segmentation | `hardware_sections.jsonl`, `hardware_sets.jsonl`, `hardware_set_segmentation_report.md` |
| Local Qwen structured extraction (six configured sets) | `mvp_llm_extractions.json`, `mvp_llm_comparison.md` |

The scripts overwrite their default outputs when rerun. Preserve copies if you need earlier runs.

## Supporting parser and saved results

`extract_sample_project_sets.py` is a deterministic parser for two representative formats: JC Ryan 2 list schedules and Roselle Public Library tables. It produces `sample_hardware_sets.json` and is useful as a review reference; it is not the LLM extraction stage.

The tracked final output lets reviewers inspect an extraction without installing MLX-LM or running inference:

- [Final focused five-sample JSON](five_sample_rerun_final.json): selected LLM records with source references and supporting metadata.
- [Submission summary](SUBMISSION_SUMMARY.md): corpus counts, evaluation results, and limitations.
- [System design](SYSTEM_DESIGN.md): how the scripts fit together and the current extraction scope.

The five-sample JSON is a saved run; the current six-set runner does not reproduce that exact selection. Detailed 20-sample and source-QA artifacts from earlier evaluations are not included in this repository; their relevant findings are summarized in `SUBMISSION_SUMMARY.md`.

## Evaluation and limitations

The five-sample manual review matched 31 of 31 extracted component rows and found 31 of 33 source rows across four countable selected sets (row precision 31/31; row recall 31/33, about 94%). This small, selected review is not corpus-wide accuracy. In a separate representative run, 20 model responses were schema-valid; schema validity does not establish that their contents are correct or complete.

Segmentation missed searchable schedules in SJC Well Behavioral and StarHardware; Woodridge Public Works remains inconclusive. Of 17,637 pages, 17,338 had extractable text and 299 did not; OCR was not used. Complex tables, merged cells, page continuations, unquantified rows, and manufacturer/product/finish mapping remain unreliable. There is no comprehensive labeled reference set, so corpus-wide precision and recall are unknown.
