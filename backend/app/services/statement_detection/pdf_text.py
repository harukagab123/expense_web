from __future__ import annotations

from pathlib import Path
import re
import zlib


class PdfTextExtractionError(Exception):
    pass


def extract_pdf_text(path: Path, max_pages: int = 6, max_chars: int = 80000) -> str:
    page_text = "\n".join(extract_pdf_pages(path, max_pages=max_pages, max_chars=max_chars))
    if page_text.strip():
        return page_text[:max_chars]
    return _extract_with_fallback(path, max_chars=max_chars)


def extract_pdf_pages(path: Path, max_pages: int = 30, max_chars: int = 250000) -> list[str]:
    pages = _extract_pages_with_pypdf(path, max_pages=max_pages, max_chars=max_chars)
    if any(page.strip() for page in pages):
        return pages
    fallback = _extract_with_fallback(path, max_chars=max_chars)
    return [fallback] if fallback.strip() else []


def _extract_pages_with_pypdf(path: Path, max_pages: int, max_chars: int) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return []

    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        total_chars = 0
        for page in reader.pages[:max_pages]:
            text = page.extract_text() or ""
            remaining_chars = max_chars - total_chars
            if remaining_chars <= 0:
                break
            pages.append(text[:remaining_chars])
            total_chars += len(pages[-1])
        return pages
    except Exception as exc:
        raise PdfTextExtractionError("The PDF could not be read.") from exc


def _extract_with_fallback(path: Path, max_chars: int) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PdfTextExtractionError("The PDF could not be read.") from exc

    chunks: list[str] = []
    for match in re.finditer(rb"(?P<header>.{0,700})stream\r?\n(?P<body>.*?)\r?\nendstream", raw, flags=re.DOTALL):
        header = match.group("header")
        body = match.group("body").strip(b"\r\n")
        if b"FlateDecode" in header:
            try:
                body = zlib.decompress(body)
            except zlib.error:
                continue
        chunks.extend(_extract_text_literals(body))
        if sum(len(chunk) for chunk in chunks) >= max_chars:
            break

    return "\n".join(chunks)[:max_chars]


def _extract_text_literals(stream: bytes) -> list[str]:
    pieces: list[str] = []
    for value in re.findall(rb"\((?:\\.|[^\\)])*\)\s*Tj", stream):
        pieces.append(_decode_pdf_literal(value.rsplit(b")", 1)[0][1:]))

    for array in re.findall(rb"\[(.*?)\]\s*TJ", stream, flags=re.DOTALL):
        for value in re.findall(rb"\((?:\\.|[^\\)])*\)", array):
            pieces.append(_decode_pdf_literal(value[1:-1]))
        for value in re.findall(rb"<([0-9A-Fa-f\s]+)>", array):
            pieces.append(_decode_pdf_hex(value))

    return [piece for piece in pieces if piece]


def _decode_pdf_literal(value: bytes) -> str:
    replacements = {
        rb"\(": b"(",
        rb"\)": b")",
        rb"\\": b"\\",
        rb"\n": b"\n",
        rb"\r": b"\r",
        rb"\t": b"\t",
        rb"\b": b"\b",
        rb"\f": b"\f",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return _decode_bytes(value)


def _decode_pdf_hex(value: bytes) -> str:
    compact = re.sub(rb"\s+", b"", value)
    if len(compact) % 2 == 1:
        compact += b"0"
    try:
        return _decode_bytes(bytes.fromhex(compact.decode("ascii")))
    except ValueError:
        return ""


def _decode_bytes(value: bytes) -> str:
    if value.startswith(b"\xfe\xff"):
        return value[2:].decode("utf-16-be", errors="ignore")
    return value.decode("latin-1", errors="ignore")
