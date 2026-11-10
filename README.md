# Hardware-set extraction take-home

This project reads construction specifications from `data.zip`, identifies likely hardware schedule pages and set regions, and produces structured JSON for selected examples. The included outputs are evaluation artifacts; they are not a claim of complete extraction.

## Setup

The rule-based pipeline requires Python 3.10+ and PyMuPDF. The tested environment used Python 3.12.1 and PyMuPDF 1.28.2. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

`requirements.txt` contains only the required PDF dependency (`PyMuPDF`). Local LLM inference is optional and additionally requires an Apple Silicon Mac with macOS/Metal available, MLX-LM, and about 2.1 GB of local 4-bit model weights (plus runtime memory). The tested inference environment used `mlx-lm` 0.32.2. No inference API is used.

## Run the rule-based pipeline

For a reproducible PDF-to-JSON run, execute these stages in order from the project root:

```bash
.venv/bin/python inspect_hardware_pages.py
.venv/bin/python segment_hardware_sets.py
.venv/bin/python extract_sample_project_sets.py
```

The first two stages inspect and segment the PDFs throughout the archive. The deterministic JSON stage currently targets JC Ryan 2 and Roselle Public Library. The commands overwrite their default outputs; preserve copies if you need previous runs. To inspect available options, use `--help` on a script.

| Stage | Output files |
|---|---|
| PDF page inspection | `candidate_pages.jsonl`, `candidate_pages.md` |
| Set segmentation | `hardware_sections.jsonl`, `hardware_sets.jsonl`, `hardware_set_segmentation_report.md` |
| Two-project deterministic extraction | `sample_hardware_sets.json`, `sample_extraction_evaluation.md` |

For a quick demonstration without rescanning the corpus or running a model, inspect the included [five-sample result](five_sample_rerun_final.json), [manual before/after review](five_sample_manual_review.md), and [20-PDF evaluation](full_sample_evaluation_report.md).

## Optional local Qwen run

The included local runner uses precomputed segments and runs six configured examples; it does not rerun PDF discovery or reproduce the 20-PDF evaluation. Install MLX-LM in the virtual environment:

```bash
.venv/bin/python -m pip install mlx-lm
```

Download the model once if it is not already at `.models/Qwen3-4B-Instruct-2507-4bit`:

```bash
.venv/bin/hf download mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --local-dir .models/Qwen3-4B-Instruct-2507-4bit
```

Run with Hugging Face and Transformers offline mode enabled:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python extract_mvp_llm.py
```

This writes `mvp_llm_extractions.json` and `mvp_llm_comparison.md`, replacing those six-example experiment outputs. The saved `five_sample_rerun_final.json` is a separate, completed five-sample rerun; there is no standalone runner in this project for reproducing that exact selection.

## Evaluation artifacts

- [Final targeted five-sample JSON](five_sample_rerun_final.json): latest extraction result for five reviewed layouts.
- [Five-sample manual review](five_sample_manual_review.md): before/after findings and the bounded row-level estimate.
- [Full-sample JSON](full_sample_representative_extractions.json): original 20 representative sets, preserved unchanged.
- [Full-sample evaluation report](full_sample_evaluation_report.md), [source QA records](full_sample_source_qa.jsonl), and [PDF inventory](full_sample_pdf_inventory.json).
- [Corpus structure and OCR diagnostic](corpus_structure_ocr_diagnostic.md).
- [Submission summary](SUBMISSION_SUMMARY.md) and [short demo script](DEMO_SCRIPT.md).

## Limitations

The five-sample manual comparison found 31/31 extracted row matches and 31/33 source rows across four countable reviewed sets (row precision 100%, row recall about 94%). This is a tiny, selected sample and is **not** corpus-wide accuracy. The original 20-sample run was 20/20 schema-valid; schema validity does not mean source correctness.

Segmentation missed searchable schedules in SJC Well Behavioral and StarHardware. Woodridge Public Works remains inconclusive. Of 17,637 pages, 299 had no extractable text; OCR was not used. Field mapping, unquantified component rows, merged table cells, continuations, and schedule completeness remain unreliable. No comprehensive labeled reference set is available, so corpus-wide precision and recall are unknown.
