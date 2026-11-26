"""Bounded EXIF header inspection. Nothing in this module decodes image pixels."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import BoundedSemaphore


JPEG_HEADER = b"\xff\xd8\xff"
TIFF_HEADERS = (b"II*\x00", b"MM\x00*")
PREFIX_LIMIT = 512 * 1024
ENTRY_LIMIT = 256
INSPECTION_TIMEOUT = 2
INSPECTION_SLOTS = BoundedSemaphore(2)


class UnreadableMetadata(ValueError):
    pass


class InspectionLimit(ValueError):
    pass


def checked_slice(data, start, size, total):
    end = start + size
    if end > total:
        raise UnreadableMetadata
    if end > len(data):
        raise InspectionLimit
    return data[start:end]


def jpeg_metadata(data, total):
    position = 2
    while position < total:
        marker_byte = checked_slice(data, position, 1, total)[0]
        if marker_byte != 0xff:
            raise UnreadableMetadata
        position += 1
        while checked_slice(data, position, 1, total)[0] == 0xff:
            position += 1
        marker = data[position]
        position += 1
        if marker in (0xd9, 0xda):  # End of image or start of compressed image data.
            return {}
        if marker == 0x01:
            continue
        if marker == 0 or 0xd0 <= marker <= 0xd8:
            raise UnreadableMetadata
        length = int.from_bytes(checked_slice(data, position, 2, total), "big")
        if length < 2:
            raise UnreadableMetadata
        segment = checked_slice(data, position + 2, length - 2, total)
        if marker == 0xe1 and segment.startswith(b"Exif\x00\x00"):
            return tiff_metadata(segment[6:], len(segment) - 6)
        position += length
    raise UnreadableMetadata


def tiff_metadata(data, total):
    header = checked_slice(data, 0, 8, total)
    if not header.startswith(TIFF_HEADERS):
        raise UnreadableMetadata
    order = "little" if header.startswith(b"II") else "big"

    def number(raw):
        return int.from_bytes(raw, order)

    def entries(offset):
        if offset < 8 or offset % 2:
            raise UnreadableMetadata
        count = number(checked_slice(data, offset, 2, total))
        if count > ENTRY_LIMIT:
            raise InspectionLimit
        directory = checked_slice(data, offset + 2, count * 12 + 4, total)
        for index in range(0, count * 12, 12):
            row = directory[index:index + 12]
            yield number(row[:2]), number(row[2:4]), number(row[4:8]), row[8:12]

    fields = {}
    exif_offset = None
    first_directory = number(header[4:8])
    for tag, kind, count, value in entries(first_directory):
        if tag == 0x8769 and kind == 4 and count == 1:
            exif_offset = number(value)
        elif tag == 0x0112 and kind == 3 and count == 1 and 1 <= number(value[:2]) <= 8:
            fields["orientation"] = number(value[:2])
        elif tag in (0x0100, 0x0101) and kind in (3, 4) and count == 1:
            dimension = number(value[:2] if kind == 3 else value)
            if dimension:
                fields["width" if tag == 0x0100 else "height"] = dimension

    if exif_offset is not None:
        if exif_offset == first_directory:
            raise UnreadableMetadata
        for tag, kind, count, value in entries(exif_offset):
            if tag in (0xa002, 0xa003) and kind in (3, 4) and count == 1:
                dimension = number(value[:2] if kind == 3 else value)
                if dimension:
                    fields["width" if tag == 0xa002 else "height"] = dimension
            elif tag == 0x9003 and kind == 2 and count == 20:
                raw = checked_slice(data, number(value), 20, total)
                try:
                    if raw[-1] == 0:
                        fields["capture_time"] = datetime.strptime(
                            raw[:-1].decode("ascii"), "%Y:%m:%d %H:%M:%S",
                        ).isoformat(timespec="seconds")
                except ValueError:
                    continue
    return fields


def inspect_image(content):
    if not content.startswith((JPEG_HEADER, *TIFF_HEADERS)):
        return {"status": "unsupported", "fields": {}}
    if not INSPECTION_SLOTS.acquire(blocking=False):
        return {"status": "unavailable", "fields": {}}
    try:
        empty_env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
        child = subprocess.run(
            [sys.executable, "-I", "-S", str(Path(__file__).resolve()), str(len(content))],
            input=content[:PREFIX_LIMIT], capture_output=True, timeout=INSPECTION_TIMEOUT, check=True,
            env=empty_env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return json.loads(child.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "unavailable", "fields": {}}
    finally:
        INSPECTION_SLOTS.release()


def main():
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
        resource.setrlimit(resource.RLIMIT_AS, (96 * 1024 * 1024, 96 * 1024 * 1024))
    total = int(sys.argv[1])
    data = sys.stdin.buffer.read(PREFIX_LIMIT)
    status, fields = "unreadable", {}
    try:
        fields = jpeg_metadata(data, total) if data.startswith(JPEG_HEADER) else tiff_metadata(data, total)
        status = "extracted" if fields else "no_supported_fields"
    except InspectionLimit:
        status = "limit_reached"
    except UnreadableMetadata:
        pass
    print(json.dumps({"status": status, "fields": fields}))


if __name__ == "__main__":
    main()
