"""Create deterministic structured records for two supported schedule formats.

This supporting parser handles JC Ryan 2 section/list schedules and Roselle
Public Library tables. It preserves source text and locations for review and
can provide a deterministic reference alongside the local LLM extraction.
"""

import argparse
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

import pymupdf

from segment_hardware_sets import COMPONENT_LINE_RE


PROJECT_FILES = {
    "JC Ryan 2": "JC Ryan 2/087100 - Door Hardware-6.pdf",
    "Roselle Public Library": "Roselle Public Library/087100_FL_-_Door_Hardware_IFB_REVISED.pdf",
}

KNOWN_LIST_MANUFACTURERS = {
    "allegion", "assa abloy", "balanced door manufacturer", "blumcraft",
    "dormakaba", "hager", "horton", "ives", "lc n", "lcn", "mckinney",
    "ngp", "norton", "pemko", "rockwood", "sargent", "schlage",
    "securitron", "von duprin", "zero",
}

SET_NUMBER_RE = re.compile(r"^\s*(\d{1,3}\.\d{1,3}(?:\.[A-Z0-9]+)?)\s*$", re.I)
TABLE_HEADER_ALIASES = {
    "set": {"set"},
    "description": {"hardware type", "hardware", "item description"},
    "product": {"manufacturer - product", "manufacturer/product", "manufacturer product", "product"},
    "qty": {"qty", "qty." , "quantity"},
    "finish": {"finish"},
    "notes": {"notes", "note"},
}


def clean_cell(value):
    return " ".join((value or "").split()).strip()


def parse_quantity(value):
    value = clean_cell(value)
    return int(value) if re.fullmatch(r"\d+", value) else None


def split_manufacturer_product(value):
    value = clean_cell(value)
    if " - " in value:
        manufacturer, product = value.split(" - ", 1)
        return manufacturer.strip() or None, product.strip() or None, value or None
    return None, None, value or None


def find_table_columns(table_rows):
    for row_index, row in enumerate(table_rows):
        normalized = [clean_cell(cell).lower().rstrip(".") for cell in row]
        columns = {}
        for name, aliases in TABLE_HEADER_ALIASES.items():
            for column_index, value in enumerate(normalized):
                if value in {alias.rstrip(".") for alias in aliases}:
                    columns[name] = column_index
                    break
        if {"set", "description", "product", "qty", "finish", "notes"}.issubset(columns):
            return row_index, columns
    return None, None


def extract_roselle_table(archive, internal_pdf_path):
    """Read table cells directly so column boundaries remain explicit."""
    pdf_bytes = archive.read(internal_pdf_path)
    document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    sets_by_id = {}
    active_set_id = None

    for page_index, page in enumerate(document):
        page_text = page.get_text("text")
        if "HARDWARE TYPE" not in page_text.upper() or "MANUFACTURER" not in page_text.upper():
            continue

        for table in page.find_tables().tables:
            rows = table.extract()
            header_row_index, columns = find_table_columns(rows)
            if columns is None:
                continue

            for row_index in range(header_row_index + 1, len(rows)):
                row = rows[row_index]
                cell = lambda name: row[columns[name]] if columns[name] < len(row) else None
                set_cell = cell("set") or ""
                set_match = next(
                    (match for line in (set_cell or "").splitlines() if (match := SET_NUMBER_RE.match(line))),
                    None,
                )
                if set_match:
                    active_set_id = set_match.group(1)
                    if active_set_id not in sets_by_id:
                        sets_by_id[active_set_id] = {
                            "set_number": active_set_id,
                            "description": None,
                            "source_pdf": internal_pdf_path,
                            "location": {"pages": [], "bounding_boxes": []},
                            "components": [],
                            "notes": None,
                            "confidence": "high",
                            "source_format": "detected hardware schedule table",
                        }

                if active_set_id is None:
                    continue
                current = sets_by_id[active_set_id]

                # Non-numeric text in the SET column is usually the opening or
                # use description, often in a vertically merged cell.
                set_descriptions = [
                    clean_cell(line)
                    for line in (set_cell or "").splitlines()
                    if clean_cell(line) and not SET_NUMBER_RE.match(line)
                ]
                if set_descriptions:
                    previous = current["description"] or ""
                    merged = list(dict.fromkeys((previous + " " + " ".join(set_descriptions)).split()))
                    current["description"] = " ".join(merged) or None

                description = clean_cell(cell("description"))
                raw_product = clean_cell(cell("product"))
                qty_text = clean_cell(cell("qty"))
                finish = clean_cell(cell("finish")) or None
                notes = clean_cell(cell("notes")) or None
                if not any([description, raw_product, qty_text, finish, notes]):
                    continue
                if not description and not raw_product and not qty_text:
                    continue

                manufacturer, catalog_number, raw_product_value = split_manufacturer_product(raw_product)
                component_bbox = None
                if row_index < len(table.rows):
                    component_bbox = table.rows[row_index].bbox
                    if component_bbox:
                        current["location"]["bounding_boxes"].append(
                            {"page_number": page_index + 1, "bbox": list(component_bbox)}
                        )
                if page_index + 1 not in current["location"]["pages"]:
                    current["location"]["pages"].append(page_index + 1)

                current["components"].append(
                    {
                        "qty": parse_quantity(qty_text),
                        "description": description or None,
                        "catalog_number": catalog_number,
                        "mfr": manufacturer,
                        "finish": finish,
                        "notes": notes,
                        "raw_product": raw_product_value,
                        "source_location": {
                            "page_number": page_index + 1,
                            "bbox": list(component_bbox) if component_bbox else None,
                        },
                    }
                )

    document.close()
    results = list(sets_by_id.values())
    for item in results:
        item["extraction_status"] = (
            "components detected" if item["components"] else "review: no component rows detected"
        )
    return results


def is_list_component_start(line):
    return bool(COMPONENT_LINE_RE.search(line))


def list_component_records(segment):
    lines = segment["text"].splitlines()
    starts = [index for index, line in enumerate(lines) if is_list_component_start(line)]
    manufacturers = {value.lower() for value in KNOWN_LIST_MANUFACTURERS}
    components = []

    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        block = [line.strip() for line in lines[start:end] if line.strip()]
        if not block:
            continue
        for stop_index, value in enumerate(block[1:], start=1):
            if re.match(r"^(?:Operation:|Set\s*:|Description:|Interior Hardware Sets\b)", value, re.I):
                block = block[:stop_index]
                break
        if not block:
            continue
        first = block[0]
        quantity_match = re.match(r"^\s*(\d+)\s+(.*)$", first)
        quantity = int(quantity_match.group(1)) if quantity_match else None
        description = quantity_match.group(2).strip() if quantity_match else first
        catalog_number = None
        manufacturer = None
        notes = []

        tail = block[1:]
        # Keep wrapped item names such as "Panic Hardware Device (Blumcraft\nStyle)"
        # together before interpreting later lines as product data.
        while tail and description.count("(") > description.count(")"):
            description += " " + tail.pop(0)

        for value in tail:
            normalized = value.strip().strip(".,;:")
            if normalized.lower() in manufacturers:
                manufacturer = normalized
                continue
            if normalized.lower().startswith("by "):
                notes.append(value)
                continue
            if (
                catalog_number is None
                and len(normalized) <= 100
                and re.search(r"\d", normalized)
                and not re.search(r"[.!?]$", normalized)
            ):
                catalog_number = value
            else:
                notes.append(value)

        components.append(
            {
                "qty": quantity,
                "description": description or None,
                "catalog_number": catalog_number,
                "mfr": manufacturer,
                # List schedules often combine finish codes with catalog
                # strings. Leave finish null unless a distinct field exists.
                "finish": None,
                "notes": " ".join(notes) or None,
                "raw_component_text": "\n".join(block),
            }
        )
    return components


def extract_jc_ryan(segments, internal_pdf_path):
    sets = []
    for segment in segments:
        if segment["pdf_filename"] != internal_pdf_path:
            continue
        description_match = re.search(r"(?im)^\s*Description:\s*(.*?)\s*$", segment["text"])
        notes_match = re.search(r"(?ims)^\s*Notes:\s*(.*?)(?=^\s*(?:Set\s*:|Description:)|\Z)", segment["text"])
        operation_match = re.search(r"(?ims)^\s*Operation:\s*(.*?)(?=^\s*(?:Set\s*:|Description:)|\Z)", segment["text"])
        set_notes = None
        if notes_match:
            set_notes = " ".join(notes_match.group(1).split()) or None
        elif operation_match:
            set_notes = "Operation: " + " ".join(operation_match.group(1).split())
        pages = segment["pages"]
        components = list_component_records(segment)
        sets.append(
            {
                "set_number": segment["set_id"],
                "description": description_match.group(1).strip() if description_match else None,
                "source_pdf": internal_pdf_path,
                "location": {
                    "pages": pages,
                    "line_ranges": segment["page_locations"],
                },
                "components": components,
                "notes": set_notes,
                "extraction_status": "review: no component rows detected" if not components else "components detected",
                "confidence": segment["confidence"],
                "source_format": "section/list hardware set",
            }
        )
    return sets


def write_evaluation(projects, output_path):
    with output_path.open("w", encoding="utf-8") as report:
        report.write("# Sample structured hardware-set extraction evaluation\n\n")
        report.write("## Scope\n\n")
        report.write(
            "This deterministic parser produces structured JSON for two supported inputs: "
            "JC Ryan 2's section/list schedule and Roselle Public Library's ruled table. "
            "It is not a full-dataset accuracy claim.\n\n"
        )
        report.write("## Counts\n\n")
        for project in projects:
            sets = project["hardware_sets"]
            component_counts = [len(item["components"]) for item in sets]
            with_components = sum(count > 0 for count in component_counts)
            flat_components = [component for item in sets for component in item["components"]]
            report.write(
                f"- **{project['project']}**: {len(sets)} set records; "
                f"{with_components} have at least one component; "
                f"{sum(component_counts)} component records total.\n"
            )
            if flat_components:
                fields = ["qty", "description", "catalog_number", "mfr", "finish", "notes"]
                coverage = "; ".join(
                    f"{field} {sum(component.get(field) is not None for component in flat_components)}/{len(flat_components)}"
                    for field in fields
                )
                report.write(f"  - Non-null field counts (coverage, not accuracy): {coverage}.\n")
        report.write("\n")

        report.write("## Spot checks and limits\n\n")
        report.write(
            "The list parser was checked against JC Ryan 2 sets EX-3.0 and 1.0: it "
            "preserves the visible set number/description, quantity prefixes, product "
            "lines, and known manufacturer lines. The Roselle table parser uses the "
            "detected SET, HARDWARE TYPE, MANUFACTURER-PRODUCT, QTY, FINISH, and NOTES "
            "columns; set IDs such as 1.2 are carried across blank merged cells. These "
            "checks confirm the expected shape on sample rows, not field-level precision "
            "or recall for every record.\n\n"
        )
        report.write(
            "For list pages, manufacturer and finish are intentionally conservative: "
            "manufacturer is assigned only when a following line exactly matches a "
            "small known-name list, and finish remains null when it is mixed into product "
            "text. The table parser maps the explicit manufacturer/product and finish "
            "columns, while preserving the raw product cell. Missing or ambiguous values "
            "are not guessed. Review empty or unusually short sets before treating this "
            "JSON as final.\n\n"
        )
        report.write(
            "The JC Ryan 2 set 15.0 record has no component rows in the source segment; "
            "it is retained with its set-level note that hardware is by the door manufacturer. "
            "This may represent a deliberate no-component/alternate case and should be reviewed, "
            "not silently dropped.\n\n"
        )
        report.write("## Next evaluation step\n\n")
        report.write(
            "Manually label the set IDs and component rows on a few pages from these two "
            "projects, then compare the JSON against those labels. Add at least one more "
            "project with a different layout before tuning manufacturer/finish rules.\n"
        )


def main():
    parser = argparse.ArgumentParser(description="Extract sample project hardware sets as JSON.")
    parser.add_argument("--archive", type=Path, default=Path("data.zip"))
    parser.add_argument("--segments", type=Path, default=Path("hardware_sets.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("sample_hardware_sets.json"))
    parser.add_argument("--evaluation", type=Path, default=Path("sample_extraction_evaluation.md"))
    args = parser.parse_args()
    if not args.archive.is_file():
        parser.error(f"Archive not found: {args.archive}")
    if not args.segments.is_file():
        parser.error(f"Set segment input not found: {args.segments}")

    segments = [json.loads(line) for line in args.segments.read_text(encoding="utf-8").splitlines() if line.strip()]
    projects = []
    with zipfile.ZipFile(args.archive) as archive:
        for project_name, suffix in PROJECT_FILES.items():
            internal_pdf_path = next(
                (name for name in archive.namelist() if name.endswith(suffix)), None
            )
            if internal_pdf_path is None:
                raise FileNotFoundError(f"PDF not found in archive: {suffix}")
            if project_name == "Roselle Public Library":
                hardware_sets = extract_roselle_table(archive, internal_pdf_path)
            else:
                hardware_sets = extract_jc_ryan(segments, internal_pdf_path)
            projects.append(
                {
                    "project": project_name,
                    "source_pdf": internal_pdf_path,
                    "hardware_sets": hardware_sets,
                }
            )

    output = {
        "extraction_version": 1,
        "note": "Prototype output; review confidence and raw fields before treating as final.",
        "projects": projects,
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_evaluation(projects, args.evaluation)
    print(f"Projects extracted: {len(projects)}")
    print(f"Set records written: {sum(len(project['hardware_sets']) for project in projects)}")
    print(f"Structured JSON saved to: {args.output}")
    print(f"Evaluation notes saved to: {args.evaluation}")


if __name__ == "__main__":
    main()
