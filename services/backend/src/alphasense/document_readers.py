"""Bounded format readers, independent of issuer and without document execution."""

import hashlib
import io
import re
import time
import zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID
from xml.etree import ElementTree as ET

from alphasense.document_contracts import (
    DocumentBlock,
    DocumentPacket,
    NumberLocale,
    ReaderVersion,
    validate_reader_options,
)
from alphasense.pdf_reader import PDFReadError, read_pdf_blocks

MAX_RAW = 1048576
MAX_ENTRY = 2097152
MAX_EXPANDED = 8388608
MAX_TEXT = 2097152
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class DocumentReadError(ValueError):
    """A stable refusal, never a path, source body or provider instruction."""


class _Blocks:
    def __init__(self) -> None:
        self.items: list[DocumentBlock] = []
        self.total = 0
        self.deadline = time.monotonic() + 5

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise DocumentReadError("DOCUMENT_TIME_LIMIT")

    def add(self, locator: str, text: str) -> None:
        self.check_time()
        text = text.strip()
        if not text:
            return
        self.total += len(text.encode("utf-8"))
        if len(self.items) >= 512 or len(text) > 32768 or self.total > MAX_TEXT:
            raise DocumentReadError("DOCUMENT_TEXT_LIMIT")
        self.items.append(
            DocumentBlock(block_id=f"block-{len(self.items) + 1}", locator=locator, text=text)
        )


class _VisibleHTML(HTMLParser):
    def __init__(self, blocks: _Blocks, *, preserve_cells: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks = blocks
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []
        self.preserve_cells = preserve_cells

    def flush(self) -> None:
        if self.preserve_cells:
            if not any(part.strip() and part != "|" for part in self.parts):
                self.parts = []
                return
            if self.parts and self.parts[-1] == "|":
                self.parts.pop()
        self.blocks.add(f"html:block:{len(self.blocks.items) + 1}", " ".join(self.parts))
        self.parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.blocks.check_time()
        properties = dict(attrs)
        hidden = (
            tag in {"script", "style", "iframe", "object", "template", "noscript", "head"}
            or "hidden" in properties
            or (properties.get("aria-hidden") or "").lower() == "true"
            or any(
                rule in re.sub(r"\s+", "", properties.get("style") or "").lower()
                for rule in ("display:none", "visibility:hidden")
            )
        )
        inside_cell = self.preserve_cells and any(name in {"td", "th"} for name, _ in self.stack)
        if tag in {"p", "div", "tr", "li", "section", "h1", "h2", "h3", "br"} and (
            not inside_cell or tag == "tr"
        ):
            self.flush()
        if tag not in {"br", "hr", "img", "input", "meta", "link", "wbr", "source", "area"}:
            if len(self.stack) >= 128:
                raise DocumentReadError("DOCUMENT_HTML_DEPTH")
            self.stack.append((tag, hidden or any(item[1] for item in self.stack)))

    def handle_endtag(self, tag: str) -> None:
        inside_cell = self.preserve_cells and any(name in {"td", "th"} for name, _ in self.stack)
        if self.preserve_cells and tag in {"td", "th"}:
            self.parts.append("|")
        if tag in {"p", "div", "tr", "li", "section", "h1", "h2", "h3"} and (
            not inside_cell or tag == "tr"
        ):
            self.flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if not any(item[1] for item in self.stack) and data.strip():
            self.parts.append(data.strip())


def _xml(raw: bytes) -> ET.Element:
    upper = raw.upper()
    if b"\x00" in raw or b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise DocumentReadError("DOCUMENT_XML_UNSAFE")
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError:
        raise DocumentReadError("DOCUMENT_XML_INVALID") from None
    if sum(1 for _ in tree.iter()) > 100000:
        raise DocumentReadError("DOCUMENT_XML_LIMIT")
    return tree


def _xlsx(raw: bytes, blocks: _Blocks) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= 128:
                raise DocumentReadError("DOCUMENT_ZIP_LIMIT")
            names: set[str] = set()
            trees: dict[str, ET.Element] = {}
            total = 0
            for info in infos:
                blocks.check_time()
                name = info.filename
                path = PurePosixPath(name)
                if (
                    not name
                    or path.as_posix() != name.rstrip("/")
                    or name in names
                    or "\\" in name
                    or path.is_absolute()
                    or ".." in path.parts
                    or ":" in name
                    or "\x00" in name
                ):
                    raise DocumentReadError("DOCUMENT_ZIP_PATH")
                names.add(name)
                lowered = name.lower()
                if any(
                    word in lowered
                    for word in ("vba", "externallinks/", "embeddings/", "customui/")
                ):
                    raise DocumentReadError("DOCUMENT_ACTIVE_CONTENT")
                total += info.file_size
                if (
                    info.flag_bits & 1
                    or info.file_size > MAX_ENTRY
                    or total > MAX_EXPANDED
                    or info.file_size > max(1, info.compress_size) * 100
                ):
                    raise DocumentReadError("DOCUMENT_ZIP_LIMIT")
                if info.is_dir():
                    continue
                content = archive.read(info)
                if len(content) != info.file_size:
                    raise DocumentReadError("DOCUMENT_ZIP_INVALID")
                if name.endswith((".xml", ".rels")):
                    if b"macroenabled" in content.lower() or b"vbaproject" in content.lower():
                        raise DocumentReadError("DOCUMENT_ACTIVE_CONTENT")
                    tree = _xml(content)
                    trees[name] = tree
                    if name.endswith(".rels"):
                        for relation in tree:
                            if relation.attrib.get("TargetMode", "Internal") != "Internal":
                                raise DocumentReadError("DOCUMENT_EXTERNAL_REFERENCE")
            workbook = trees.get("xl/workbook.xml")
            relations = trees.get("xl/_rels/workbook.xml.rels")
            if workbook is None or relations is None:
                raise DocumentReadError("DOCUMENT_WORKBOOK_INVALID")
            targets: dict[str, str] = {}
            relation_ids: set[str] = set()
            for relation in relations.findall(REL + "Relationship"):
                target = relation.attrib.get("Target", "")
                path = PurePosixPath(target)
                if ".." in path.parts or "\\" in target or ":" in target:
                    raise DocumentReadError("DOCUMENT_EXTERNAL_REFERENCE")
                key = relation.attrib.get("Id", "")
                if not key or key in relation_ids:
                    raise DocumentReadError("DOCUMENT_WORKBOOK_INVALID")
                relation_ids.add(key)
                if relation.attrib.get("Type", "").endswith("/worksheet"):
                    resolved = target.lstrip("/") if path.is_absolute() else "xl/" + target
                    if not resolved.startswith("xl/worksheets/"):
                        raise DocumentReadError("DOCUMENT_EXTERNAL_REFERENCE")
                    targets[key] = resolved
            shared = trees.get("xl/sharedStrings.xml")
            strings = (
                []
                if shared is None
                else [
                    "".join(part.text or "" for part in node.iter(NS + "t"))
                    for node in shared.findall(NS + "si")
                ]
            )
            sheets = workbook.find(NS + "sheets")
            if sheets is None:
                raise DocumentReadError("DOCUMENT_WORKBOOK_INVALID")
            for sheet in sheets:
                name = sheet.attrib.get("name", "")
                if not name or len(name) > 128:
                    raise DocumentReadError("DOCUMENT_WORKBOOK_INVALID")
                target = targets.get(sheet.attrib.get(DOC_REL + "id", ""), "")
                sheet_tree = trees.get(target)
                if sheet_tree is None:
                    raise DocumentReadError("DOCUMENT_WORKBOOK_INVALID")
                seen_cells: set[str] = set()
                for row in sheet_tree.findall(f"{NS}sheetData/{NS}row"):
                    blocks.check_time()
                    values = []
                    row_id = row.attrib.get("r", "")
                    if not re.fullmatch(r"[1-9][0-9]{0,6}", row_id):
                        raise DocumentReadError("DOCUMENT_CELL_INVALID")
                    for cell in row.findall(NS + "c"):
                        ref = cell.attrib.get("r", "")
                        if (
                            not re.fullmatch(r"[A-Z]{1,3}" + re.escape(row_id), ref)
                            or ref in seen_cells
                        ):
                            raise DocumentReadError("DOCUMENT_CELL_INVALID")
                        seen_cells.add(ref)
                        if cell.find(NS + "f") is not None:
                            raise DocumentReadError("DOCUMENT_FORMULA_UNSUPPORTED")
                        kind = cell.attrib.get("t", "n")
                        value = cell.findtext(NS + "v", "")
                        if kind == "s":
                            if not re.fullmatch(r"[0-9]{1,8}", value) or int(value) >= len(strings):
                                raise DocumentReadError("DOCUMENT_CELL_INVALID")
                            value = strings[int(value)]
                        elif kind == "inlineStr":
                            inline = cell.find(NS + "is")
                            value = (
                                ""
                                if inline is None
                                else "".join(part.text or "" for part in inline.iter(NS + "t"))
                            )
                        elif kind not in {"n", "str", "b", "e"}:
                            raise DocumentReadError("DOCUMENT_CELL_UNSUPPORTED")
                        if value:
                            values.append(f"{ref}: {value}")
                    blocks.add(f"{name}!row:{row_id}", " | ".join(values))
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError, OSError):
        raise DocumentReadError("DOCUMENT_ZIP_INVALID") from None


def read_text_document(
    raw: bytes,
    *,
    document_id: UUID,
    classification: Literal["public", "private", "secret"],
    format: Literal["text", "html", "xlsx", "pdf"],
    reader_version: ReaderVersion | None = None,
    number_locale: NumberLocale | None = None,
) -> DocumentPacket:
    """Read issuer-neutral blocks; OCR and spreadsheet formulas remain unsupported."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_RAW:
        raise DocumentReadError("DOCUMENT_RAW_LIMIT")
    try:
        validate_reader_options(format, reader_version, number_locale)
    except ValueError:
        raise DocumentReadError("DOCUMENT_READER_OPTIONS_INVALID") from None
    blocks = _Blocks()
    if format == "xlsx":
        _xlsx(raw, blocks)
    elif format == "pdf":
        try:
            pdf_blocks = read_pdf_blocks(raw)
            # PDF parsing has its own process deadline; start the block-copy
            # deadline after that bounded operation has completed.
            blocks = _Blocks()
            for locator, content in pdf_blocks:
                blocks.add(locator, content)
        except PDFReadError as error:
            raise DocumentReadError(str(error)) from None
    elif format in {"text", "html"}:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError:
            raise DocumentReadError("DOCUMENT_ENCODING_UNSUPPORTED") from None
        if "\x00" in text:
            raise DocumentReadError("DOCUMENT_TEXT_INVALID")
        if format == "text":
            for number, line in enumerate(text.splitlines(), 1):
                blocks.add(f"text:line:{number}", line)
        else:
            parser = _VisibleHTML(blocks, preserve_cells=reader_version == "table-text-v2")
            parser.feed(text)
            parser.close()
            parser.flush()
    else:
        raise DocumentReadError("DOCUMENT_FORMAT_UNSUPPORTED")
    if not blocks.items:
        raise DocumentReadError("DOCUMENT_EMPTY")
    return DocumentPacket(
        schema_version="1.0",
        document_id=document_id,
        sha256=hashlib.sha256(raw).hexdigest(),
        format=format,
        classification=classification,
        blocks=blocks.items,
        reader_version=reader_version,
        number_locale=number_locale,
    )


read_document = read_text_document
