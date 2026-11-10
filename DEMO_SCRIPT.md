# Three-minute demo script

Use the existing `five_sample_rerun_final.json`; do not run inference. Keep the JSON open beside Preview so each extracted record can be compared with its source page. The commands below copy PDFs from the archive into `/tmp`; the archive remains unchanged.

## Prepare the three source PDFs

Run each command from the project root:

```bash
unzip -p data.zip "Fresco Coding Challenge (Hardware Sets)/SAT TDP/2025.12.19 - SAT TDP - Project Manual.pdf" > /tmp/sat-tdp-demo.pdf
```

```bash
unzip -p data.zip "Fresco Coding Challenge (Hardware Sets)/81-85 Bridgeport/08-70-00-Hardware-Schedule.pdf" > /tmp/bridgeport-demo.pdf
```

```bash
unzip -p data.zip "Fresco Coding Challenge (Hardware Sets)/2353 Gerrard Street Shelter/2.02 2535 Gerrard Shelter-Issued for Tender_5-Architectural Specifications.pdf" > /tmp/gerrard-demo.pdf
```

Open each PDF in Preview as you reach its segment and navigate to the stated PDF page. In `five_sample_rerun_final.json`, use the `samples` array indices below (zero-based) and expand each sample's `llm` object.

## Walkthrough and narration

**0:00–0:25 — Goal and pipeline**  
Show `data.zip`, then the flow in `SYSTEM_DESIGN.md`. Say: “PyMuPDF reads PDF pages, heuristics find likely hardware sections and set regions, and a local Qwen experiment structures selected sets. The saved results include source-page references and raw text for review.”

**0:25–1:05 — SAT TDP, group 715TW**  
Open the first PDF:

```bash
open -a Preview /tmp/sat-tdp-demo.pdf
```

Go to page **734**. In the JSON, open `samples[3].llm` (find `"set_number": "715TW"`). Compare the exit-device finish **626** and surface-closer finish **689** with the printed `FINISH` column. Say: “The wrapped catalog text no longer shifts into the finish field.”

**1:05–1:35 — Bridgeport, Heading #1**  
Open the second PDF:

```bash
open -a Preview /tmp/bridgeport-demo.pdf
```

Go to page **3**. In the JSON, open `samples[1].llm` (find `"set_number": "Heading #1"`). Show the seven component rows and `mfr: null`. Say: “The schedule does not tie a manufacturer to these rows, so the output leaves manufacturer blank instead of assigning one from the document-wide index.”

**1:35–2:05 — 2353 Gerrard Shelter, set AL 01**  
Open the third PDF:

```bash
open -a Preview /tmp/gerrard-demo.pdf
```

Go to page **165**. In the JSON, open `samples[0].llm` (find `"set_number": "AL 01"`). Show the power-transfer row (`finish: ALM`, `mfr: Hager Companies`) and the exit-device row (`finish: 630`, `mfr: Detex`); then show the code lists on page 164 if time permits. Say: “The complete set identifier and these code meanings are supported by the printed heading, aligned cells, and explicit legends.”

**2:05–2:45 — Results and limitations**  
Show `five_sample_manual_review.md`. Say: “All five outputs are schema-valid, but they are not all fully correct. A manual review matched 31 of 31 extracted rows and found 31 of 33 source rows across four countable reviewed sets: 31/31 row precision and 31/33 row recall. Those figures apply only to those four selected sets; the Gerrard schedule was excluded from the counts because it mixes hardware with coordination entries. Roselle still misses two unquantified rows, and the corpus has known segmentation misses in SJC Well Behavioral and StarHardware. We have not measured corpus-wide accuracy.”

**2:45–2:55 — Close**  
Point reviewers to `README.md` for setup and commands, and note that these precomputed results can be inspected without running the local model.
