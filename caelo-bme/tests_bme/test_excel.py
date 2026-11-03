"""Exercise the lazy Excel reader and its English, multi-sheet notices."""
import hashlib
from openpyxl import Workbook
from caelo_core.bme.engine.analysis import Dataset


def test_selected_excel_sheet_is_read_only_and_notices_are_english(tmp_path):
    path = tmp_path / 'experiment.xlsx'
    book = Workbook()
    book.active.title = 'First'
    book.active.append(['concentration', 'signal'])
    book.active.append([0, 12])
    second = book.create_sheet('Second')
    second.append(['concentration', 'signal'])
    second.append([10, 42])
    book.save(path)
    book.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    data = Dataset.load(path, 'Second')
    assert data.rows == (('10', '42'),)
    assert data.sheet == 'Second'
    assert any('other worksheets were not sent' in note for note in data.warnings)
    assert 'Worksheet: Second' in data.summary
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
