"""Run a small, local Qwen extraction experiment on six hardware sets.

This is an experiment runner, not a replacement for the existing pipeline. It
reuses hardware_sets.jsonl for set regions and the existing deterministic list
parser for a comparison baseline, then saves source context, model JSON, and a
human-readable comparison report.
"""

import argparse
import json
import math
import os
import re
import zipfile
from pathlib import Path

import pymupdf

from extract_sample_project_sets import list_component_records


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = BASE_DIR / ".models" / "Qwen3-4B-Instruct-2507-4bit"
SAMPLES = [
    ("81-85 Bridgeport", "Heading #1"),
    ("81-85 Bridgeport", "Heading #2"),
    ("Valor Acres Building E", "01"),
    ("Valor Acres Building E", "13"),
    ("HFH DG - HOSPITAL", "001"),
    ("HFH DG - HOSPITAL", "002"),
]

QUALITY_REVIEW = {
    ("81-85 Bridgeport", "Heading #1"): "Recovered the separate-line quantities. Manufacturer assignments are unsupported by a component-level mapping; product/catalog/finish splits need review.",
    ("81-85 Bridgeport", "Heading #2"): "Captured the visible rows and door reference. It mixes product codes and finishes, and some schedule entries may be coordination rather than hardware components.",
    ("Valor Acres Building E", "01"): "Captured all seven visible rows; nullable product/manufacturer fields are appropriate where the source gives no separate values.",
    ("Valor Acres Building E", "13"): "Captured the ten visible rows. Several short codes appear to be finishes but were assigned to catalog_number or left null.",
    ("HFH DG - HOSPITAL", "001"): "Captured the nine rows on page 20, but confused table glyphs with finish/notes and missed the unheaded continuation on page 21.",
    ("HFH DG - HOSPITAL", "002"): "Captured five rows on page 21 but missed the continuation on page 22; this set output is incomplete.",
}


def load_segments(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_source_context(archive, pdf_filename, target_pages):
    """Read full text for target and immediately adjacent 1-based PDF pages."""
    document = pymupdf.open(stream=archive.read(pdf_filename), filetype="pdf")
    target_pages = sorted(set(int(page) for page in target_pages))
    first = min(target_pages)
    last = max(target_pages)
    context_pages = range(max(1, first - 1), min(len(document), last + 1) + 1)
    page_texts = {}
    for page_number in context_pages:
        page_texts[str(page_number)] = document[page_number - 1].get_text("text").strip()
    document.close()
    return page_texts


def extract_layout_evidence(archive, pdf_filename, target_pages, set_id):
    """Return coordinate-based visual rows for the target set's pages.

    Column names are attached only when they are printed in a recognizable
    table header. Without one, cells remain positional and the uncertainty is
    explicit; this helper never guesses a field mapping from x coordinates.
    """
    document = pymupdf.open(stream=archive.read(pdf_filename), filetype="pdf")
    evidence = []
    group_pattern = re.compile(
        rf"(?i)\bhardware\s+group\s+no\.?\s*{re.escape(str(set_id))}(?![\w])"
        rf"|\bset\s*#\s*{re.escape(str(set_id))}(?![\w])"
    )
    next_group_pattern = re.compile(r"(?i)\bhardware\s+group\s+no\.?\s*\S+|\bset\s*#\s*\S+")
    for page_number in sorted(set(int(page) for page in target_pages)):
        page = document[page_number - 1]
        words = page.get_text("words")
        lines = []
        for word in words:
            x0, y0, x1, y1, text = word[:5]
            if not text.strip():
                continue
            match = next((line for line in lines if abs(line["y"] - y0) <= 2.5), None)
            if match is None:
                match = {"y": y0, "words": []}
                lines.append(match)
            match["words"].append((x0, y0, x1, y1, text))
        lines.sort(key=lambda line: line["y"])
        for line in lines:
            line["words"].sort(key=lambda word: word[0])
            line["text"] = " ".join(word[4] for word in line["words"])

        start_index = next((i for i, line in enumerate(lines) if group_pattern.search(line["text"])), None)
        if start_index is None:
            evidence.append({
                "page_number": page_number,
                "method": "PyMuPDF word bounding boxes",
                "rows": [],
                "column_labels": None,
                "uncertainty": "Target set heading was not located on this page; source text is retained without assigning geometry to the set.",
            })
            continue
        start_y = lines[start_index]["y"]
        end_y = next((line["y"] for line in lines[start_index + 1:] if next_group_pattern.search(line["text"])), float("inf"))
        region_lines = [line for line in lines if start_y <= line["y"] < end_y]
        header_line = next((line for line in region_lines if re.search(r"(?i)\bqty\b", line["text"]) and re.search(r"(?i)\bdescription\b", line["text"])), None)
        labels = []
        if header_line:
            header_words = header_line["words"]
            label_specs = [
                (r"(?i)^qty\.?$", "QTY"), (r"(?i)^description$", "DESCRIPTION"),
                (r"(?i)^catalog$", "CATALOG NUMBER"), (r"(?i)^finish$", "FINISH"),
                (r"(?i)^(?:mfr\.?|manufacturer)$", "MFR"),
                (r"(?i)^product$", "PRODUCT"), (r"(?i)^notes?$", "NOTES"),
            ]
            for word_index, word in enumerate(header_words):
                for pattern, label in label_specs:
                    if re.match(pattern, word[4]):
                        if label == "CATALOG NUMBER" and word_index + 1 < len(header_words) and header_words[word_index + 1][4].upper() == "NUMBER":
                            labels.append({"label": label, "x0": word[0], "x1": header_words[word_index + 1][2]})
                        elif label != "CATALOG NUMBER" or word[4].upper() != "NUMBER":
                            labels.append({"label": label, "x0": word[0], "x1": word[2]})
                        break
        labels.sort(key=lambda item: item["x0"])
        rows = []
        for line in region_lines:
            if line is header_line:
                rows.append({"y": round(line["y"], 1), "cells": [{"column": "HEADER", "raw_text": line["text"]}]})
                continue
            if not line["words"]:
                continue
            if labels and line["y"] > header_line["y"]:
                cells = []
                # Keep the boundary close to the next printed column label.
                # Midpoints can put long catalog/product strings into FINISH
                # or MFR even when those values stop before the next column.
                boundaries = [labels[0]["x0"]] + [
                    right["x0"] - 2 for right in labels[1:]
                ]
                grouped = [[] for _ in labels]
                markers = []
                for word in line["words"]:
                    glyph_match = re.match(r"^([\uf000-\uf8ff]+)(.*)$", word[4])
                    if glyph_match:
                        markers.append(glyph_match.group(1))
                        visible_text = glyph_match.group(2)
                        if not visible_text:
                            continue
                    else:
                        visible_text = word[4]
                    if not visible_text:
                        continue
                    idx = max((i for i, left in enumerate(boundaries) if word[0] >= left - 2), default=0)
                    grouped[idx].append(visible_text)
                for label, values in zip(labels, grouped):
                    if values:
                        cells.append({"column": label["label"], "raw_text": " ".join(values)})
                row = {"y": round(line["y"], 1), "cells": cells, "raw_text": line["text"]}
                if markers:
                    row["unmapped_pdf_glyphs"] = markers
                rows.append(row)
            else:
                cells = []
                groups = []
                for word in line["words"]:
                    if not groups or word[0] - groups[-1][-1][2] > 18:
                        groups.append([word])
                    else:
                        groups[-1].append(word)
                for group in groups:
                    cells.append({"x_start": round(group[0][0], 1), "raw_text": " ".join(word[4] for word in group)})
                rows.append({"y": round(line["y"], 1), "cells": cells, "raw_text": line["text"]})
        # Attach wrapped catalog/finish/note lines to the preceding component
        # when they have no new quantity or description. This keeps a split
        # PDF line in its visual column instead of inviting a field shift.
        merged_rows = []
        for row in rows:
            cells = row.get("cells", [])
            columns = {cell.get("column") for cell in cells}
            is_component_start = "QTY" in columns or "DESCRIPTION" in columns
            if (
                merged_rows
                and not is_component_start
                and "HEADER" not in columns
                and labels
            ):
                previous = merged_rows[-1]
                previous_columns = {cell.get("column") for cell in previous.get("cells", [])}
                if "QTY" in previous_columns and "DESCRIPTION" in previous_columns:
                    for cell in cells:
                        existing = next((item for item in previous["cells"] if item.get("column") == cell.get("column") and cell.get("column") is not None), None)
                        if existing:
                            existing["raw_text"] = f"{existing['raw_text']} {cell['raw_text']}"
                        else:
                            previous["cells"].append(cell)
                    previous["raw_text"] = f"{previous.get('raw_text', '')} {row.get('raw_text', '')}".strip()
                else:
                    merged_rows.append(row)
            else:
                merged_rows.append(row)
        rows = merged_rows
        evidence.append({
            "page_number": page_number,
            "method": "PyMuPDF word bounding boxes grouped into visual lines and x-position cells",
            "rows": rows,
            "column_labels": [item["label"] for item in labels] if labels else None,
            "uncertainty": None if labels else "No usable printed column-header row was found. Cells retain approximate x positions and raw text; field names are intentionally not inferred.",
        })
    document.close()
    return evidence


def make_baseline(project, segment):
    """Apply the existing deterministic line parser to this segment as a baseline."""
    description = None
    heading = segment.get("heading") or ""
    if ":" in heading:
        description = heading.split(":", 1)[1].strip().strip("()") or None
    if not description:
        match = re.search(r"(?im)^\s*(?:\d+\s+)?(?:Single|Pair)\s+door\s+[^\n]+", segment["text"])
        if match:
            description = match.group(0).strip()

    return {
        "set_number": str(segment["set_id"]),
        "description": description,
        "source_pdf": segment["pdf_filename"],
        "location": {
            "pages": segment["pages"],
            "line_ranges": segment["page_locations"],
        },
        "components": list_component_records(segment),
        "notes": None,
        "extraction_status": "components detected" if segment.get("component_rows") else "review: no component rows detected",
        "confidence": segment.get("confidence"),
        "source_format": "existing deterministic line parser applied to segment",
    }


def build_prompt(project, segment, page_texts, layout_evidence=None):
    context = "\n\n".join(
        f"--- PDF page {page_number} (full page context; adjacent pages may contain other sets) ---\n{text}"
        for page_number, text in page_texts.items()
    )
    schema = {
        "set_number": "string or null",
        "description": "string or null",
        "door_references": ["explicit door identifiers, or [] if none"],
        "source_pdf": "string",
        "location": {
            "pages": segment.get("pages", []),
            "line_ranges": segment.get("page_locations", []),
        },
        "components": [
            {
                "qty": "number or null",
                "description": "string or null",
                "product": "string or null",
                "catalog_number": "string or null",
                "mfr": "string or null",
                "finish": "string or null",
                "notes": "string or null",
                "source_page": "1-based page number or null",
                "raw_component_text": "verbatim source lines or null",
            }
        ],
        "notes": "string or null",
        "uncertainty_note": "brief string; null when no material uncertainty",
        "extraction_status": "string",
        "confidence": "low, medium, or high; heuristic judgment, not probability",
        "source_format": "string",
    }
    return (
        "Extract exactly one hardware set from the supplied construction specification text. "
        "Use only facts visible in the text. Do not invent a door reference, quantity, manufacturer, "
        "product, finish, or page number; use null when uncertain. A missing quantity is valid "
        "and must be JSON null rather than guessed; do not treat null quantity as an error. Keep component descriptions "
        "and product/model strings faithful to the source. The target set is identified below. "
        "Adjacent page text is context and may include other hardware groups: include continuation "
        "rows for this target only, stopping at the next explicit set/group heading. Preserve raw "
        "component text for traceability. For table rows, keep each row independent: do not carry a "
        "quantity, finish, manufacturer, product, or note from a neighboring row into a blank cell. "
        "A printed dash such as '--' means the quantity is missing; retain that component with qty null. "
        "A wrapped continuation line with no new quantity belongs to its preceding row; keep it with "
        "the column shown by the layout evidence, and do not move it to another field. When a labeled "
        "legend explicitly defines finish or manufacturer codes, use that legend only for the matching "
        "code in the component's aligned cell. "
        "Use the group's printed name/location as the set description; never use the first component "
        "description as the set description. Do not use a general manufacturer index to assign a "
        "manufacturer to a component unless the source links it to that row. For positional rows, use "
        "geometry and explicit legends only when they unambiguously identify the value; otherwise use null. "
        "Return one JSON object only, with no markdown or prose, "
        "matching this shape (retain all keys):\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + f"\n\nProject: {project}\nTarget set ID: {segment['set_id']}\n"
        + f"Exact source_pdf value: {segment['pdf_filename']}\n"
        + f"Target heading: {segment.get('heading')}\n"
        + f"Segmenter page(s): {json.dumps(segment.get('pages', []))}\n"
        + f"Target segmented source text:\n{segment['text']}\n\n"
        + "Coordinate-based layout evidence (supplemental, extracted from the PDF; "
        "these are visual lines/cells, not parsed component rows):\n"
        + json.dumps(layout_evidence or [], ensure_ascii=False, indent=2)
        + "\nUse named columns only where printed column labels are shown. If cells are positional, "
        "retain their raw text and use null for uncertain field mappings. Never move values between "
        "columns based only on a guess.\n"
        + f"Original PDF page text with adjacent-page context:\n{context}\n"
    )


def extract_json_object(text):
    """Parse one complete JSON object; reject surrounding prose or truncation."""
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1]).strip()
    if not candidate.startswith("{"):
        raise ValueError("model response must start with one JSON object")
    if not candidate.endswith("}"):
        raise ValueError("model response ended before the JSON object was complete")
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed JSON: {error.msg} at character {error.pos}") from error
    if not isinstance(value, dict):
        raise ValueError("response must be a JSON object")
    return value


def validate_record(record):
    if not isinstance(record, dict):
        raise ValueError("response must be a JSON object")
    required = {
        "set_number", "description", "door_references", "source_pdf", "location",
        "components", "notes", "uncertainty_note", "extraction_status", "confidence",
        "source_format",
    }
    missing = sorted(required - record.keys())
    if missing:
        raise ValueError(f"Missing required keys: {', '.join(missing)}")
    if not isinstance(record["components"], list):
        raise ValueError("components must be a list")
    if not isinstance(record["door_references"], list) or not all(
        isinstance(value, str) for value in record["door_references"]
    ):
        raise ValueError("door_references must be a list of strings")
    if not isinstance(record["location"], dict):
        raise ValueError("location must be an object")
    if not isinstance(record["location"].get("pages"), list) or not all(
        isinstance(value, int) and not isinstance(value, bool) for value in record["location"]["pages"]
    ):
        raise ValueError("location.pages must be a list of 1-based integers")
    if not isinstance(record["location"].get("line_ranges"), list) or not all(
        isinstance(value, dict) for value in record["location"]["line_ranges"]
    ):
        raise ValueError("location.line_ranges must be a list of line-range objects")
    for field in ("set_number", "description", "source_pdf", "notes", "uncertainty_note", "extraction_status", "confidence", "source_format"):
        value = record[field]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be a string or null")
    if record["confidence"] not in {None, "low", "medium", "high"}:
        raise ValueError("confidence must be low, medium, high, or null")
    component_keys = {
        "qty", "description", "product", "catalog_number", "mfr", "finish",
        "notes", "source_page", "raw_component_text",
    }
    for index, component in enumerate(record["components"], start=1):
        if not isinstance(component, dict):
            raise ValueError(f"component {index} must be an object")
        missing_component = sorted(component_keys - component.keys())
        if missing_component:
            raise ValueError(f"Component {index} missing keys: {', '.join(missing_component)}")
        qty = component["qty"]
        if qty is not None and (isinstance(qty, bool) or not isinstance(qty, (int, float))):
            raise ValueError(f"component {index} qty must be a number or null")
        if isinstance(qty, float) and not math.isfinite(qty):
            raise ValueError(f"component {index} qty must be finite")
        page = component["source_page"]
        if page is not None and (isinstance(page, bool) or not isinstance(page, int) or page < 1):
            raise ValueError(f"component {index} source_page must be a 1-based integer or null")
        for field in ("description", "product", "catalog_number", "mfr", "finish", "notes", "raw_component_text"):
            value = component[field]
            if value is not None and not isinstance(value, str):
                raise ValueError(f"component {index} {field} must be a string or null")
    return True


def normalize_null_strings(value):
    """Convert common model string stand-ins for JSON null to actual nulls."""
    if isinstance(value, dict):
        return {key: normalize_null_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_null_strings(item) for item in value]
    if isinstance(value, str) and value.strip().lower() in {"null", "none", "n/a", "unknown"}:
        return None
    return value


def read_code_legend(source_page_texts):
    """Read code/name pairs only from explicitly labeled finish/manufacturer lists."""
    full_text = "\n".join(source_page_texts.values())
    result = {"finish": {}, "manufacturer": {}}
    sections = [
        ("finish", r"(?im)^\s*(?:[A-Z]\.\s*)?Finish List\s*$", r"(?im)^\s*(?:[A-Z]\.\s*)?Manufacturer List\s*$"),
        ("manufacturer", r"(?im)^\s*(?:[A-Z]\.\s*)?Manufacturer List\s*$", r"(?im)^\s*(?:[A-Z]\.\s*)?Option List\s*$"),
    ]
    for kind, start_pattern, stop_pattern in sections:
        start = re.search(start_pattern, full_text)
        if not start:
            continue
        tail = full_text[start.end():]
        stop = re.search(stop_pattern, tail)
        if stop:
            tail = tail[:stop.start()]
        lines = [line.strip() for line in tail.splitlines() if line.strip()]
        lines = [line for line in lines if line.casefold() not in {"code", "description", "name"}]
        for index in range(0, len(lines) - 1, 2):
            code, name = lines[index:index + 2]
            if code and name:
                result[kind][code.upper()] = name
    return result


def normalize_layout_text(value):
    return " ".join(str(value or "").split()).casefold()


def apply_source_row_fields(record, segment, source_page_texts, layout_evidence):
    """Use explicit row cells/legends; clear mfr/finish values absent from that row."""
    legends = read_code_legend(source_page_texts)
    for component in record.get("components", []):
        raw = component.get("raw_component_text") or ""
        normalized_raw = normalize_layout_text(raw)
        matched_rows = []
        for page in layout_evidence or []:
            for row in page.get("rows", []):
                row_text = normalize_layout_text(row.get("raw_text"))
                if row_text and (row_text == normalized_raw or row_text in normalized_raw or normalized_raw in row_text):
                    matched_rows.append((page, row))
        exact_cells = []
        for page, row in matched_rows:
            cell_map = {}
            for cell in row.get("cells", []):
                value = " ".join(str(cell.get("raw_text", "")).split())
                if value:
                    exact_cells.append((cell.get("column"), value))
                    if cell.get("column"):
                        cell_map.setdefault(cell["column"], []).append(value)
            labels = set(page.get("column_labels") or [])
            if labels:
                def joined(label):
                    return " ".join(cell_map.get(label, [])) or None

                qty_text = joined("QTY")
                if "QTY" in labels:
                    qty_match = re.match(r"\s*(\d+(?:\.\d+)?)\b", qty_text or "")
                    component["qty"] = float(qty_match.group(1)) if qty_match and "." in qty_match.group(1) else int(qty_match.group(1)) if qty_match else None
                if "DESCRIPTION" in labels and joined("DESCRIPTION"):
                    component["description"] = joined("DESCRIPTION")
                if "CATALOG NUMBER" in labels and joined("CATALOG NUMBER"):
                    component["catalog_number"] = joined("CATALOG NUMBER")
                    component["product"] = joined("CATALOG NUMBER")
                if "PRODUCT" in labels and joined("PRODUCT"):
                    component["product"] = joined("PRODUCT")
                if "FINISH" in labels:
                    component["finish"] = joined("FINISH")
                if "MFR" in labels:
                    component["mfr"] = joined("MFR")
                if "NOTES" in labels:
                    component["notes"] = joined("NOTES")
                else:
                    component["notes"] = None

        for column, value in exact_cells:
            code = value.upper()
            if column == "FINISH" and code in legends["finish"]:
                component["finish"] = value
            elif column == "MFR" and code in legends["manufacturer"]:
                component["mfr"] = legends["manufacturer"][code]
            elif column is None:
                if code in legends["finish"]:
                    component["finish"] = value
                    if normalize_layout_text(component.get("catalog_number")) == normalize_layout_text(value):
                        component["catalog_number"] = None
                if code in legends["manufacturer"]:
                    component["mfr"] = legends["manufacturer"][code]

        # Do not retain a value that appears only in a neighboring row or a
        # document-wide index. A legend-backed manufacturer expansion is
        # supported when its code appears in this component's own raw text.
        raw_upper = raw.upper()
        finish = component.get("finish")
        if finish:
            finish_code = str(finish).upper()
            if finish_code in legends["manufacturer"] and finish_code not in legends["finish"]:
                component["finish"] = None
            elif normalize_layout_text(finish) not in normalized_raw:
                mapped_code = next((code for code, name in legends["finish"].items() if name.casefold() == str(finish).casefold()), None)
                if not mapped_code or not re.search(rf"(?<![A-Z0-9]){re.escape(mapped_code)}(?![A-Z0-9])", raw_upper):
                    component["finish"] = None
        manufacturer = component.get("mfr")
        if manufacturer:
            manufacturer_code = str(manufacturer).upper()
            if manufacturer_code in legends["finish"] and manufacturer_code not in legends["manufacturer"]:
                component["mfr"] = None
            elif normalize_layout_text(manufacturer) not in normalized_raw:
                mapped_code = next((code for code, name in legends["manufacturer"].items() if name.casefold() == str(manufacturer).casefold()), None)
                if not mapped_code or not re.search(rf"(?<![A-Z0-9]){re.escape(mapped_code)}(?![A-Z0-9])", raw_upper):
                    component["mfr"] = None


def attach_verified_metadata(record, segment, context_page_numbers, source_page_texts=None, layout_evidence=None):
    """Restore identifiers and locations directly known from the input pipeline."""
    heading = segment.get("heading") or ""
    printed_identifier = re.match(
        r"(?i)^\s*(?:hardware\s+group(?:\s+no\.?)?|set)\s*#?\s*(.*?)\s*$",
        heading,
    )
    # Prefer a complete explicit source heading when segmentation stored only
    # a prefix (for example, heading 'Set #AL 01' with set_id 'AL').
    record["set_number"] = (
        printed_identifier.group(1).split(":", 1)[0].strip()
        if printed_identifier and printed_identifier.group(1).split(":", 1)[0].strip()
        else str(segment["set_id"])
    )
    record["source_pdf"] = segment["pdf_filename"]
    if ":" in heading:
        record["description"] = heading.split(":", 1)[1].strip().strip("()") or None
    elif re.match(r"(?i)^Heading\s*#", heading):
        door_description = re.search(
            r"(?im)^\s*\d+\s+((?:Single|Pair)\s+door\s+[^\n]+)", segment.get("text", "")
        )
        if door_description:
            record["description"] = door_description.group(1).strip()
    if isinstance(record.get("description"), str):
        component_descriptions = {
            normalize_layout_text(component.get("description"))
            for component in record.get("components", [])
            if component.get("description")
        }
        if normalize_layout_text(record["description"]) in component_descriptions:
            record["description"] = None
    valid_pages = {int(page) for page in context_page_numbers}
    source_pages = set(int(page) for page in segment["pages"])
    for component in record.get("components", []):
        page_number = component.get("source_page")
        try:
            page_number = int(page_number) if page_number is not None else None
        except (TypeError, ValueError):
            page_number = None
        if page_number not in valid_pages:
            component["source_page"] = None
        else:
            component["source_page"] = page_number
            source_pages.add(page_number)
    record["location"] = {
        "pages": sorted(source_pages),
        "line_ranges": segment["page_locations"],
    }
    # The instruction does not allow guessing identifiers; a generic opening
    # class (for example PR door(s)) is not an explicit door reference.
    record["door_references"] = [
        ref for ref in record.get("door_references", [])
        if isinstance(ref, str) and re.search(r"\d", ref)
    ]
    normalized_refs = []
    for ref in record["door_references"]:
        explicit_door = re.search(
            r"(?i)\b(?:single|pair(?:\s+of)?|double)\s+doors?\s+([A-Z]{0,4}\d+[A-Z0-9]*)", ref
        )
        normalized_refs.append(explicit_door.group(1) if explicit_door else ref)
    record["door_references"] = list(dict.fromkeys(normalized_refs))
    if isinstance(record.get("description"), str) and re.match(
        r"(?i)^\s*provide each\b", record["description"]
    ):
        record["description"] = None
    if source_page_texts:
        apply_source_row_fields(record, segment, source_page_texts, layout_evidence or [])


def get_local_model(model_path):
    if not (model_path / "config.json").is_file() or not list(model_path.glob("*.safetensors")):
        raise FileNotFoundError(f"Local model files not found under {model_path}")
    # Prevent accidental Hub lookup: the model argument itself is a local path,
    # and the Hub/Transformers clients are also put in offline mode.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from mlx_lm import load

    return load(str(model_path))


def run_model(model, tokenizer, prompt, max_tokens):
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler

    chat_prompt = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    return generate(model, tokenizer, chat_prompt, max_tokens=max_tokens, sampler=make_sampler(temp=0.0))


def build_retry_prompt(original_prompt, raw_response, error):
    """Ask for a corrected full response after a parse/schema failure only."""
    response_tail = (raw_response or "")[-6000:]
    return (
        original_prompt
        + "\n\nRETRY INSTRUCTION: The previous response failed JSON/schema validation: "
        + str(error)
        + ". Return a complete corrected JSON object only. Preserve null for missing values, "
        "including missing quantities. Do not add inferred facts. Repeat the provided location "
        "metadata exactly; line_ranges must remain objects, not a list of line numbers. "
        "Do not change any extraction merely to match the deterministic parser.\n"
        "Previous response (for correction):\n"
        + response_tail
    )


def normalize(value):
    return " ".join(str(value or "").lower().split())


def compare_records(baseline, llm):
    differences = []
    for field in ("set_number", "description"):
        if normalize(baseline.get(field)) != normalize(llm.get(field)):
            differences.append(f"set-level {field}: deterministic={baseline.get(field)!r}; LLM={llm.get(field)!r}")
    base_pages = baseline.get("location", {}).get("pages", [])
    llm_pages = llm.get("location", {}).get("pages", [])
    if base_pages != llm_pages:
        differences.append(f"set-level source pages: deterministic={base_pages!r}; LLM={llm_pages!r}")

    base_components = baseline.get("components", [])
    llm_components = llm.get("components", [])
    if len(base_components) != len(llm_components):
        differences.append(f"component count: deterministic={len(base_components)}; LLM={len(llm_components)}")
    base_by_description = {}
    for component in base_components:
        base_by_description.setdefault(normalize(component.get("description")), []).append(component)
    llm_by_description = {}
    for component in llm_components:
        llm_by_description.setdefault(normalize(component.get("description")), []).append(component)
    for description in sorted(set(base_by_description) | set(llm_by_description)):
        left = base_by_description.get(description, [])
        right = llm_by_description.get(description, [])
        if len(left) != len(right):
            differences.append(
                f"component description {description or '[blank]'!r}: deterministic count={len(left)}; LLM count={len(right)}"
            )
            continue
        for baseline_component, llm_component in zip(left, right):
            for field in ("qty", "catalog_number", "mfr", "finish"):
                if normalize(baseline_component.get(field)) != normalize(llm_component.get(field)):
                    differences.append(
                        f"{description or '[blank]'} {field}: deterministic={baseline_component.get(field)!r}; LLM={llm_component.get(field)!r}"
                    )
    return differences


def write_report(samples, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as report:
        report.write("# Local Qwen hardware-set MVP: six-sample run\n\n")
        report.write(
            "JSON/schema validity means the response parsed and met the required shape; it does "
            "not establish factual correctness or completeness. Deterministic-parser disagreements "
            "are reported for review and never trigger retries. Missing quantities are valid nulls. "
            "No accuracy, precision, or recall is claimed. Inference used the local model with "
            "Hub/Transformers offline mode enabled.\n\n"
        )
        report.write("| Sample | Baseline rows | Qwen rows | JSON/schema | Retries | Source review |\n")
        report.write("|---|---:|---:|---|---:|---|\n")
        for sample in samples:
            baseline = sample.get("baseline") or {}
            llm = sample.get("llm") or {}
            baseline_count = len(baseline.get("components", []))
            llm_count = len(llm.get("components", [])) if llm else "—"
            review = QUALITY_REVIEW.get(
                (sample["project"], str(sample["set_id"])),
                "See the stored source, output, and disagreement details.",
            ).replace("|", "\\|")
            report.write(
                f"| {sample['project']} / {sample['set_id']} | {baseline_count} | {llm_count} | "
                f"{sample.get('validation_status', 'not run')} | {sample.get('retry_count', 0)} | {review} |\n"
            )
        report.write("\n## Audit trail\n\n")
        report.write(
            "`mvp_llm_extractions.json` retains each source excerpt and adjacent-page text, "
            "deterministic output, parsed model output (or null on failure), every raw response, "
            "validation status, retry count, error details, and parser disagreements. Retries "
            "apply only to generation, JSON-parse, or schema-validation failures. A null quantity "
            "does not fail validation.\n"
        )


def save_output(samples, output_path, model_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment": "six-set local Qwen MVP",
        "model_path": str(model_path.resolve()),
        "inference_mode": "local-only; HF_HUB_OFFLINE=1; TRANSFORMERS_OFFLINE=1",
        "schema_note": "Existing fields retained where applicable; added door_references, product, source_page, raw_component_text, uncertainty_note.",
        "samples": samples,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=BASE_DIR / "data.zip")
    parser.add_argument("--segments", type=Path, default=BASE_DIR / "hardware_sets.jsonl")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=BASE_DIR / "mvp_llm_extractions.json")
    parser.add_argument("--report", type=Path, default=BASE_DIR / "mvp_llm_comparison.md")
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--max-retries", type=int, default=2)
    args = parser.parse_args()
    if not 0 <= args.max_retries <= 2:
        parser.error("--max-retries must be between 0 and 2")
    if args.max_tokens < 1:
        parser.error("--max-tokens must be positive")
    for path in (args.archive, args.segments):
        if not path.is_file():
            parser.error(f"Required input not found: {path}")
    if not args.model.is_dir():
        parser.error(f"Local model directory not found: {args.model}")

    segment_rows = load_segments(args.segments)
    results = []
    segment_by_key = {}
    with zipfile.ZipFile(args.archive) as archive:
        for project, set_id in SAMPLES:
            sample = {
                "project": project,
                "set_id": str(set_id),
                "source_pdf": None,
                "source_pages": {},
                "source_excerpt": None,
                "baseline": None,
                "llm": None,
                "llm_status": "pending",
                "attempts": [],
                "raw_model_output": None,
                "validation_status": "not run",
                "retry_count": 0,
                "error_details": [],
                "differences": [],
            }
            results.append(sample)
            try:
                matches = [
                    row for row in segment_rows
                    if project.lower() in row.get("pdf_filename", "").lower()
                    and str(row.get("set_id")) == str(set_id)
                ]
                if not matches:
                    raise ValueError("set region not found in hardware_sets.jsonl")
                segment = matches[0]
                segment_by_key[(project, str(set_id))] = segment
                sample["source_pdf"] = segment["pdf_filename"]
                sample["source_excerpt"] = segment["text"]
                sample["source_pages"] = read_source_context(
                    archive, segment["pdf_filename"], segment["pages"]
                )
                sample["layout_evidence"] = extract_layout_evidence(
                    archive, segment["pdf_filename"], segment["pages"], segment["set_id"]
                )
                sample["baseline"] = make_baseline(project, segment)
            except Exception as error:
                sample["validation_status"] = "not run"
                sample["llm_status"] = "failed during source preparation"
                sample["error_details"].append(
                    {"stage": "source preparation", "error": f"{type(error).__name__}: {error}"}
                )

    # A single model-load failure is recorded for every prepared sample; it
    # does not prevent a report or partial output from being written.
    try:
        model, tokenizer = get_local_model(args.model)
        model_error = None
    except Exception as error:
        model = tokenizer = None
        model_error = f"{type(error).__name__}: {error}"

    save_output(results, args.output, args.model)
    for index, sample in enumerate(results, start=1):
        key = (sample["project"], sample["set_id"])
        segment = segment_by_key.get(key)
        if segment is None:
            continue
        if model_error is not None:
            sample["llm_status"] = "failed during model initialization"
            sample["error_details"].append({"stage": "model initialization", "error": model_error})
            sample["validation_status"] = "not run"
            save_output(results, args.output, args.model)
            continue

        try:
            original_prompt = build_prompt(
                sample["project"], segment, sample["source_pages"], sample.get("layout_evidence")
            )
        except Exception as error:
            sample["llm_status"] = "failed while building prompt"
            sample["error_details"].append({"stage": "prompt construction", "error": f"{type(error).__name__}: {error}"})
            sample["validation_status"] = "not run"
            save_output(results, args.output, args.model)
            continue

        print(f"[{index}/{len(results)}] {sample['project']} set {sample['set_id']}", flush=True)
        previous_raw = ""
        previous_error = None
        for attempt_number in range(args.max_retries + 1):
            max_tokens = min(args.max_tokens + attempt_number * 1000, 6000)
            prompt = original_prompt if attempt_number == 0 else build_retry_prompt(
                original_prompt, previous_raw, previous_error
            )
            attempt = {
                "attempt": attempt_number + 1,
                "max_tokens": max_tokens,
                "validation_status": "pending",
                "raw_response": None,
                "error": None,
            }
            sample["attempts"].append(attempt)
            try:
                raw = run_model(model, tokenizer, prompt, max_tokens)
                attempt["raw_response"] = raw
                sample["raw_model_output"] = raw
                record = normalize_null_strings(extract_json_object(raw))
                validate_record(record)
                attach_verified_metadata(
                    record, segment, sample["source_pages"].keys(),
                    sample["source_pages"], sample.get("layout_evidence"),
                )
                validate_record(record)
                attempt["validation_status"] = "valid"
                sample["llm"] = record
                sample["llm_status"] = "valid JSON and schema"
                sample["validation_status"] = "valid"
                sample["retry_count"] = attempt_number
                break
            except Exception as error:
                details = f"{type(error).__name__}: {error}"
                attempt["validation_status"] = "failed"
                attempt["error"] = details
                sample["error_details"].append(
                    {"attempt": attempt_number + 1, "stage": "generation or validation", "error": details}
                )
                previous_raw = attempt.get("raw_response") or ""
                previous_error = details
                sample["raw_model_output"] = previous_raw or sample.get("raw_model_output")
                sample["retry_count"] = attempt_number
                if attempt_number < args.max_retries:
                    print(f"  retrying after response/validation failure: {details}", flush=True)
                else:
                    sample["validation_status"] = "failed"
                    sample["llm_status"] = "failed after retry limit"

        if sample.get("llm") is not None:
            # Comparison is informational only and deliberately happens after
            # retries, so parser disagreement never causes another inference.
            try:
                sample["differences"] = compare_records(sample["baseline"], sample["llm"])
            except Exception as error:
                sample["comparison_error"] = f"{type(error).__name__}: {error}"
        save_output(results, args.output, args.model)

    write_report(results, args.report)
    print(f"Saved extraction JSON: {args.output}")
    print(f"Saved comparison report: {args.report}")


if __name__ == "__main__":
    main()
