"""Find likely hardware schedule pages in PDFs stored in data.zip.

The built-in text patterns are an automatic, tunable first-pass heuristic. This
inspection aid retains matching page text in a debug file; it never changes
the source archive or its PDFs. Candidate filtering is not final classification.
"""

import argparse
import json
import re
import zipfile
from pathlib import Path

import pymupdf as fitz


# Automatic first-pass clues. Tune these as you inspect the PDFs. The filter is
# intentionally easy to revise and should not be treated as final classification.
HEADER_FILTERS = [
    r"\bHARDWARE\s+GROUP(?:\s+NO\.?)?\b",
    r"\bSET\s*(?:#|NO\.?)\s*[A-Z0-9-]+\b",
    r"\b087100\b|\b08\s*71\s*00\b",  # Door hardware section identifiers
]

TABLE_COLUMN_FILTERS = {
    "quantity": r"\b(?:QTY|QUANTITY)\b",
    "item": r"\b(?:ITEM|NO\.?|PRODUCT)\b",
    "description": r"\b(?:DESCRIPTION|HARDWARE)\b",
    "manufacturer": r"\b(?:MANUFACTURER|MFR|MFG)\b",
    "finish": r"\bFINISH\b",
}

HARDWARE_TERM_FILTERS = {
    "hinge": r"\bHINGE\w*\b",
    "lock": r"\b(?:LOCK|LOCKSET|LATCH|DEADBOLT)\w*\b",
    "closer": r"\bCLOSER\w*\b",
    "exit device": r"\bEXIT\s+DEVICE\w*\b",
    "handle": r"\b(?:HANDLE|LEVER|PULL)\w*\b",
    "door": r"\bDOOR\w*\b",
    "hardware": r"\bHARDWARE\b",
    "strike": r"\bSTRIKE\w*\b",
    "threshold": r"\bTHRESHOLD\w*\b",
}

COMPONENT_ROW_FILTERS = {
    "hinge": r"^(?:\d+\s+)?(?:standard\s+|continuous\s+)?hinge\w*\b",
    "lock": r"^(?:\d+\s+)?(?:lockset|lock|latch|deadbolt)\w*\b",
    "closer": r"^(?:\d+\s+)?(?:surface\s+|overhead\s+)?closer\w*\b",
    "exit device": r"^(?:\d+\s+)?exit\s+device\w*\b",
    "cylinder": r"^(?:\d+\s+)?cylinder\w*\b",
    "flush bolt": r"^(?:\d+\s+)?flush\s+bolt\w*\b",
    "strike": r"^(?:\d+\s+)?(?:electric\s+)?strike\w*\b",
    "pull/handle": r"^(?:\d+\s+)?(?:door\s+)?(?:pull|handle|lever)\w*\b",
    "threshold": r"^(?:\d+\s+)?threshold\w*\b",
    "stop": r"^(?:\d+\s+)?(?:door\s+)?stop\w*\b",
    "coordinator": r"^(?:\d+\s+)?coordinator\w*\b",
    "astragal": r"^(?:\d+\s+)?(?:z\s+)?astragal\w*\b",
    "armor plate": r"^(?:\d+\s+)?(?:armor|kick)\s+plate\w*\b",
}

EXPLICIT_SET_LINE = re.compile(
    r"^\s*(?:HARDWARE\s+)?(?:SET|GROUP)\s*"
    r"(?:(?:#|NO\.?|NUMBER|:)\s*[A-Z0-9][A-Z0-9.-]*|"
    r"(?:NO\.?\s*)?\d+[A-Z0-9.-]*)\b",
    flags=re.IGNORECASE,
)


def find_matches(text, patterns):
    """Return the labels of patterns found in page text."""
    return [
        label
        for label, pattern in patterns.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]


def find_component_rows(text):
    """Find hardware component labels at the start of extracted text lines."""
    component_rows = set()
    for line in text.splitlines():
        normalized_line = re.sub(r"^\s*(?:\d+[.)]?\s+)?", "", line).strip()
        component_rows.update(find_matches(normalized_line, COMPONENT_ROW_FILTERS))
    return component_rows


def assess_page(
    page,
    text,
    header_patterns,
    extra_patterns,
    previous_table_page=False,
    previous_set_heading=False,
):
    """Use table/list structure first, retaining broad clues as low-priority hits."""
    header_matches = [
        pattern
        for pattern in header_patterns
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    header_matches.extend(
        f"custom filter {index}"
        for index, pattern in enumerate(extra_patterns, start=1)
        if re.search(pattern, text, flags=re.IGNORECASE)
    )
    columns = find_matches(text, TABLE_COLUMN_FILTERS)
    hardware_terms = find_matches(text, HARDWARE_TERM_FILTERS)
    component_rows = find_component_rows(text)
    schedule_heading = bool(
        re.search(r"\b(?:DOOR\s+)?HARDWARE\s+SCHEDULE\b", text, flags=re.IGNORECASE)
    )
    repeated_schedule_items = (
        len(re.findall(r"\bHEADING\s*#\s*\d+", text, re.IGNORECASE)) >= 1
        and len(re.findall(r"\bITEM\s*#\s*\d+", text, re.IGNORECASE)) >= 2
        and len(component_rows) >= 2
    )
    set_heading_lines = [
        index
        for index, line in enumerate(text.splitlines())
        if EXPLICIT_SET_LINE.search(line)
    ]
    explicit_set_heading = bool(set_heading_lines)
    set_list_match = any(
        find_component_rows("\n".join(text.splitlines()[index + 1:index + 13]))
        for index in set_heading_lines
    )

    # A table is only inspected on pages with a plausible schedule schema.
    # This avoids running geometric table detection over every page in the archive.
    upper_text = re.sub(r"\s+", " ", text.upper())
    schema_terms = {
        "set": bool(re.search(r"\bSET\b", upper_text)),
        "hardware type": "HARDWARE TYPE" in upper_text,
        "manufacturer/product": bool(re.search(r"\b(?:MANUFACTURER|MFR|MFG|PRODUCT)\b", upper_text)),
        "quantity": bool(re.search(r"\b(?:QTY\.?|QUANTITY)\b", upper_text)),
        "finish": bool(re.search(r"\bFINISH\b", upper_text)),
        "notes": bool(re.search(r"\bNOTES?\b", upper_text)),
    }
    page_schema_terms = [name for name, found in schema_terms.items() if found]
    table_geometry_found = False
    table_schema_terms = []
    if schema_terms["set"] and schema_terms["quantity"] and len(page_schema_terms) >= 3:
        try:
            tables = page.find_tables().tables
            table_geometry_found = bool(tables)
            for table in tables:
                table_text = " ".join(
                    cell or ""
                    for row in table.extract()
                    for cell in row
                )
                extracted_terms = find_matches(table_text.upper(), TABLE_COLUMN_FILTERS)
                # The page-level schema clues must also belong to a detected
                # table. This avoids treating narrative mentions as a table.
                if (
                    re.search(r"\bSET\b", table_text, re.I)
                    and re.search(r"\b(?:QTY\.?|QUANTITY)\b", table_text, re.I)
                    and re.search(r"\bHARDWARE\s+TYPE\b|\b(?:MANUFACTURER|MFR|MFG|PRODUCT)\b", table_text, re.I)
                    and len(extracted_terms) >= 4
                ):
                    table_schema_terms = extracted_terms
                    break
        except Exception:
            # Broken/malformed PDFs should still be processed by text heuristics.
            table_geometry_found = False

    # Accept table-like pages with a small amount of evidence to favor recall.
    # A set/group/schedule item marker plus component rows is useful context.
    has_set_marker = explicit_set_heading
    broad_table_match = (
        len(component_rows) >= 3
        or (has_set_marker and len(component_rows) >= 2)
        or (schedule_heading and len(component_rows) >= 2)
        or (len(columns) >= 3 and len(component_rows) >= 2)
    )
    structured_table_match = (
        bool(table_schema_terms)
        and len(component_rows) >= 2
    )
    continued_table_match = previous_table_page and len(component_rows) >= 1
    continued_set_match = previous_set_heading and len(component_rows) >= 1
    structural_match = (
        explicit_set_heading
        or set_list_match
        or structured_table_match
        or continued_table_match
        or continued_set_match
    )
    table_match = structured_table_match or broad_table_match or continued_table_match
    is_candidate = (
        bool(header_matches)
        or table_match
        or explicit_set_heading
        or repeated_schedule_items
    )

    if not is_candidate:
        confidence = None
    elif structured_table_match or set_list_match:
        confidence = "high"
    elif explicit_set_heading or continued_set_match:
        confidence = "medium"
    elif repeated_schedule_items:
        confidence = "medium"
    elif continued_table_match or (has_set_marker and len(component_rows) >= 2):
        confidence = "medium"
    elif broad_table_match or continued_table_match or repeated_schedule_items:
        confidence = "medium"
    else:
        confidence = "low"

    evidence = []
    if header_matches:
        evidence.append("header/section clue")
    if table_match:
        evidence.append("table or component-row clues")
    if set_list_match:
        evidence.append("set heading followed by component rows")
    elif explicit_set_heading:
        evidence.append("explicit set/group identifier")
    if structured_table_match:
        evidence.append("detected table with set/component column schema")
    if continued_table_match:
        evidence.append("continuation of a structured table page")
    if continued_set_match:
        evidence.append("component rows continuing a set from the previous page")
    if repeated_schedule_items:
        evidence.append("repeated schedule heading/item markers")
    return {
        "is_candidate": is_candidate,
        "structural_match": structural_match,
        "explicit_set_heading": explicit_set_heading,
        "confidence": confidence,
        "evidence": evidence,
        "header_matches": header_matches,
        "table_columns": columns,
        "hardware_terms": hardware_terms,
        "component_row_types": sorted(component_rows),
        "table_schema_terms": table_schema_terms,
        "table_geometry_found": table_geometry_found,
    }


def assess_document(filename, first_page_text):
    """Rank, but never exclude, files that look like door hardware documents."""
    basename = Path(filename).name
    filename_hint = bool(
        re.search(
            r"door[\s_-]*hardware|hardware[\s_-]*(?:schedule|spec|index|group)|"
            r"\b087100\b|\b08[\s._-]*71[\s._-]*00\b",
            basename,
            flags=re.IGNORECASE,
        )
    )
    if filename_hint:
        return "high"
    if re.search(r"\bDOOR\s+HARDWARE\b|\b08\s*71\s*00\b", first_page_text, re.I):
        return "medium"
    return "low"


def inspect_archive(archive_path, header_patterns, extra_patterns):
    """Read each PDF in the ZIP one page at a time and keep matching pages."""
    pages_processed = 0
    pages_with_text = 0
    pages_without_text = 0
    candidates = []
    header_candidate_count = 0
    table_only_count = 0

    with zipfile.ZipFile(archive_path) as archive:
        pdf_names = [
            item.filename
            for item in archive.infolist()
            if not item.is_dir() and item.filename.lower().endswith(".pdf")
        ]

        for pdf_name in pdf_names:
            # Open the PDF directly from the ZIP member bytes; no source files
            # are extracted or modified on disk.
            pdf_bytes = archive.read(pdf_name)
            with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
                first_page_text = (
                    document.load_page(0).get_text("text") if document.page_count else ""
                )
                document_priority = assess_document(pdf_name, first_page_text)
                previous_table_page = False
                previous_set_heading = False
                for page_index in range(document.page_count):
                    page = document.load_page(page_index)
                    text = page.get_text("text")
                    pages_processed += 1
                    if text.strip():
                        pages_with_text += 1
                    else:
                        pages_without_text += 1

                    assessment = assess_page(
                        page,
                        text,
                        header_patterns,
                        extra_patterns,
                        previous_table_page=previous_table_page,
                        previous_set_heading=previous_set_heading,
                    )
                    previous_table_page = assessment["table_geometry_found"]
                    previous_set_heading = assessment["explicit_set_heading"]
                    if assessment["header_matches"]:
                        header_candidate_count += 1
                    if assessment["is_candidate"] and not assessment["header_matches"]:
                        table_only_count += 1
                    if assessment["is_candidate"]:
                        candidates.append(
                            {
                                "pdf_filename": pdf_name,
                                "document_priority": document_priority,
                                "page_number": page_index + 1,
                                "text_characters": len(text),
                                "confidence": assessment["confidence"],
                                "structural_match": assessment["structural_match"],
                                "explicit_set_heading": assessment["explicit_set_heading"],
                                "evidence": assessment["evidence"],
                                "header_matches": assessment["header_matches"],
                                "table_columns": assessment["table_columns"],
                                "hardware_terms": assessment["hardware_terms"],
                                "component_row_types": assessment["component_row_types"],
                                "table_schema_terms": assessment["table_schema_terms"],
                                "table_geometry_found": assessment["table_geometry_found"],
                                "text": text,
                            }
                        )

    return (
        pages_processed,
        pages_with_text,
        pages_without_text,
        header_candidate_count,
        table_only_count,
        candidates,
    )


def save_candidates(candidates, output_path):
    """Write candidate page metadata and text as readable JSON Lines."""
    with output_path.open("w", encoding="utf-8") as output_file:
        for candidate in candidates:
            output_file.write(json.dumps(candidate, ensure_ascii=False) + "\n")


def save_markdown_report(candidates, report_path, pages_processed, pages_with_text,
                         pages_without_text, header_count, table_only_count):
    """Write a human-readable report with evidence and extracted page text."""
    with report_path.open("w", encoding="utf-8") as report:
        report.write("# Candidate hardware schedule pages\n\n")
        report.write("## Scan summary\n\n")
        report.write(f"- PDF pages processed: {pages_processed}\n")
        report.write(f"- Pages with extractable text: {pages_with_text}\n")
        report.write(f"- Pages with no extractable text: {pages_without_text}\n")
        report.write(f"- Pages matched by header/section clues: {header_count}\n")
        report.write(
            "- Additional candidates without a header/section match "
            f"(set, table, or list cues): {table_only_count}\n"
        )
        report.write(f"- Total candidate pages: {len(candidates)}\n\n")
        structural_count = sum(candidate["structural_match"] for candidate in candidates)
        report.write(f"- Candidates with structural set evidence: {structural_count}\n")
        report.write(
            f"- Broad-clue candidates retained for recall: "
            f"{len(candidates) - structural_count}\n\n"
        )
        report.write(
            "Confidence labels are heuristic evidence levels, not probabilities. "
            "Document priority only orders review and never excludes a PDF. "
            "Candidates may include false positives; pages without extractable "
            "text may need OCR in a later stage.\n\n"
        )
        ordered_candidates = sorted(
            candidates,
            key=lambda candidate: (
                not candidate["structural_match"],
                {"high": 0, "medium": 1, "low": 2}[candidate["document_priority"]],
                candidate["pdf_filename"].lower(),
                candidate["page_number"],
            ),
        )
        report.write("## Structural evidence candidates\n")
        report.write("Pages with explicit set identifiers, set-shaped lists, or detected table structure.\n")

        structural_number = 0
        broad_number = 0
        for candidate in ordered_candidates:
            if candidate["structural_match"]:
                structural_number += 1
                number = structural_number
            else:
                if broad_number == 0:
                    report.write("\n## Broad-clue candidates retained for recall\n")
                    report.write("These need review; a section code or generic component mention alone is weak evidence.\n")
                broad_number += 1
                number = broad_number
            report.write(f"\n### {number}. {candidate['pdf_filename']} — page "
                         f"{candidate['page_number']}\n\n")
            report.write(f"- Confidence: **{candidate['confidence']}**\n")
            report.write(f"- Document priority: **{candidate['document_priority']}**\n")
            classification = (
                "structural set evidence"
                if candidate["structural_match"]
                else "broad clue; review needed"
            )
            report.write(f"- Classification: {classification}\n")
            report.write(f"- Evidence: {', '.join(candidate['evidence']) or 'none'}\n")
            if candidate["header_matches"]:
                report.write(f"- Header clues: {', '.join(candidate['header_matches'])}\n")
            if candidate["component_row_types"]:
                report.write(
                    "- Component-like row types: "
                    f"{', '.join(candidate['component_row_types'])}\n"
                )
            report.write(f"- Extracted characters: {candidate['text_characters']}\n\n")

            # Pick a fence longer than any backtick run in the extracted text.
            runs = re.findall(r"`+", candidate["text"])
            fence = "`" * max(3, max((len(run) for run in runs), default=0) + 1)
            report.write(f"{fence}text\n{candidate['text']}\n{fence}\n")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Inspect PDFs in a ZIP and save pages matching the automatic "
            "first-pass hardware schedule heuristic."
        )
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("data.zip"),
        help="Input ZIP archive (default: data.zip)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("candidate_pages.jsonl"),
        help="Debug output file (default: candidate_pages.jsonl)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("candidate_pages.md"),
        help="Readable Markdown report (default: candidate_pages.md)",
    )
    parser.add_argument(
        "--filter",
        action="append",
        dest="filters",
        help="Additional case-insensitive regex header clue; may be repeated.",
    )
    args = parser.parse_args()

    if not args.archive.is_file():
        parser.error(f"Archive not found: {args.archive}")

    pages_processed, pages_with_text, pages_without_text, header_count, table_only_count, candidates = inspect_archive(
        args.archive, HEADER_FILTERS, args.filters or []
    )
    save_candidates(candidates, args.output)
    save_markdown_report(
        candidates,
        args.report,
        pages_processed,
        pages_with_text,
        pages_without_text,
        header_count,
        table_only_count,
    )

    print(f"PDF pages processed: {pages_processed}")
    print(f"Pages with extractable text: {pages_with_text}")
    print(f"Pages with no extractable text: {pages_without_text}")
    print(f"Pages matched by header/section clues: {header_count}")
    print(
        "Additional candidates without a header/section match "
        f"(set, table, or list cues): {table_only_count}"
    )
    print(f"Candidate pages found: {len(candidates)}")
    print(f"Candidate text saved to: {args.output}")
    print(f"Readable report saved to: {args.report}")


if __name__ == "__main__":
    main()
