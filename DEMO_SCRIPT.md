# 2–3 minute demo video script

Use the precomputed outputs; do not run model inference during the recording. The saved JSON includes source-page text, component source pages, and raw component text.

## Before recording

From the project root, extract the SAT TDP PDF to a temporary path and open it in Preview:

```bash
unzip -p data.zip "Fresco Coding Challenge (Hardware Sets)/SAT TDP/2025.12.19 - SAT TDP - Project Manual.pdf" > /tmp/sat-tdp-demo.pdf
open -a Preview /tmp/sat-tdp-demo.pdf
```

Navigate to PDF page **734**. Keep `five_sample_rerun_final.json`, `README.md`, and `SYSTEM_DESIGN.md` ready in the editor.

## Walkthrough

**0:00–0:25 — Input and goal**  
Show `data.zip` and `spec.txt`. Say: “The input is a set of construction specification PDFs. The goal is to identify likely hardware sets and preserve component fields with source locations.”

**0:25–0:55 — Pipeline**  
Show `inspect_hardware_pages.py`, `segment_hardware_sets.py`, and `extract_mvp_llm.py`, then the pipeline diagram/description in `SYSTEM_DESIGN.md`. Say: “The first two stages find candidate pages and set regions. The deterministic sample parser and local Qwen experiment are separate extraction experiments.” Point out that the checked-in outputs are available without a model run.

**0:55–1:35 — Source PDF**  
In Preview, show page 734 and the `Hardware Group No. 715TW` schedule. Point to the `QTY`, `DESCRIPTION`, `CATALOG NUMBER`, `FINISH`, and `MFR` columns, especially the exit-device finish `626` and closer finish `689`.

**1:35–2:15 — JSON and traceability**  
Open `five_sample_rerun_final.json`. Find `set_number` 715TW, then show its component rows, `source_page: 734`, `raw_component_text`, and saved source-page excerpt. Compare the finish values to the visible PDF columns. Mention that `full_sample_representative_extractions.json` preserves the original 20-sample run.

**2:15–2:45 — Results and limits**  
Show `five_sample_manual_review.md` and `SUBMISSION_SUMMARY.md`. Say: “The small manual review found 31 matching rows out of 31 extracted and 31 of 33 source rows across four countable examples. That is a selected sample only, not corpus-wide accuracy. Known segmentation misses include SJC Well Behavioral and StarHardware.”

**2:45–3:00 — Close**  
Show the README run commands and state that local Qwen inference requires Apple Silicon/Metal and the downloaded local model; the precomputed evaluation is viewable without inference.
