"""Isolate likely hardware-set regions and segment them across pages.

Input is the recall-oriented candidate_pages.jsonl inspection output. This
script does not extract component fields; it records set regions and the raw
component-like lines for review.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


SET_START_RE = re.compile(
    r"^\s*(?:HARDWARE\s+)?(?:SET|GROUP)\s*"
    r"(?:(?:#|NO\.?|NUMBER|:)\s*(?P<marked>[A-Z0-9][A-Z0-9.-]*)|"
    r"(?P<plain>(?:NO\.?\s*)?\d+[A-Z0-9.-]*))\b",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^\s*HEADING\s*#\s*(\d+)\b", re.IGNORECASE)
TABLE_SET_NUMBER_RE = re.compile(r"^\s*(\d{1,3}\.\d{1,3}(?:\.[A-Z0-9]+)?)\s*$")

# These patterns recognize component-like labels at the start of a row. The
# text is retained as-is; matching a label does not mean its fields were parsed.
COMPONENT_LINE_RE = re.compile(
    r"^\s*(?:\d+\s+)?"
    r"(?:(?:standard|continuous|mortise|pivot|hw|surface|overhead|electric|electrified|"
    r"storeroom|panic|constant|latching|dust|proof|fail|safe|secure|rim|flush|door|"
    r"wall|floor|perimeter|jamb|head|card|automatic|auto|removable|weather|protection|"
    r"kick|armor|mag|magnetic|hanging|offset|sliding|full|cylindrical)\s+){0,3}"
    r"(?:HINGE|LOCKSET|LOCK|LATCH|DEADBOLT|CLOSER|EXIT\s+DEVICE|PANIC\s+HARDWARE(?:\s+DEVICE)?|"
    r"CYLINDER|FLUSH\s+BOLT|STRIKE|PULL|HANDLE|LEVER|THRESHOLD|STOP|COORDINATOR|"
    r"ASTRAGAL|GASKETING|GASKET|SWEEP|SHOE|WEATHERSTRIPPING|SILENCER|SILENCERS|"
    r"HANGING\s+DEVICE|CARD\s+READER|ACCESSORY|ACTUATOR|MULLION|DOOR\s+CONTACT|"
    r"PROTECTION\s+PLATE|ARMOR\s+PLATE|KICK\s+PLATE|MAGNETIC\s+HOLDER|DOOR\s+HOLDER|"
    r"POWER\s+TRANSFER|HARNESS|DOOR\s+ACCESS\s+CONTROL|MORTISE\s+DEVICE)\b",
    re.IGNORECASE,
)


def component_lines(lines):
    """Return line-numbered component-like rows for the given lines."""
    return [
        {"line_number": number, "text": line.strip()}
        for number, line in enumerate(lines, start=1)
        if line.strip() and COMPONENT_LINE_RE.search(line)
    ]


def find_set_starts(lines, table_schema):
    """Find explicit set/group headings and supported schedule identifiers."""
    starts = []
    for index, line in enumerate(lines):
        match = SET_START_RE.search(line)
        if match:
            set_id = match.group("marked") or match.group("plain")
            set_id = re.sub(r"^NO\.?\s*", "", set_id, flags=re.IGNORECASE)
            starts.append((index, set_id, "explicit_set_heading", line.strip()))
            continue

        heading = HEADING_RE.search(line)
        if heading:
            starts.append((index, f"Heading #{heading.group(1)}", "schedule_heading", line.strip()))
            continue

        # In the detected SET/HARDWARE TYPE/QTY tables, IDs such as 5.1 label
        # set groups. The schema guard avoids treating ordinary numbered prose
        # as set identifiers.
        table_id = TABLE_SET_NUMBER_RE.search(line) if table_schema else None
        if table_id:
            starts.append((index, table_id.group(1), "table_set_id", line.strip()))

    # If a table has a proper schema, explicit set headings take precedence;
    # otherwise numeric IDs identify rows in that table.
    deduplicated = []
    seen_lines = set()
    for start in starts:
        if start[0] not in seen_lines:
            deduplicated.append(start)
            seen_lines.add(start[0])
    return deduplicated


def isolate_page(candidate):
    """Return likely set regions, with a low-confidence fallback if unclear."""
    lines = candidate["text"].splitlines()
    table_terms = set(candidate.get("table_schema_terms", []))
    table_schema = (
        candidate.get("table_geometry_found", False)
        and "SET" in candidate["text"].upper()
        and {"quantity", "item", "manufacturer", "finish"}.issubset(table_terms)
    )
    starts = find_set_starts(lines, table_schema)
    regions = []

    if starts:
        for position, (start, set_id, start_type, heading) in enumerate(starts):
            end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
            region_lines = lines[start:end]
            rows = component_lines(region_lines)
            for row in rows:
                row["line_number"] += start

            if start_type == "table_set_id":
                confidence = "high" if len(rows) >= 2 else "medium"
                evidence = ["detected table SET column", "set identifier", "component-like rows"]
            elif len(rows) >= 2:
                confidence = "high"
                evidence = ["explicit set/group heading", "component-like rows"]
            else:
                confidence = "medium"
                evidence = ["explicit set/group heading"]

            regions.append(
                {
                    "pdf_filename": candidate["pdf_filename"],
                    "page_number": candidate["page_number"],
                    "line_start": start + 1,
                    "line_end": end,
                    "set_id": set_id,
                    "start_type": start_type,
                    "heading": heading,
                    "confidence": confidence,
                    "evidence": evidence,
                    "component_rows": rows,
                    "document_priority": candidate.get("document_priority", "low"),
                    "table_geometry_found": candidate.get("table_geometry_found", False),
                    "text": "\n".join(region_lines).strip(),
                }
            )

    if not regions:
        # Keep a reviewable page excerpt rather than silently discarding a
        # broad candidate that may use an unseen set format.
        rows = component_lines(lines)
        if rows:
            start = rows[0]["line_number"] - 1
            end = rows[-1]["line_number"]
            fallback_text = "\n".join(lines[start:end]).strip()
            fallback_rows = component_lines(lines[start:end])
            for row in fallback_rows:
                row["line_number"] += start
        else:
            start, end = 0, len(lines)
            fallback_text = candidate["text"].strip()
            fallback_rows = []
        regions.append(
            {
                "pdf_filename": candidate["pdf_filename"],
                "page_number": candidate["page_number"],
                "line_start": start + 1,
                "line_end": end,
                "set_id": None,
                "start_type": "unresolved_candidate_page",
                "heading": None,
                "confidence": "low",
                "evidence": ["candidate page retained; no set boundary isolated"],
                "component_rows": fallback_rows,
                "document_priority": candidate.get("document_priority", "low"),
                "table_geometry_found": candidate.get("table_geometry_found", False),
                "text": fallback_text,
            }
        )

    return regions, table_schema


def segment_regions(regions):
    """Group set regions and attach adjacent continuation-page content."""
    by_file = defaultdict(list)
    for region in regions:
        by_file[region["pdf_filename"]].append(region)

    segments = []
    for filename, file_regions in by_file.items():
        file_regions.sort(key=lambda row: (row["page_number"], row["line_start"]))
        active_by_id = {}
        previous_segment = None

        for region in file_regions:
            set_id = region["set_id"]
            has_rows = bool(region["component_rows"])

            if set_id is not None:
                prior = active_by_id.get(set_id)
                if (
                    prior
                    and region["page_number"] == prior["last_page"] + 1
                    and region["line_start"] <= 18
                ):
                    segment = prior["segment"]
                    segment["pages"].append(region["page_number"])
                    segment["page_locations"].append(
                        {"page_number": region["page_number"], "line_start": region["line_start"], "line_end": region["line_end"]}
                    )
                    segment["text"] += "\n\n" + region["text"]
                    segment["component_rows"].extend(region["component_rows"])
                    segment["evidence"].append("same set identifier continued on adjacent page")
                    if region["confidence"] == "high":
                        segment["confidence"] = "high"
                    active_by_id[set_id]["last_page"] = region["page_number"]
                    previous_segment = segment
                else:
                    segment = {
                        "pdf_filename": filename,
                        "set_id": set_id,
                        "heading": region["heading"],
                        "pages": [region["page_number"]],
                        "page_locations": [
                            {"page_number": region["page_number"], "line_start": region["line_start"], "line_end": region["line_end"]}
                        ],
                        "confidence": region["confidence"],
                        "evidence": list(region["evidence"]),
                        "component_rows": list(region["component_rows"]),
                        "text": region["text"],
                    }
                    segments.append(segment)
                    active_by_id[set_id] = {"segment": segment, "last_page": region["page_number"]}
                    previous_segment = segment
            elif (
                has_rows
                and previous_segment is not None
                and region["page_number"] == previous_segment["pages"][-1] + 1
                and (
                    region["table_geometry_found"]
                    or region["document_priority"] == "high"
                )
            ):
                previous_segment["pages"].append(region["page_number"])
                previous_segment["page_locations"].append(
                    {"page_number": region["page_number"], "line_start": region["line_start"], "line_end": region["line_end"]}
                )
                previous_segment["text"] += "\n\n" + region["text"]
                previous_segment["component_rows"].extend(region["component_rows"])
                previous_segment["evidence"].append("component rows continued on adjacent page")
                previous_segment["confidence"] = "medium"

    return segments


def write_jsonl(rows, path):
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_report(candidates, regions, segments, table_pages, report_path):
    region_confidence = Counter(row["confidence"] for row in regions)
    segment_confidence = Counter(row["confidence"] for row in segments)
    files_with_segments = len({row["pdf_filename"] for row in segments})
    continued = sum(len(set(row["pages"])) > 1 for row in segments)
    total_component_rows = sum(len(row["component_rows"]) for row in segments)

    with report_path.open("w", encoding="utf-8") as report:
        report.write("# Hardware set section isolation and segmentation\n\n")
        report.write("## Evaluation summary\n\n")
        report.write(f"- Candidate pages examined: {len(candidates)}\n")
        report.write(f"- Pages with detected table schema: {len(table_pages)}\n")
        report.write(f"- Isolated or fallback regions: {len(regions)}\n")
        report.write(f"- Regions with high / medium / low confidence: {region_confidence['high']} / {region_confidence['medium']} / {region_confidence['low']}\n")
        report.write(f"- Segmented set candidates: {len(segments)} across {files_with_segments} PDFs\n")
        report.write(f"- Segments spanning adjacent pages: {continued}\n")
        report.write(f"- Component-like rows retained: {total_component_rows}\n")
        report.write(
            f"- Set segments with high / medium / low confidence: "
            f"{segment_confidence['high']} / {segment_confidence['medium']} / {segment_confidence['low']}\n\n"
        )
        report.write(
            "Confidence is a rule-based review aid, not a probability. The report "
            "does not claim these are all true hardware sets. Rows are retained as "
            "raw text; quantities, manufacturers, finishes, and notes are not parsed.\n\n"
        )

        report.write("## What was checked manually\n\n")
        report.write(
            "Representative text from three layouts was reviewed: JC Ryan 2's `Set: EX-3.0` "
            "list, the Roselle `SET / HARDWARE TYPE / MANUFACTURER - PRODUCT / QTY. / "
            "FINISH / NOTES` table, and 81-85 Bridgeport's `Heading #` / `Item #` schedule. "
            "The extractor found explicit set/list structure in JC Ryan 2 and table-set "
            "structure on Roselle pages 15-17. Bridgeport page 30's Heading #55 region "
            "contains component-like rows and is retained as a segment; item references "
            "alone are not enough. These "
            "spot checks are useful examples, not a full labeled accuracy evaluation.\n\n"
        )

        report.write("## Segmented set candidates\n")
        for index, segment in enumerate(segments, start=1):
            rows = segment["component_rows"]
            report.write(
                f"\n### {index}. {segment['pdf_filename']} — set {segment['set_id']} "
                f"(page{'s' if len(segment['pages']) != 1 else ''} {', '.join(map(str, segment['pages']))})\n\n"
            )
            report.write(f"- Confidence: **{segment['confidence']}**\n")
            report.write(f"- Component-like rows: {len(rows)}\n")
            report.write(f"- Evidence: {', '.join(dict.fromkeys(segment['evidence']))}\n")
            if rows:
                report.write("- Sample rows: " + "; ".join(row["text"] for row in rows[:5]) + "\n")

        report.write("\n## Limits and next evaluation step\n\n")
        report.write(
            "The current evaluation counts detections and records a few manually reviewed "
            "examples; it does not measure precision or recall because no complete page/set "
            "ground-truth labels exist yet. Next, label a small set of pages from multiple "
            "projects, including positive, negative, and continuation pages, then compare "
            "the detected regions and set boundaries against those labels. Preserve low "
            "confidence regions until that check shows they can be safely excluded.\n"
        )


def main():
    parser = argparse.ArgumentParser(description="Isolate and segment hardware set candidates.")
    parser.add_argument("--input", type=Path, default=Path("candidate_pages.jsonl"))
    parser.add_argument("--sections", type=Path, default=Path("hardware_sections.jsonl"))
    parser.add_argument("--sets", type=Path, default=Path("hardware_sets.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("hardware_set_segmentation_report.md"))
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"Candidate input not found: {args.input}")

    candidates = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    regions = []
    table_pages = set()
    for candidate in candidates:
        page_regions, has_table_schema = isolate_page(candidate)
        regions.extend(page_regions)
        if has_table_schema:
            table_pages.add((candidate["pdf_filename"], candidate["page_number"]))

    segments = segment_regions(regions)
    write_jsonl(regions, args.sections)
    write_jsonl(segments, args.sets)
    write_report(candidates, regions, segments, table_pages, args.report)
    print(f"Candidate pages examined: {len(candidates)}")
    print(f"Set regions/fallbacks written: {len(regions)} ({args.sections})")
    print(f"Set segments written: {len(segments)} ({args.sets})")
    print(f"Evaluation report written: {args.report}")


if __name__ == "__main__":
    main()
