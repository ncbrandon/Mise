"""Text/image extraction from uploaded documents."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile


def kind_of(filename: str, content_type: str, data: bytes) -> str:
    name = (filename or "").lower()
    ct = (content_type or "").lower()
    if data[:4] == b"%PDF" or name.endswith(".pdf") or "pdf" in ct:
        return "pdf"
    if name.endswith(".docx") or "wordprocessingml" in ct:
        return "docx"
    if ct.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif")):
        return "image"
    if name.endswith((".html", ".htm")) or "html" in ct:
        return "html"
    return "text"


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for p in reader.pages[:30]:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            continue
    return "\n".join(pages).strip()


def pdf_images(data: bytes, max_pages: int = 4) -> list[bytes]:
    """Rasterize the first pages of a scanned PDF (needs poppler's pdftoppm)."""
    if not shutil.which("pdftoppm"):
        return []
    tmp = tempfile.mkdtemp(prefix="mise-pdf-")
    try:
        src = os.path.join(tmp, "in.pdf")
        with open(src, "wb") as f:
            f.write(data)
        subprocess.run(["pdftoppm", "-r", "110", "-jpeg", "-l", str(max_pages), src, os.path.join(tmp, "p")],
                       check=True, timeout=60, capture_output=True)
        out = []
        for name in sorted(os.listdir(tmp)):
            if name.startswith("p") and name.endswith(".jpg"):
                with open(os.path.join(tmp, name), "rb") as f:
                    out.append(f.read())
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def docx_text(data: bytes) -> str:
    import docx

    d = docx.Document(io.BytesIO(data))
    lines = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            lines.append(" ".join(c.text.strip() for c in row.cells if c.text.strip()))
    return "\n".join(l for l in lines if l.strip())


def plain_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
