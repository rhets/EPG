
#!/usr/bin/env python3

"""
Build an XMLTV EPG for all Xtream Codes provider channels.

Uses:
    provider_guide.xml
    epg_review_with_warnings.csv
    strong_match_candidates.csv
    strong_match_title_review.csv

Output:
    epg.xml

Only approved strong matches receive programme listings.
All other provider channels are included without listings.
"""

from pathlib import Path
import csv
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from collections import Counter

BASE = Path(__file__).resolve().parent

GUIDE_FILE = BASE / "provider_guide.xml"
ALL_CHANNELS_FILE = BASE / "epg_review_with_warnings.csv"
STRONG_FILE = BASE / "strong_match_candidates.csv"
TITLE_REVIEW_FILE = BASE / "strong_match_title_review.csv"
MANUAL_FILE = BASE / "production_manual_approvals.csv"
OUTPUT_FILE = BASE / "epg.xml"

GOOD_SAMPLE_LABEL = "SAMPLES LOOK USEFUL - still verify channel identity"

TIME_RE = re.compile(r"^(\d{14})(?:\s+[+-]\d{4})?$")


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def clean_text(value):
    value = "" if value is None else str(value)

    return "".join(
        ch for ch in value
        if ch in "\t\n\r"
        or 0x20 <= ord(ch) <= 0xD7FF
        or 0xE000 <= ord(ch) <= 0xFFFD
        or 0x10000 <= ord(ch) <= 0x10FFFF
    ).strip()


def valid_time(value):
    if not value:
        return None

    match = TIME_RE.match(value.strip())

    if not match:
        return None

    try:
        return datetime.strptime(
            match.group(1),
            "%Y%m%d%H%M%S"
        )
    except ValueError:
        return None


def main():

    required_files = [
        GUIDE_FILE,
        ALL_CHANNELS_FILE,
        STRONG_FILE,
        TITLE_REVIEW_FILE,
        MANUAL_FILE
    ]

    for path in required_files:
        if not path.is_file():
            print(f"ERROR: Missing input file: {path.name}")
            sys.exit(1)

    print("Reading review files...")

    all_channels = read_csv(ALL_CHANNELS_FILE)
    strong_rows = read_csv(STRONG_FILE)
    title_rows = read_csv(TITLE_REVIEW_FILE)
    manual_rows = read_csv(MANUAL_FILE)

    # Map guide IDs to their title-review status.
    # The review file must contain guide_id and sample_review columns.
    title_status = {
        row.get("guide_id", "").strip():
        row.get("sample_review", "").strip()
        for row in title_rows
    }

    approved = {}
    used_guide_ids = set()

    for row in strong_rows:

        stream_id = str(row.get("stream_id", "")).strip()
        guide_id = str(row.get("candidate_1_id", "")).strip()

        provider_name = clean_text(
            row.get("provider_name", "")
        )

        if not stream_id or not guide_id:
            continue

        if title_status.get(guide_id) != GOOD_SAMPLE_LABEL:
            continue

        if row.get(
            "candidate_1_id_duplicate_warning", ""
        ).strip() != "NOT DUPLICATED":
            continue

        if row.get("existing_id_match", "").strip() != guide_id:
            continue

        if row.get("candidate_1_score", "").strip() not in (
            "1", "1.0", "1.00"
        ):
            continue

        if stream_id in approved:
            continue

        if guide_id in used_guide_ids:
            continue

        approved[stream_id] = (guide_id, provider_name)
        used_guide_ids.add(guide_id)

    # Validate and add manually approved US channels.
    provider_by_stream = {
        str(row.get("stream_id", "")).strip():
        clean_text(row.get("provider_name", ""))
        for row in all_channels
    }

    print("Checking manual production approvals...")

    guide_channel_ids = set()
    guide_programme_counts = Counter()

    for event, elem in ET.iterparse(
        str(GUIDE_FILE),
        events=("end",)
    ):
        if elem.tag == "channel":
            guide_channel_ids.add(elem.get("id", ""))
            elem.clear()
        elif elem.tag == "programme":
            guide_programme_counts[elem.get("channel", "")] += 1
            elem.clear()

    manual_streams = set()
    manual_guide_ids = set()
    manual_errors = []

    for row in manual_rows:
        stream_id = str(row.get("stream_id", "")).strip()
        guide_id = str(row.get("guide_id", "")).strip()
        provider_name = clean_text(row.get("provider_name", ""))

        problems = []

        if not stream_id or not guide_id:
            problems.append("missing stream or guide ID")

        if stream_id in manual_streams:
            problems.append("duplicate manual stream ID")

        manual_streams.add(stream_id)
        manual_guide_ids.add(guide_id)

        if provider_by_stream.get(stream_id) != provider_name:
            problems.append("provider name does not match stream ID")

        if not provider_name.startswith("US|"):
            problems.append("not identified as a US provider channel")

        if guide_id not in guide_channel_ids:
            problems.append("guide ID not found in XMLTV")

        if guide_programme_counts[guide_id] == 0:
            problems.append("guide ID has no programmes")

        if stream_id in approved:
            problems.append("stream already has an automatic approval")

        if problems:
            manual_errors.append(
                f"{stream_id} / {guide_id}: " + ", ".join(problems)
            )
        else:
            approved[stream_id] = (guide_id, provider_name)
            used_guide_ids.add(guide_id)

    if manual_errors:
        print("ERROR: Manual production approvals failed validation:")
        for error in manual_errors:
            print(" -", error)
        sys.exit(1)

    print(f"Manual production approvals added: {len(manual_rows):,}")
    print(f"Approved matches: {len(approved):,}")
    print("Preparing provider channels...")

    channel_rows = []
    seen_stream_ids = set()
    seen_xmltv_ids = set()
    guide_to_xmltv_ids = {}

    for row in all_channels:

        stream_id = str(row.get("stream_id", "")).strip()

        name = clean_text(
            row.get("provider_name", "")
        )

        if not stream_id or stream_id in seen_stream_ids:
            continue

        seen_stream_ids.add(stream_id)

        if stream_id in approved:
            guide_id = approved[stream_id][0]
            xmltv_id = guide_id

            if xmltv_id in seen_xmltv_ids:
                xmltv_id = stream_id
        else:
            guide_id = None
            xmltv_id = stream_id

        base_id = xmltv_id
        suffix = 2

        while xmltv_id in seen_xmltv_ids:
            xmltv_id = f"{base_id}.{suffix}"
            suffix += 1

        seen_xmltv_ids.add(xmltv_id)

        channel_rows.append(
            (xmltv_id, name, stream_id)
        )

        if guide_id:
            guide_to_xmltv_ids.setdefault(
                guide_id, []
            ).append(xmltv_id)

    guide_ids = set(guide_to_xmltv_ids)

    counts = Counter()
    invalid = 0
    duplicate_programmes = 0
    seen_programmes = set()

    print("Building XMLTV file from live guide...")
    print("This may take a few minutes.")

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as out:

        out.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
        )

        out.write(
            '<tv generator-info-name="my-us-epg">\n'
        )

        # Write all provider channels.
        for xmltv_id, name, stream_id in channel_rows:

            channel = ET.Element(
                "channel",
                {"id": xmltv_id}
            )

            display = ET.SubElement(
                channel,
                "display-name",
                {"lang": "en"}
            )

            display.text = name or stream_id

            out.write(
                ET.tostring(
                    channel,
                    encoding="unicode"
                ) + "\n"
            )

        # Stream programme data from the live guide.
        for event, elem in ET.iterparse(
            str(GUIDE_FILE),
            events=("end",)
        ):

            if elem.tag == "programme":

                channel_id = elem.get("channel", "")

                if channel_id in guide_to_xmltv_ids:

                    start_text = elem.get("start", "")
                    stop_text = elem.get("stop", "")

                    start_dt = valid_time(start_text)
                    stop_dt = valid_time(stop_text)

                    if (
                        start_dt is None
                        or stop_dt is None
                        or stop_dt <= start_dt
                    ):
                        invalid += 1

                    else:
                        # Copy the guide listing to every stream
                        # assigned to this source guide ID.
                        for output_id in guide_to_xmltv_ids[channel_id]:

                            key = (
                                output_id,
                                start_text,
                                stop_text,
                                elem.findtext("title", default="")
                            )

                            if key in seen_programmes:
                                duplicate_programmes += 1
                            else:
                                seen_programmes.add(key)
                                elem.set("channel", output_id)

                                out.write(
                                    ET.tostring(
                                        elem,
                                        encoding="unicode"
                                    ) + "\n"
                                )

                                counts[output_id] += 1

                elem.clear()

            elif elem.tag == "channel":
                elem.clear()

        out.write("</tv>\n")

    mapped_with_listings = sum(
        1 for xmltv_id, _, stream_id in channel_rows
        if stream_id in approved and counts[xmltv_id] > 0
    )

    total_programmes = sum(counts.values())

    print("\nEPG BUILD COMPLETE")
    print("------------------")

    print(
        f"Provider channels included: "
        f"{len(channel_rows):,}"
    )

    print(
        f"Channels with programme data: "
        f"{mapped_with_listings:,}"
    )

    print(
        f"Channels without listings: "
        f"{len(channel_rows) - mapped_with_listings:,}"
    )

    print(
        f"Valid programme entries written: "
        f"{total_programmes:,}"
    )

    print(
        f"Invalid programme entries skipped: "
        f"{invalid:,}"
    )

    print(
        f"Duplicate programme entries skipped: "
        f"{duplicate_programmes:,}"
    )

    print(f"Output: {OUTPUT_FILE}")

    print(
        "\nNote: Matches passed title-sample screening, "
        "but channel identity should still be checked in TiviMate."
    )


if __name__ == "__main__":
    main()
