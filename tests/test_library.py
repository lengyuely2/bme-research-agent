import io
import json
import socket
import threading

import pytest

from bioagent.library import Cancelled, Library, extract, table_summary
from bioagent.safety import digest


def test_index_search_stats_are_offline_and_preserve_sources(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "IL6.txt").write_text("IL6 炎症研究。样本量不足，结论存在局限。", encoding="utf-8")
    (root / "data.csv").write_text("patient_id,IL6\nprivate_patient_a,1\nprivate_patient_b,3\n", encoding="utf-8")
    before = {p.name: digest(p.read_bytes()) for p in root.iterdir()}
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline indexing attempted a network connection")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    library = Library.load(root)
    assert len(library.sources) == 2
    assert library.search("炎症")[0].evidence.source == "IL6.txt"
    assert library.search("IL6")
    table = next(e for e in library.evidence if e.table)
    assert "private_patient" not in table.text
    assert json.loads(table.text)["columns"][1]["mean"] == 2
    assert before == {p.name: digest(p.read_bytes()) for p in root.iterdir()}


def test_stats_missing_invalid_and_sample_sd():
    summary = json.loads(table_summary("value,group\n1,A\n3,B\n,A\nNaN,B\ninf,B\ntext,A\n"))
    column = summary["columns"][0]
    assert summary["rows"] == 6
    assert column["numeric_n"] == 2
    assert column["missing_n"] == 1
    assert column["non_numeric_or_invalid_n"] == 3
    assert column["mean"] == 2
    assert column["sample_sd"] == pytest.approx(2 ** .5)


@pytest.mark.parametrize("text", ["a,a\n1,2", "a,b\n1,2,3", "a,\n1,2", ""])
def test_invalid_csv_is_rejected(text):
    with pytest.raises(ValueError):
        table_summary(text)


def test_csv_row_limit_fails_instead_of_silently_sampling():
    with pytest.raises(ValueError, match="10,000"):
        table_summary("value\n" + "1\n" * 10001)


def test_pdf_has_page_citations_and_rejects_scanned_blank():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 30 300 Td (IL6 research evidence) Tj ET")
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    page[NameObject("/Contents")] = writer._add_object(stream)
    data = io.BytesIO()
    writer.write(data)
    pages = extract(data.getvalue(), ".pdf")
    assert pages[0][0] == "第 1 页"
    assert "IL6 research" in pages[0][1]
    blank = PdfWriter()
    blank.add_blank_page(width=400, height=400)
    data = io.BytesIO()
    blank.write(data)
    with pytest.raises(ValueError, match="OCR"):
        extract(data.getvalue(), ".pdf")


def test_cancelled_index_never_returns_partial_success(tmp_path):
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        Library.load(tmp_path, event)
