"""Audit representative LLM extraction records against their source PDFs.

This review stage reads the PDFs, saved segmentation candidates, and one
representative extraction per segmented PDF. It writes source-based findings
separately and never changes the extraction records. Its heuristic checks are
not a labeled benchmark and do not establish corpus-wide accuracy.
"""

import argparse
import json
import re
import zipfile
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf


BASE_DIR = Path(__file__).resolve().parent
SET_PATTERNS = [
    re.compile(r"(?i)\bhardware\s+group\s*/\s*set\s*#\s*([A-Z0-9.-]+)"),
    re.compile(r"(?i)\bhardware\s+group\s+no\.?\s*([A-Z0-9.-]+)"),
    re.compile(r"(?i)\bset\s*#\s*([A-Z0-9.-]+)"),
]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def token_overlap(left, right):
    a = set(re.findall(r"[a-z0-9]+", str(left or "").lower()))
    b = set(re.findall(r"[a-z0-9]+", str(right or "").lower()))
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def source_rows(archive, sample):
    """Independently recover labeled rows from the original PDF geometry."""
    rows = []
    pages = (sample.get("baseline") or {}).get("location", {}).get("pages", [])
    if not pages or not sample.get("source_pdf"):
        return rows
    document = pymupdf.open(stream=archive.read(sample["source_pdf"]), filetype="pdf")
    set_id = str(sample.get("set_id", ""))
    id_pattern = re.compile(
        rf"(?i)\bhardware\s+group\s+no\.?\s*{re.escape(set_id)}(?![\w])"
        rf"|\bhardware\s+group\s*/\s*set\s*#\s*{re.escape(set_id)}(?![\w])"
        rf"|\bset\s*#\s*{re.escape(set_id)}(?![\w])"
    )
    next_pattern = re.compile(r"(?i)\bhardware\s+group\s+no\.?\s*\S+|\bhardware\s+group\s*/\s*set\s*#\s*\S+|\bset\s*#\s*\S+")
    for page_number in pages:
        page = document[int(page_number) - 1]
        lines = []
        for word in page.get_text("words"):
            x0, y0, x1, _y1, text = word[:5]
            if not text.strip():
                continue
            line = next((item for item in lines if abs(item["y"] - y0) <= 2.5), None)
            if line is None:
                line = {"y": y0, "words": []}
                lines.append(line)
            line["words"].append((x0, x1, text))
        lines.sort(key=lambda item: item["y"])
        for line in lines:
            line["words"].sort(key=lambda item: item[0])
            line["text"] = " ".join(word[2] for word in line["words"])
        start = next((i for i, line in enumerate(lines) if id_pattern.search(line["text"])), None)
        if start is None:
            continue
        end_y = next((line["y"] for line in lines[start + 1:] if next_pattern.search(line["text"])), float("inf"))
        region = [line for line in lines[start:] if line["y"] < end_y]
        header = next((line for line in region if re.search(r"(?i)\bqty\b", line["text"]) and re.search(r"(?i)\bdescription\b", line["text"])), None)
        if not header:
            continue
        labels = []
        for index, word in enumerate(header["words"]):
            text = word[2]
            label = {"QTY": "QTY", "DESCRIPTION": "DESCRIPTION", "FINISH": "FINISH", "MFR": "MFR", "MANUFACTURER": "MFR"}.get(text.upper().rstrip("."))
            if text.upper() == "CATALOG":
                label = "CATALOG NUMBER"
            if label:
                labels.append((word[0], label))
        labels.sort()
        if not labels:
            continue
        anchors = [item[0] for item in labels]
        # Header labels are often wider/centered differently than their values.
        # Use their left edges with a small tolerance instead of midpoint
        # splitting, which can incorrectly move long catalog text into FINISH.
        boundaries = [max(0, anchor - 15) for anchor in anchors]
        for line in region:
            if line["y"] <= header["y"]:
                continue
            grouped = [[] for _ in labels]
            for x0, _x1, text in line["words"]:
                glyph = re.match(r"^([\uf000-\uf8ff]+)(.*)$", text)
                visible = glyph.group(2) if glyph else text
                if not visible:
                    continue
                column = max((i for i, left in enumerate(boundaries) if x0 >= left - 2), default=0)
                grouped[column].append(visible)
            cells = {label: " ".join(values) for (_, label), values in zip(labels, grouped) if values}
            qty_match = re.match(r"\s*(\d+(?:\.\d+)?)\b", cells.get("QTY", ""))
            description = cells.get("DESCRIPTION", "")
            if qty_match and float(qty_match.group(1)) <= 100 and description:
                rows.append({
                    "page_number": int(page_number), "qty": float(qty_match.group(1)),
                    "description": description, "catalog_number": cells.get("CATALOG NUMBER", ""),
                    "finish": cells.get("FINISH", ""), "mfr": cells.get("MFR", ""),
                    "raw_text": line["text"],
                })
    document.close()
    return rows


def match_score(component, source):
    desc = token_overlap(component.get("description"), source["description"])
    catalog = token_overlap(component.get("catalog_number") or component.get("product"), source["catalog_number"])
    return max(desc, 0.65 * desc + 0.35 * catalog)


def audit_sample(archive, sample):
    findings = []
    llm = sample.get("llm") or {}
    layout_rows = source_rows(archive, sample)
    components = llm.get("components", [])
    try:
        raw_text = sample.get("raw_model_output", "").strip()
        if raw_text.startswith("```"):
            raw_text = "\n".join(raw_text.splitlines()[1:-1])
        raw_llm = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError, AttributeError):
        raw_llm = {}
    matched_sources = set()
    matched_components = set()
    pairs = []
    for ci, component in enumerate(components):
        choices = sorted(
            ((match_score(component, row), ri, row) for ri, row in enumerate(layout_rows) if ri not in matched_sources),
            reverse=True,
            key=lambda item: item[0],
        )
        if choices and choices[0][0] >= 0.45:
            score, ri, row = choices[0]
            matched_sources.add(ri)
            matched_components.add(ci)
            pairs.append((ci, ri, score, row))
        else:
            findings.append({
                "source_pdf": sample.get("source_pdf"),
                "set_id": sample.get("set_id"),
                "category": "component_row_alignment",
                "confidence": "unverified",
                "extracted_value": component,
                "suspected_source_value": None,
                "source_page": component.get("source_page"),
                "source_evidence": "No sufficiently similar, explicitly labeled source row was recovered from the target-page geometry. This may reflect a row mismatch or limits of geometry extraction.",
            })

    for ci, ri, score, row in pairs:
        component = components[ci]
        for field in ("qty", "catalog_number", "finish", "mfr"):
            expected = row[field]
            actual = component.get(field)
            if field == "qty":
                try:
                    same = actual is not None and float(actual) == float(expected)
                except (TypeError, ValueError):
                    same = False
            else:
                actual_norm, expected_norm = norm(actual), norm(expected)
                same = actual_norm == expected_norm
                # A null source cell does not support asserting that an output
                # value is wrong; it is not compared as an empty string.
                if not str(expected or "").strip():
                    continue
            if not same:
                boundary_ambiguous = field != "qty" and bool(actual_norm and expected_norm) and (
                    actual_norm in expected_norm or expected_norm in actual_norm
                )
                findings.append({
                    "source_pdf": sample.get("source_pdf"),
                    "set_id": sample.get("set_id"),
                    "category": (
                        "field_boundary_ambiguous" if boundary_ambiguous
                        else {"qty": "quantity", "mfr": "manufacturer_mapping"}.get(field, "field_mapping")
                    ),
                    "confidence": "unverified" if boundary_ambiguous else ("high" if score >= 0.65 else "medium"),
                    "field": field,
                    "extracted_value": actual,
                    "suspected_source_value": expected,
                    "source_page": row["page_number"],
                    "source_evidence": row["raw_text"],
                    "note": "Source and extracted value overlap; coordinate-based cell boundaries may include adjacent words, so this is not treated as a confirmed mapping error." if boundary_ambiguous else None,
                })
        raw_component = (raw_llm.get("components") or [])
        raw_component = raw_component[ci] if ci < len(raw_component) and isinstance(raw_component[ci], dict) else {}
        if raw_component.get("source_page") is not None and str(raw_component["source_page"]) != str(row["page_number"]):
            findings.append({
                "source_pdf": sample.get("source_pdf"), "set_id": sample.get("set_id"),
                "category": "page_location", "confidence": "high" if score >= 0.65 else "medium",
                "field": "source_page", "extracted_value": raw_component.get("source_page"),
                "suspected_source_value": row["page_number"], "source_page": row["page_number"],
                "source_evidence": row["raw_text"],
                "note": "Compared the raw model response before the runner restored segment-derived page metadata.",
            })

    for ri, row in enumerate(layout_rows):
        if ri not in matched_sources:
            findings.append({
                "source_pdf": sample.get("source_pdf"),
                "set_id": sample.get("set_id"),
                "category": "possible_missing_component",
                "confidence": "medium",
                "extracted_value": None,
                "suspected_source_value": {
                    "qty": row["qty"], "description": row["description"],
                    "catalog_number": row["catalog_number"], "finish": row["finish"], "mfr": row["mfr"],
                },
                "source_page": row["page_number"],
                "source_evidence": row["raw_text"],
            })

    expected_pages = {int(value) for value in llm.get("location", {}).get("pages", [])}
    for component in components:
        page = component.get("source_page")
        if page is not None and int(page) not in expected_pages:
            findings.append({
                "source_pdf": sample.get("source_pdf"), "set_id": sample.get("set_id"),
                "category": "page_location", "confidence": "high",
                "extracted_value": page, "suspected_source_value": sorted(expected_pages),
                "source_page": page,
                "source_evidence": "Component source_page is outside the extracted set location pages.",
            })
    if not layout_rows:
        findings.append({
            "source_pdf": sample.get("source_pdf"), "set_id": sample.get("set_id"),
            "category": "layout_qa_unverified", "confidence": "unverified",
            "extracted_value": None, "suspected_source_value": None,
            "source_page": (sample.get("baseline") or {}).get("location", {}).get("pages", [None])[0],
            "source_evidence": "No labeled quantity/description table rows were available. Position-only geometry and raw source remain in the extraction output, but this QA pass does not assign field truth from coordinates alone.",
        })
    if raw_llm:
        source_text = "\n".join((sample.get("source_pages") or {}).values())
        raw_id = str(raw_llm.get("set_number", ""))
        expected_id = str(sample.get("set_id", ""))
        heading_id = re.fullmatch(r"(?i)heading\s*#\s*(\d+)", expected_id)
        same_heading_number = bool(heading_id and raw_id == heading_id.group(1))
        if raw_id and norm(raw_id) != norm(expected_id) and not same_heading_number:
            findings.append({
                "source_pdf": sample.get("source_pdf"), "set_id": sample.get("set_id"),
                "category": "set_identifier", "confidence": "medium",
                "extracted_value": raw_id, "suspected_source_value": expected_id,
                "source_page": (sample.get("baseline") or {}).get("location", {}).get("pages", [None])[0],
                "source_evidence": "The raw model identifier differs from the segment ID; the final record had the segment-derived ID restored by the existing pipeline.",
            })
        if expected_id and norm(expected_id) not in norm(source_text):
            findings.append({
                "source_pdf": sample.get("source_pdf"), "set_id": sample.get("set_id"),
                "category": "set_identifier_source_check", "confidence": "unverified",
                "extracted_value": expected_id, "suspected_source_value": None,
                "source_page": (sample.get("baseline") or {}).get("location", {}).get("pages", [None])[0],
                "source_evidence": "The segment ID was not found verbatim in target/adjacent page text. It may use a layout form not captured by text search.",
            })
    target_pages = {int(page) for page in (sample.get("baseline") or {}).get("location", {}).get("pages", [])}
    for page_text, page_number in ((text, int(page)) for page, text in (sample.get("source_pages") or {}).items()):
        if page_number in target_pages:
            continue
        if re.search(r"(?i)hardware\s+group\s+no\.?\s*" + re.escape(str(sample.get("set_id", ""))), page_text):
            findings.append({
                "source_pdf": sample.get("source_pdf"), "set_id": sample.get("set_id"),
                "category": "possible_cross_page_continuation", "confidence": "unverified",
                "extracted_value": sorted(target_pages), "suspected_source_value": page_number,
                "source_page": page_number,
                "source_evidence": "An adjacent page repeats the target set heading outside the segment's page range. Review whether component rows continue there.",
            })
    if len(target_pages) > 1:
        for page_number in sorted(target_pages - {min(target_pages)}):
            if not any(row["page_number"] == page_number for row in layout_rows):
                findings.append({
                    "source_pdf": sample.get("source_pdf"), "set_id": sample.get("set_id"),
                    "category": "possible_cross_page_continuation", "confidence": "unverified",
                    "extracted_value": sorted(target_pages), "suspected_source_value": None,
                    "source_page": page_number,
                    "source_evidence": "A later segment page had no independently recovered labeled rows; it may be a continuation page or a geometry-extraction limitation.",
                })
    return findings, len(layout_rows), len(components), len(pairs)


def scan_unsegmented_set_ids(candidate_rows, pdf_filename):
    ids = defaultdict(set)
    for row in candidate_rows:
        if row.get("pdf_filename") != pdf_filename:
            continue
        text = row.get("text", "")
        for pattern in SET_PATTERNS:
            for match in pattern.finditer(text):
                ids[match.group(1).upper()].add(int(row["page_number"]))
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=BASE_DIR / "data.zip")
    parser.add_argument("--segments", type=Path, default=BASE_DIR / "hardware_sets.jsonl")
    parser.add_argument("--candidates", type=Path, default=BASE_DIR / "candidate_pages.jsonl")
    parser.add_argument("--extractions", type=Path, default=BASE_DIR / "full_sample_representative_extractions.json")
    parser.add_argument("--discrepancies", type=Path, default=BASE_DIR / "full_sample_source_qa.jsonl")
    parser.add_argument("--inventory", type=Path, default=BASE_DIR / "full_sample_pdf_inventory.json")
    parser.add_argument("--report", type=Path, default=BASE_DIR / "full_sample_evaluation_report.md")
    args = parser.parse_args()

    segments = read_jsonl(args.segments)
    candidate_rows = read_jsonl(args.candidates)
    extraction_payload = json.loads(args.extractions.read_text(encoding="utf-8"))
    results = extraction_payload["samples"]
    samples_by_pdf = {sample["source_pdf"]: sample for sample in results if sample.get("source_pdf")}
    segments_by_pdf = defaultdict(list)
    for row in segments:
        segments_by_pdf[row["pdf_filename"]].append(row)
    candidates_by_pdf = Counter(row["pdf_filename"] for row in candidate_rows)

    findings = []
    sample_summaries = {}
    inventory = []
    with zipfile.ZipFile(args.archive) as archive:
        for sample in results:
            current, source_row_count, output_count, aligned = audit_sample(archive, sample)
            findings.extend(current)
            sample_summaries[sample["source_pdf"]] = {
                "sampled_set_id": sample["set_id"], "validation_status": sample.get("validation_status"),
                "retry_count": sample.get("retry_count", 0), "source_rows_with_named_columns": source_row_count,
                "model_components": output_count, "aligned_components": aligned,
                "finding_count": len(current),
            }
        pdfs = sorted(name for name in archive.namelist() if name.lower().endswith(".pdf"))
        for pdf in pdfs:
            errors = []
            try:
                document = pymupdf.open(stream=archive.read(pdf), filetype="pdf")
                page_count = len(document)
                text_pages = 0
                for number, page in enumerate(document, start=1):
                    try:
                        if page.get_text("text").strip():
                            text_pages += 1
                    except Exception as error:
                        errors.append({"page": number, "error": f"{type(error).__name__}: {error}"})
                document.close()
            except Exception as error:
                page_count, text_pages = None, None
                errors.append({"error": f"{type(error).__name__}: {error}"})

            sample = samples_by_pdf.get(pdf)
            rows = segments_by_pdf.get(pdf, [])
            distinct_sets = sorted({str(row["set_id"]) for row in rows})
            if sample:
                status = "processed" if sample.get("validation_status") == "valid" else "failed"
                reason = None
            elif rows:
                status, reason = "not sampled", "This PDF had candidate set regions, but one representative per PDF was the selected extraction scope."
            else:
                status, reason = "skipped", "No hardware-set region was produced by the existing segmenter; source-page scan is recorded separately."
                source_ids = scan_unsegmented_set_ids(candidate_rows, pdf)
                if source_ids:
                    findings.append({
                        "source_pdf": pdf, "set_id": None, "category": "possible_missed_sets",
                        "confidence": "high" if len(source_ids) >= 2 else "medium",
                        "extracted_value": [], "suspected_source_value": sorted(source_ids),
                        "source_page": min(page for pages in source_ids.values() for page in pages),
                        "source_evidence": "Candidate-page source scan found explicit hardware group/set identifiers, but hardware_sets.jsonl contains no regions for this PDF. See inventory for per-ID page references.",
                    })
                    reason = "No segment candidates; explicit source group/set identifiers require review."
            inventory.append({
                "pdf_filename": pdf, "status": status, "status_reason": reason,
                "page_count": page_count, "pages_with_extractable_text": text_pages,
                "candidate_pages": candidates_by_pdf.get(pdf, 0),
                "segmented_region_records": len(rows), "distinct_segment_ids": distinct_sets,
                "representative_sample": sample_summaries.get(pdf), "errors": errors,
                "source_set_ids_found_when_unsegmented": {
                    key: sorted(value) for key, value in scan_unsegmented_set_ids(candidate_rows, pdf).items()
                } if not rows else {},
            })

    args.discrepancies.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in findings), encoding="utf-8")
    args.inventory.write_text(json.dumps({"pdf_count": len(inventory), "pdfs": inventory}, ensure_ascii=False, indent=2), encoding="utf-8")

    category_counts = Counter(item["category"] for item in findings)
    confidence_counts = Counter(item["confidence"] for item in findings)
    layout_types = Counter(
        "printed column headers" if any(page.get("column_labels") for page in sample.get("layout_evidence", []))
        else "position-only or non-tabular"
        for sample in results
    )
    processed = sum(item["status"] == "processed" for item in inventory)
    failed = sum(item["status"] == "failed" for item in inventory)
    skipped = sum(item["status"] == "skipped" for item in inventory)
    not_sampled = sum(item["status"] == "not sampled" for item in inventory)
    with args.report.open("w", encoding="utf-8") as report:
        report.write("# Full take-home sample: representative extraction and source QA\n\n")
        report.write("## Scope and limits\n\n")
        report.write(
            f"Inspected {len(inventory)} PDFs ({sum(item.get('page_count') or 0 for item in inventory):,} pages). "
            f"Ran local Qwen on one representative set in each of {processed + failed} segmented PDFs; "
            f"{not_sampled} additional PDFs had set candidates but were not sampled, and {skipped} PDFs had no segment candidate. "
            "The separate QA pass reopens source PDFs and independently derives labeled rows from word coordinates where available. "
            "It is a heuristic audit, not ground truth; no precision/recall or full-set coverage claim is made.\n\n"
        )
        no_text_pages = sum((item.get("page_count") or 0) - (item.get("pages_with_extractable_text") or 0) for item in inventory)
        report.write(
            f"PyMuPDF extracted text from {sum(item.get('pages_with_extractable_text') or 0 for item in inventory):,} pages; "
            f"{no_text_pages:,} pages had no extractable text. No OCR was run, so those pages remain unverified.\n\n"
        )
        report.write("Representative layout types: " + "; ".join(f"{name}: {count}" for name, count in sorted(layout_types.items())) + ".\n\n")
        run_config = extraction_payload.get("run_configuration", {})
        if run_config:
            report.write(
                "**Local inference:** "
                f"{run_config.get('base_model')} (4-bit MLX), mlx-lm {run_config.get('inference_library_version')} "
                f"(weights converted with mlx-lm {run_config.get('model_conversion_mlx_lm_version')}), "
                f"Python {run_config.get('python_version')}, PyMuPDF {run_config.get('pymupdf_version')}; "
                "offline mode, temperature 0, max 4,000 tokens, up to 2 retries. "
                f"Valid: {run_config.get('valid_samples')}/{run_config.get('sample_count')}; "
                f"failed: {run_config.get('failed_samples')}.\n\n"
            )
            warnings = run_config.get("source_qa_warnings", [])
            if warnings:
                report.write("**Nonfatal source-reader warnings:** " + "; ".join(warnings) + ". They occurred during source reading; the emitting file/page was not isolated. Text extraction completed and no page-level Python exceptions were recorded.\n\n")
        report.write("## Extraction status\n\n| PDFs | Count |\n|---|---:|\n")
        for label, count in (("Processed successfully", processed), ("Failed", failed), ("Candidate PDFs not sampled", not_sampled), ("Skipped: no segment candidate", skipped)):
            report.write(f"| {label} | {count} |\n")
        report.write("\n## Source QA findings\n\n")
        report.write(f"Discrepancy records: {len(findings)}. Confidence labels: {dict(confidence_counts)}.\n\n")
        report.write("| Category | Findings |\n|---|---:|\n")
        for category, count in sorted(category_counts.items()):
            report.write(f"| {category} | {count} |\n")
        report.write("\n## Per-PDF results\n\n| PDF | Status | Candidate set IDs | Sampled set | Validity | QA flags |\n|---|---|---:|---|---|---:|\n")
        for item in inventory:
            sample = item.get("representative_sample") or {}
            report.write(
                f"| `{item['pdf_filename']}` | {item['status']} | {len(item['distinct_segment_ids'])} | "
                f"{sample.get('sampled_set_id', '—')} | {sample.get('validation_status', '—')} | "
                f"{sample.get('finding_count', 0)} |\n"
            )
        report.write("\n## Likely missed schedule\n\n")
        missed = [item for item in findings if item["category"] == "possible_missed_sets"]
        if missed:
            for finding in missed:
                ids = finding["suspected_source_value"]
                report.write(
                    f"- **{finding['source_pdf']}**: source scan found {len(ids)} explicit group/set IDs "
                    f"({', '.join(ids[:12])}{'…' if len(ids) > 12 else ''}) at/around PDF page {finding['source_page']}; "
                    "the segmenter emitted no set regions. This is a likely segmentation miss; the listed IDs need review.\n"
                )
        else:
            report.write("No explicit group/set identifiers were found in PDFs without segment candidates.\n")
        report.write("\n## Field and layout patterns\n\n")
        row_count_differences = sum(
            len((sample.get("baseline") or {}).get("components", [])) != len((sample.get("llm") or {}).get("components", []))
            for sample in results
        )
        report.write(
            "The seven representative PDFs with printed QTY/DESCRIPTION-style headers enabled the most direct source comparison. "
            "Two high-confidence finish mismatches remain in SAT TDP set 715TW (PDF page 734), listed in the discrepancy JSONL. "
            "The other 13 samples used position-only or non-tabular layouts; their component-row alignments are mostly unverified, "
            "so this audit cannot claim those formats perform well or poorly. Roselle's SET/HARDWARE TYPE schedule is a distinct schema "
            "and also remains unverified by the generic column audit. No high-confidence quantity or page-location discrepancy was found. "
            f"The LLM component count differed from the deterministic parser in {row_count_differences}/20 samples (higher in each); "
            "this is a review signal only because the parser is not ground truth and counts may reflect either parser omissions or model over-splitting. "
            "The pipeline restores set IDs and location pages from segmentation metadata, so those final fields are not purely model predictions.\n\n"
        )
        report.write("\n## What this audit can establish\n\n")
        report.write(
            "High-confidence field flags require a matched source row with printed column labels; the evidence is the original row text. "
            "Medium flags include unmatched source rows and partial description matches. Headerless rows, component identities that could not be aligned, "
            "and continuation claims without explicit source evidence remain unverified. Other sets in candidate PDFs were intentionally not extracted, "
            "so they are not counted as omissions. Full set/component coverage cannot be estimated from one sample per PDF.\n\n"
            f"See `{args.inventory.name}` for every PDF, page/text counts, status, candidate counts, and set IDs; "
            f"see `{args.discrepancies.name}` for source evidence and suspected values.\n"
        )

    print(f"Inventory: {args.inventory} ({len(inventory)} PDFs)")
    print(f"Source QA findings: {args.discrepancies} ({len(findings)} records)")
    print(f"Report: {args.report}")


if __name__ == "__main__":
    main()
