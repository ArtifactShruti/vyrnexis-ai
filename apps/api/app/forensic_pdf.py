"""Generate a bounded, text-only report from a stored case snapshot."""
from io import BytesIO
from textwrap import wrap

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas


def render_report(snapshot: dict, integrity_hash: str) -> bytes:
    buffer = BytesIO()
    document = Canvas(buffer, pagesize=A4, invariant=True)
    document.setTitle(f"VYRNEXIS report {snapshot['case']['id']} v{snapshot['version']}")
    width, height = A4
    y = 0
    page = 0

    def next_page():
        nonlocal y, page
        if page:
            document.showPage()
        page += 1
        document.setFillColor(colors.HexColor("#0C1830"))
        document.rect(0, height - 46, width, 46, fill=1, stroke=0)
        document.setFont("Helvetica-Bold", 12)
        document.setFillColor(colors.white)
        document.drawString(42, height - 29, "VYRNEXIS | Investigation report")
        document.setFont("Helvetica", 8)
        document.setFillColor(colors.HexColor("#44546A"))
        document.drawRightString(width - 42, 28, f"Page {page}")
        y = height - 69

    def write(value, *, bold=False):
        nonlocal y
        for row in str(value).splitlines() or [""]:
            for line in wrap(row, width=85, replace_whitespace=True) or [""]:
                if y < 52:
                    next_page()
                document.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
                document.setFillColor(colors.HexColor("#14253B"))
                document.drawString(42, y, line)
                y -= 14

    next_page()
    case = snapshot["case"]
    write(case["title"], bold=True)
    write(f"Case {case['id']} | Report version {snapshot['version']} | {snapshot['created_at']}")
    write(f"Investigator {case.get('investigator_name') or 'Unassigned'} | {case['status']}")
    write(case["description"])
    if case.get("closure_summary"):
        write(case["closure_summary"])
    write(snapshot["scope"], bold=True)
    for link in snapshot["links"]:
        write(f"{link['kind']} {link['object_id']}")
    write("Evidence and custody", bold=True)
    for item in snapshot["evidence"]:
        write(f"{item['name']} | {item['classification']} | {item['custodian_id'] or 'Unassigned'}")
        write("SHA-256 " + item["sha256"])
        write("SHA-512 " + item["sha512"])
        write("Custody verification " + item["chain_status"])
        image = item.get("image_metadata")
        if image and image["fields"]:
            fields = image["fields"]
            if "width" in fields and "height" in fields:
                write(f"Embedded dimensions {fields['width']} × {fields['height']} pixels")
            if "orientation" in fields:
                write(f"Embedded EXIF orientation {fields['orientation']}")
            if "capture_time" in fields:
                write(f"Embedded capture time {fields['capture_time']} (time zone unverified)")
        for entry in item["custody"]:
            write(f"{entry['time']} | {entry['action']} | {entry['actor_id']} | {entry['purpose']}")
    write("Analyst notes and preserved revisions", bold=True)
    for note in snapshot["notes"]:
        write(f"{note['category']} | revision {note['revision']} | {note['time']} | {note['author_id']}", bold=True)
        write(note["body"])
        for ref in note["references"]:
            write(f"Reference {ref['kind']} {ref['object_id']}")
    write("Investigation activity", bold=True)
    for entry in snapshot["activity"]:
        write(f"{entry['time']} | {entry['action']} | {entry['actor_id']}")
    if snapshot["agent_findings"]:
        write(f"Deterministic analysis | {snapshot['agent_run_status']}", bold=True)
        for item in snapshot["agent_findings"]:
            write(f"{item['agent']} | {item['verification_status']}", bold=True)
            write(item["claim"])
            for source in item["sources"]:
                write(f"Source {source}")
    write("SHA-256 of canonical JSON snapshot", bold=True)
    write(integrity_hash)
    document.save()
    return buffer.getvalue()
