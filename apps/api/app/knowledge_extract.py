"""Read text from bounded uploads without rendering document content."""
import csv
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import BoundedSemaphore
from xml.etree import ElementTree
from zipfile import ZipFile


MAX_FILE = 2 * 1024 * 1024
MAX_TEXT = 80_000
MAX_BODY = (MAX_FILE * 4 // 3) + 4096
FORMATS = {"txt", "md", "csv", "json", "pdf", "docx"}
SLOTS = BoundedSemaphore(2)
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def document_text(format_name, payload):
    if format_name == "pdf":
        from pypdf import PdfReader

        if not payload.startswith(b"%PDF-"):
            raise ValueError
        reader = PdfReader(BytesIO(payload), strict=True)
        if reader.is_encrypted or len(reader.pages) > 25:
            raise ValueError
        pages, count = [], 0
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text()
            count += len(text)
            if count > MAX_TEXT:
                raise ValueError
            pages.append((f"page {number}", text))
        return pages
    if format_name == "docx":
        with ZipFile(BytesIO(payload)) as bundle:
            parts = bundle.infolist()
            if len(parts) > 200 or sum(part.file_size for part in parts) > 8 * MAX_FILE:
                raise ValueError
            entries = [part for part in parts if part.filename == "word/document.xml"]
            if len(entries) != 1 or entries[0].file_size > MAX_FILE:
                raise ValueError
            with bundle.open(entries[0]) as stream:
                document = stream.read(MAX_FILE + 1)
            if len(document) > MAX_FILE or not document.lstrip().startswith(b"<") or re.search(
                rb"<!\s*(DOCTYPE|ENTITY)", document, re.IGNORECASE,
            ):
                raise ValueError
            tree = ElementTree.fromstring(document.decode("utf-8-sig"))
            if tree.tag != WORD + "document":
                raise ValueError
            text = "\n".join("".join(node.text or "" for node in paragraph.iter(WORD + "t"))
                             for paragraph in tree.iter(WORD + "p"))
            return [("body", text)]
    content = payload.decode("utf-8-sig")
    if any(ord(char) < 32 and char not in "\r\n\t" for char in content):
        raise ValueError
    if len(content) > MAX_TEXT:
        raise ValueError
    if format_name == "json":
        value = json.loads(content)
        if not isinstance(value, (dict, list)):
            raise ValueError
        content = json.dumps(value, ensure_ascii=False)
    if format_name == "csv":
        rows = csv.reader(StringIO(content), strict=True)
        content = "\n".join(" | ".join(row) for row in rows if row)
    return [("body", content)]


def extract(filename, payload):
    format_name = Path(filename).suffix.lower().lstrip(".")
    if format_name not in FORMATS:
        raise ValueError("Choose a TXT, Markdown, CSV, JSON, PDF, or DOCX file")
    if not SLOTS.acquire(blocking=False):
        raise BlockingIOError("Document extraction is busy")
    try:
        environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
        child = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve()), format_name], input=payload,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment, timeout=5, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        sections = json.loads(child.stdout)
        if not sections:
            raise ValueError
        return sections
    except (ValueError, OSError, subprocess.SubprocessError):
        raise ValueError("No searchable text could be extracted within the file limits") from None
    finally:
        SLOTS.release()


if __name__ == "__main__":
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    payload = sys.stdin.buffer.read(MAX_FILE + 1)
    if len(payload) > MAX_FILE:
        sys.exit(1)
    sections = [(label, re.sub(r"\s+", " ", text).strip()) for label, text in document_text(sys.argv[1], payload)]
    if sum(len(text) for _, text in sections) > MAX_TEXT:
        sys.exit(1)
    sys.stdout.write(json.dumps([(label, text) for label, text in sections if text]))
