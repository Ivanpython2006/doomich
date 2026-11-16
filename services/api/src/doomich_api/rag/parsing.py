"""Разбор документов в блоки текста с номерами страниц и разделами.

Базовые парсеры работают без моделей и GPU (pypdf, python-docx, openpyxl, python-pptx).
Если установлен Docling (``pip install doomich-api[docling]``), PDF разбирается им —
лучше таблицы и сканы с OCR.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass

log = logging.getLogger(__name__)

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
TXT = "text/plain"
MD = "text/markdown"

EXTENSIONS = {".pdf": PDF, ".docx": DOCX, ".xlsx": XLSX, ".pptx": PPTX, ".txt": TXT, ".md": MD}


class ParseError(ValueError):
    pass


@dataclass
class Block:
    text: str
    page: int | None = None
    section: str | None = None
    is_table: bool = False


def sniff_mime(filename: str, data: bytes) -> str:
    """Тип файла по сигнатуре (а не только по расширению)."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"PK\x03\x04"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile as exc:
            raise ParseError("Повреждённый файл Office") from exc
        if "word/document.xml" in names:
            return DOCX
        if "xl/workbook.xml" in names:
            return XLSX
        if "ppt/presentation.xml" in names:
            return PPTX
        raise ParseError("Неподдерживаемый формат архива")
    if ext in {".txt", ".md"}:
        try:
            data[:4096].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParseError("Текстовый файл должен быть в UTF-8") from exc
        return EXTENSIONS[ext]
    raise ParseError("Поддерживаются PDF, DOCX, XLSX, PPTX, TXT и MD")


def parse_document(data: bytes, mime: str, max_pages: int = 300) -> tuple[list[Block], int]:
    """Вернуть блоки и число страниц (листов, слайдов)."""
    if mime == PDF:
        return _parse_pdf(data, max_pages)
    if mime == DOCX:
        return _parse_docx(data)
    if mime == XLSX:
        return _parse_xlsx(data)
    if mime == PPTX:
        return _parse_pptx(data, max_pages)
    if mime in {TXT, MD}:
        text = data.decode("utf-8", errors="replace")
        return _split_markdown(text), 1
    raise ParseError(f"Неподдерживаемый тип: {mime}")


def _parse_pdf(data: bytes, max_pages: int) -> tuple[list[Block], int]:
    try:
        docling_blocks = _parse_with_docling(data)
        if docling_blocks is not None:
            return docling_blocks
    except Exception:
        log.exception("Docling не смог разобрать PDF, используем pypdf")
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseError("PDF защищён паролем")
        pages = len(reader.pages)
    except PdfReadError as exc:
        raise ParseError(f"Не удалось прочитать PDF: {exc}") from exc
    if pages > max_pages:
        raise ParseError(f"Слишком много страниц: {pages} (максимум {max_pages})")
    blocks = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(Block(text=_clean(text), page=number))
    if not blocks:
        raise ParseError("В PDF нет текстового слоя (скан). Распознавание сканов появится в R1.1")
    return blocks, pages


def _parse_with_docling(data: bytes) -> tuple[list[Block], int] | None:
    try:
        from docling.datamodel.base_models import DocumentStream
        from docling.document_converter import DocumentConverter
    except ImportError:
        return None
    result = DocumentConverter().convert(DocumentStream(name="doc.pdf", stream=io.BytesIO(data)))
    doc = result.document
    blocks: list[Block] = []
    for item, _level in doc.iterate_items():
        text = getattr(item, "text", None)
        prov = getattr(item, "prov", None) or []
        page = prov[0].page_no if prov else None
        if hasattr(item, "export_to_markdown") and item.__class__.__name__ == "TableItem":
            blocks.append(Block(text=item.export_to_markdown(doc), page=page, is_table=True))
        elif text:
            blocks.append(Block(text=text, page=page))
    pages = len(doc.pages) if getattr(doc, "pages", None) else 0
    return blocks, pages


def _parse_docx(data: bytes) -> tuple[list[Block], int]:
    import docx

    document = docx.Document(io.BytesIO(data))
    blocks: list[Block] = []
    section: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            blocks.append(Block(text="\n".join(buffer), section=section))
            buffer.clear()

    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = docx.text.paragraph.Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
            if style.startswith(("heading", "заголовок", "title")):
                flush()
                section = text[:500]
            else:
                buffer.append(text)
        elif tag == "tbl":
            flush()
            table = docx.table.Table(child, document)
            rows = [[cell.text.strip().replace("\n", " ") for cell in row.cells] for row in table.rows]
            if rows:
                blocks.append(Block(text=_markdown_table(rows), section=section, is_table=True))
    flush()
    return blocks, 1


def _parse_xlsx(data: bytes) -> tuple[list[Block], int]:
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    blocks: list[Block] = []
    for index, sheet in enumerate(workbook.worksheets, start=1):
        rows = []
        for row in sheet.iter_rows(values_only=True):
            values = ["" if v is None else str(v).strip() for v in row]
            if any(values):
                rows.append(values)
        if not rows:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        header, body = rows[0], rows[1:]
        # большие таблицы режем на части, повторяя заголовок
        step = 25
        for start in range(0, max(1, len(body)), step):
            part = body[start : start + step]
            blocks.append(Block(text=_markdown_table([header, *part]), page=index, section=sheet.title, is_table=True))
    workbook.close()
    return blocks, len(workbook.worksheets)


def _parse_pptx(data: bytes, max_pages: int) -> tuple[list[Block], int]:
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(data))
    slides = list(presentation.slides)
    if len(slides) > max_pages:
        raise ParseError(f"Слишком много слайдов: {len(slides)}")
    blocks = []
    for number, slide in enumerate(slides, start=1):
        texts = []
        title = None
        for shape in slide.shapes:
            if shape.has_text_frame:
                value = shape.text_frame.text.strip()
                if value:
                    if title is None and shape == slide.shapes.title:
                        title = value
                    texts.append(value)
        if texts:
            blocks.append(Block(text="\n".join(texts), page=number, section=title))
    return blocks, len(slides)


def _split_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    section = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if buffer:
                blocks.append(Block("\n".join(buffer).strip(), section=section))
                buffer = []
            section = line.lstrip("#").strip()[:500]
        else:
            buffer.append(line)
    if "\n".join(buffer).strip():
        blocks.append(Block("\n".join(buffer).strip(), section=section))
    return [b for b in blocks if b.text]


def _markdown_table(rows: list[list[str]]) -> str:
    def esc(value: str) -> str:
        return value.replace("|", "/")

    header = "| " + " | ".join(esc(c) for c in rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join([header, sep, *body])


def _clean(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    joined = "\n".join(lines)
    # склеиваем переносы слов «авто-\nматически»
    return joined.replace("-\n", "")
