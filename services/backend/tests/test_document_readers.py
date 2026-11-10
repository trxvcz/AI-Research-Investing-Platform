"""Generic issuer-neutral reading and refusal of active/archive hazards."""

import hashlib
import io
import zipfile
from uuid import uuid4

import pytest

from alphasense.document_readers import DocumentReadError, read_text_document


def read(raw: bytes, format: str = "xlsx"):
    return read_text_document(raw, document_id=uuid4(), classification="public", format=format)


def workbook(company="Issuer A", *, formula=False, external=False, extra=None):
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    docrel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    files = {
        "xl/workbook.xml": f'<workbook xmlns="{ns}" xmlns:r="{docrel}"><sheets>'
        '<sheet name="Financials" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{rel}">'
        f'<Relationship Id="rId1" Type="{docrel}/worksheet" '
        'Target="/xl/worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": f'<sst xmlns="{ns}"><si><t>{company}</t></si>'
        "<si><t>Operating cash flow</t></si></sst>",
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{ns}"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2">'
        + ('<f>WEBSERVICE("https://evil.invalid")</f>' if formula else "")
        + "<v>1234</v></c></row></sheetData></worksheet>",
    }
    if external:
        files["xl/_rels/workbook.xml.rels"] = files["xl/_rels/workbook.xml.rels"].replace(
            'Target="/xl/', 'TargetMode="External" Target="https://evil.invalid/'
        )
    if extra:
        files.update(extra)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return buffer.getvalue()


@pytest.mark.parametrize("company", ["Issuer A", "Different Issuer B"])
def test_same_reader_preserves_generic_rows_and_raw_hash(company):
    raw = workbook(company)
    result = read(raw)
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    assert result.blocks[0].text == "A1: " + company
    assert result.blocks[1].locator == "Financials!row:2"
    assert result.blocks[1].text == "A2: Operating cash flow | B2: 1234"


def test_text_locators_are_deterministic_and_classification_is_retained():
    result = read(b"Issuer\n\nRevenue 100 PLN", "text")
    assert [b.locator for b in result.blocks] == ["text:line:1", "text:line:3"]
    assert result.classification == "public"


def test_html_only_retains_visible_text_and_no_executable_markup():
    raw = b"<html><head><title>Hidden</title></head><body><script>bad()</script>"
    raw += b"<p>Issuer &amp; Group</p><iframe>hide</iframe><p hidden>private</p>"
    raw += b'<p style="display: none">not visible</p>'
    raw += b"<p>Revenue <b>123</b> PLN</p></body></html>"
    result = read(raw, "html")
    assert [b.text for b in result.blocks] == ["Issuer & Group", "Revenue 123 PLN"]


@pytest.mark.parametrize("format", ["pdf", "unknown"])
def test_unsupported_formats_are_explicit(format):
    with pytest.raises(DocumentReadError, match="DOCUMENT_FORMAT_UNSUPPORTED"):
        read(b"a", format)


@pytest.mark.parametrize("raw", [b"", b"a" * 1048577, b"not a zip"])
def test_raw_and_zip_bounds(raw):
    with pytest.raises(DocumentReadError):
        read(raw)


@pytest.mark.parametrize(
    "extra",
    [
        {"../outside.xml": "bad"},
        {"/outside.xml": "bad"},
        {"xl/vbaProject.bin": "bad"},
        {"xl/externalLinks/link.xml": "bad"},
        {"xl/x.xml": '<!DOCTYPE x [<!ENTITY bad "EXPAND">]><x>&bad;</x>'},
        {"xl/x.xml": "<broken"},
    ],
)
def test_archive_and_xml_hazards_are_rejected(extra):
    with pytest.raises(DocumentReadError):
        read(workbook(extra=extra))


def test_external_relationship_is_never_followed():
    with pytest.raises(DocumentReadError, match="DOCUMENT_EXTERNAL_REFERENCE"):
        read(workbook(external=True))


def test_formula_is_rejected_instead_of_using_stale_cached_result():
    with pytest.raises(DocumentReadError, match="DOCUMENT_FORMULA_UNSUPPORTED"):
        read(workbook(formula=True))


def test_unbounded_shared_string_index_has_a_controlled_refusal():
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = (
        f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1" t="s"><v>'
        + "9" * 5000
        + "</v></c></row></sheetData></worksheet>"
    )
    with pytest.raises(DocumentReadError, match="DOCUMENT_CELL_INVALID"):
        read(workbook(extra={"xl/worksheets/sheet1.xml": sheet}))


def test_compression_bomb_and_duplicate_names_are_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.xml", "a" * 100000)
    with pytest.raises(DocumentReadError, match="DOCUMENT_ZIP_LIMIT"):
        read(buffer.getvalue())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("same.xml", "<a/>")
        with pytest.warns(UserWarning):
            archive.writestr("same.xml", "<b/>")
    with pytest.raises(DocumentReadError, match="DOCUMENT_ZIP_PATH"):
        read(buffer.getvalue())


def test_block_and_depth_limits_fail_without_silent_truncation():
    with pytest.raises(DocumentReadError, match="DOCUMENT_TEXT_LIMIT"):
        read(b"line\n" * 513, "text")
    with pytest.raises(DocumentReadError, match="DOCUMENT_HTML_DEPTH"):
        read(b"<div>" * 129 + b"text", "html")
