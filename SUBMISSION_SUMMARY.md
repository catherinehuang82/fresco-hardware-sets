# Submission summary

## Functionality

- Reads PDFs inside `data.zip` with PyMuPDF and records 1-based page locations.
- Uses heuristic page filtering and set segmentation to prepare likely hardware-set regions.
- Uses local Qwen/MLX as the structured component-extraction stage for selected sets, with JSON/schema validation, bounded retries, and source references. The checked-in runner is configured for six sets; it does not process every candidate in the archive.
- Includes deterministic parsers for JC Ryan 2 and Roselle Public Library as supporting outputs and comparison references, plus separate source-based QA artifacts.

## Evaluation snapshot

- Corpus inventory: 43 PDFs, 17,637 pages, grouped in 21 project folders.

### Saved segmentation counts by PDF

Counts below come from the existing `hardware_sets.jsonl` and `hardware_sections.jsonl`; no inspection or segmentation was rerun. “Set candidates” counts segmented records, not verified actual sets. “Review-fallback regions” counts section records with `start_type: unresolved_candidate_page`; these broad unresolved page regions are not set candidates and may be false positives.

| Project / PDF | Set candidates | Review-fallback regions |
|---|---:|---:|
| 2353 Gerrard Street Shelter / `2.02 2535 Gerrard Shelter-Issued for Tender_5-Architectural Specifications.pdf` | 35 | 21 |
| 2353 Gerrard Street Shelter / `Hdw Spec & Sch-IFT_5.pdf` | 35 | 18 |
| 81-85 Bridgeport / `08-10-00-Hollow-Metal-Doors-Frames_Rev_0.pdf` | 0 | 1 |
| 81-85 Bridgeport / `08-20-00-Wood-Doors_Rev_0.pdf` | 0 | 0 |
| 81-85 Bridgeport / `08-70-00-Hardware-Schedule.pdf` | 87 | 2 |
| 81-85 Bridgeport / `08-70-00-Hardware-Schedule_Rev_0.pdf` | 87 | 2 |
| AMI _Copy_ / `c43c36d9-000_Full_Volume_ATC_Renovation_Bid_Specs_Volume_1__1_.pdf` | 44 | 32 |
| Forest Park School / `Project Manual (1).pdf` | 2 | 18 |
| HFH DG - HOSPITAL / `08 71 00 - DOOR HARDWARE.pdf` | 190 | 33 |
| HFH DG - HOSPITAL / `08 71 00.01 - DOOR HARDWARE INDEX cut up.pdf` | 0 | 0 |
| JC Ryan 2 / `08 11 13 - HOLLOW METAL DOORS AND FRAMES.pdf` | 0 | 6 |
| JC Ryan 2 / `08 14 16 - FLUSH WOOD DOORS.pdf` | 0 | 2 |
| JC Ryan 2 / `087100 - Door Hardware-6.pdf` | 38 | 24 |
| Livelle Mulholland - Life Plan Community / `2025-12-12_Livelle_Bid_Set_Project_Manual_Vol1_rev1.pdf` | 162 | 39 |
| Livelle Mulholland - Life Plan Community / `2025-12-12_Livelle_Bid_Set_Project_Manual_Vol2.pdf` | 0 | 3 |
| Livelle Mulholland - Life Plan Community / `2025-12-12_Livelle_Bid_Set_Project_Manual_Vol3_rev1.pdf` | 0 | 5 |
| Livelle Mulholland - Life Plan Community / `2025-12-12_Livelle_Bid_Set_Project_Manual_Vol4.pdf` | 0 | 1 |
| Lyons Township HS / `Project Manual (1).pdf` | 29 | 30 |
| Market View Apartments / `S_251107 Market View Prelim Project Manual_pdf.pdf` | 25 | 38 |
| Morris Bank / `030f2d1d-Morris_Bank_Macon_-Spec_Manual_Issued_for_Const._1-26-26_FULL_SPECS.pdf` | 50 | 41 |
| National Doors and Hardware / `15e2b8ac-FS17_Specs_V1.pdf` | 15 | 19 |
| Roselle Public Library / `081113_FL_-_Hollow_Metal_Doors_and_Frames.pdf` | 0 | 1 |
| Roselle Public Library / `081416_FL_-_Flush_Wood_Doors.pdf` | 0 | 2 |
| Roselle Public Library / `083113_FL_-_Access_Doors_and_Frames.pdf` | 0 | 0 |
| Roselle Public Library / `087100_FL_-_Door_Hardware_IFB_REVISED.pdf` | 33 | 14 |
| SAT TDP / `2025.12.19 - SAT TDP - Project Manual.pdf` | 186 | 47 |
| SJC Well Behavioral / `89671ede-20260218_SJC_BeWell_Bldg_B_85__DESIGN_UPDATE_-_SPECIFICATIONS.pdf` | 0 | 80 |
| Shubie Center / `e2231795-IFT_Specs.pdf` | 3 | 4 |
| StarHardware / `9839d1a1-Division_8_Specs_-_Commons_Lane.pdf` | 0 | 102 |
| The Door Company _Copy_ / `Vantage TX-22 Div 01, 08.pdf` | 3 | 62 |
| USI / `c9634958-Radnet_Building_-_Specs.pdf` | 2 | 13 |
| Valor Acres Building E / `081113-HOLLOW-METAL-DOORS-AND-FRAMES_Rev_1.pdf` | 0 | 0 |
| Valor Acres Building E / `081416-WOOD-DOORS-_Rev_1.pdf` | 0 | 0 |
| Valor Acres Building E / `083113-ACCESS-DOORS-AND-FRAMES_Rev_1.pdf` | 0 | 1 |
| Valor Acres Building E / `084113-ALUMINUM-FRAMED-ENTRANCES-AND-STOREFRONTS_Rev_1.pdf` | 0 | 1 |
| Valor Acres Building E / `084126-ALL-GLASS-ENTRANCES_Rev_0.pdf` | 0 | 0 |
| Valor Acres Building E / `085313-RESIDENTIAL-WINDOWS-AND-DOORS-_Rev_1.pdf` | 0 | 2 |
| Valor Acres Building E / `087100-DOOR-HARDWARE_Rev_2.pdf` | 37 | 6 |
| Valor Acres Building E / `088000-GLAZING_Rev_1.pdf` | 0 | 0 |
| Valor Acres Building E / `088300-MIRRORS_Rev_1.pdf` | 0 | 0 |
| Valor Acres Building E / `088713-DECORATIVE-WINDOW-FILMS_Rev_0.pdf` | 0 | 0 |
| Village of Oswego New Public Works Facility  _Copy_ / `SPECIFICATIONS VOLUME 1.pdf` | 40 | 46 |
| Woodridge Public Works / `1548 - Specs - VOW - New Public Works Facility  - B&P.pdf` | 0 | 36 |
| **Aggregate** | **1,103** | **752** |

Each zero means no record of that type in the saved heuristic output, not proof that the PDF contains no hardware set. Zero set candidates can coexist with unresolved review regions, and even zeros in both columns do not establish that the PDF has no relevant content.

### Comparison Against Expected Project Scale

The founder's 5–30 sets and 3–15 components per set are typical ranges, not pass/fail limits. The table groups candidate records by project folder and sums across its PDFs. Component counts are the number of component rows in existing extracted outputs (not quantities); sampled outputs do not cover every candidate. The unresolved regions remain separate and must not be counted as sets.

| Project / specbook | PDFs | Raw candidate records | Adjusted likely unique records | Unresolved regions | Existing extracted component rows per set |
|---|---:|---:|---:|---:|---|
| 2353 Gerrard Street Shelter | 2 | 70 | 35 | 39 | 2 sets: 20–31 |
| 81-85 Bridgeport | 4 | 174 | 87 | 5 | 2 sets: 7–9 |
| AMI _Copy_ | 1 | 44 | 44 | 32 | 1 set: 4 |
| Forest Park School | 1 | 2 | 2 | 18 | 1 set: 2 (<3) |
| HFH DG - HOSPITAL | 2 | 190 | 190 | 33 | 1 set: 9 |
| JC Ryan 2 | 3 | 38 | 38 | 32 | 38 parsed sets: 0–12; 2 below 3 |
| Livelle Mulholland - Life Plan Community | 4 | 162 | 162 | 48 | 1 set: 9 |
| Lyons Township HS | 1 | 29 | 29 | 30 | 1 set: 1 (<3) |
| Market View Apartments | 1 | 25 | 25 | 38 | 1 set: 19 (>15) |
| Morris Bank | 1 | 50 | 50 | 41 | 1 set: 10 |
| National Doors and Hardware | 1 | 15 | 15 | 19 | 1 set: 9 |
| Roselle Public Library | 4 | 33 | 33 | 17 | 33 parsed sets: 1–10; 1 below 3 |
| SAT TDP | 1 | 186 | 186 | 47 | 1 set: 10 |
| SJC Well Behavioral | 1 | 0 | 0 | 80 | Unavailable; no extracted set output |
| Shubie Center | 1 | 3 | 3 | 4 | 1 set: 16 (>15) |
| StarHardware | 1 | 0 | 0 | 102 | Unavailable; no extracted set output |
| The Door Company _Copy_ | 1 | 3 | 3 | 62 | 1 set: 1 (<3) |
| USI | 1 | 2 | 2 | 13 | 1 set: 10 |
| Valor Acres Building E | 10 | 37 | 37 | 10 | 1 set: 7 |
| Village of Oswego New Public Works Facility _Copy_ | 1 | 40 | 40 | 46 | 1 set: 20 (>15) |
| Woodridge Public Works | 1 | 0 | 0 | 36 | Unavailable; no extracted set output |
| **Aggregate** | **43** | **1,103** | **981** | **752** | **89 matched extracted-set records with countable component arrays** |

The raw counts in the preceding column preserve the original per-PDF sum. The adjusted column removes exact repeats only when the same set ID and normalized candidate text occur in different PDFs in the same project folder. This identifies 35 repeated Gerrard records across its two PDFs and 87 repeated Bridgeport records across the schedule and its revision; the identical IDs, text, and corresponding page locations support treating these as duplicate copies for this estimate. It does not merge unresolved regions or alter the saved segmentation output. The adjusted aggregate is 981 records.

Using adjusted counts, eleven project folders exceed 30 candidates, three fall within 5–30, and seven are below 5. The remaining high counts may reflect large schedules or segmentation that splits/duplicates regions. These are heuristic counts, not verified set totals. Low or zero counts also are not evidence that a project lacks hardware: fallback regions remain in several such folders, and known segmentation gaps include SJC Well Behavioral and StarHardware.

Within individual PDFs, the repeated ID `1` in Forest Park appears once in unrelated fastener-specification text and once as a hardware-set heading; the repeated `Group 1` in SAT appears in miscellaneous-material specifications, not as schedule set IDs. They are not duplicate hardware candidates on the available text. Morris Bank has two `MISC` candidates with nearly identical component text on pages 263 and 287, but their door-reference context differs (`Other Door #MISC` versus `Doors: MISC`), so this possible duplicate remains unadjusted. Ten records span adjacent pages and are already represented as one candidate each (JC Ryan 2 `EX-2.0`; HFH DG groups 017, 055, 063, 084, 090, 096, 122, 130, and 142); no separate adjacent-page duplicate record was identified for these continuations. Other candidates with distinct IDs or nonmatching contents were retained as distinct.

Among the 89 existing extracted-set records that could be matched to these projects, 6 have fewer than 3 component rows and 5 have more than 15; 78 fall within the typical range. These are output row-count observations, not correctness measurements. Gerrard's 20-row set includes security/coordination entries, so it is not directly comparable to a count of hardware components. Most segmented candidates have no associated component extraction output, and component counts are unavailable for SJC Well Behavioral, StarHardware, and Woodridge Public Works. Low counts may indicate incomplete extraction or a false-positive candidate; high counts may reflect merged rows, non-hardware entries, or a genuinely longer schedule. Source-grounded review would be needed to distinguish these explanations.

- Original LLM evaluation: one representative set from each of 20 segmented PDFs; all 20 outputs were schema-valid. This is not evidence of 20 correct extractions.
- Latest five-sample source review: across four countable selected sets, 31/31 extracted component rows matched source rows (100% row precision) and 31/33 source rows were represented (about 94% row recall). Gerrard was excluded from those counts because its schedule mixes hardware and coordination/security entries.
- These are small, selected-sample results. No corpus-wide precision or recall has been measured.

## Known limitations

- Segmentation misses searchable schedules in SJC Well Behavioral and StarHardware. Woodridge Public Works remains inconclusive.
- 299 pages had no extractable text; OCR was not used.
- The latest Roselle sample still misses two unquantified rows. Table continuations, merged cells, component notes, and manufacturer/product/finish mapping remain uncertain.
- JSON/schema validity and automated QA flags do not establish completeness or factual correctness.

See [README.md](README.md) for setup and commands, [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) for the architecture, and [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for a short presentation walkthrough.
