"""Bounded, read-only Excel conversion. No macro execution or external-link fetching."""

import csv
import io
from datetime import date, datetime
from zipfile import ZipFile, BadZipFile

from .safety import SafetyError


def spreadsheet_text(raw: bytes, sheet: str | None = None):
    from openpyxl import load_workbook

    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(x.file_size for x in entries) > 100 * 1024 * 1024:
                raise SafetyError("Excel expanded size or member count exceeds the limit.")
            if any(x.file_size > 50 * 1024 * 1024 for x in entries):
                raise SafetyError("An internal Excel file exceeds the size limit. Save the required worksheet separately.")
        values = load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
        formulas = None
        try:
            names = tuple(s.title for s in values.worksheets if s.sheet_state == "visible")
            if not names or (sheet is not None and sheet not in names):
                raise SafetyError("Select a visible worksheet from the file.")
            chosen = sheet or names[0]
            ws = values[chosen]
            if (ws.max_row or 0) > 10001 or (ws.max_column or 0) > 256:
                raise SafetyError("Worksheets are limited to 10,000 records and 64 columns. Clear unused formatting or save a smaller copy.")
            formulas = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            formula_count, missing_cache = 0, 0
            rows = []
            for cached, source in zip(ws.iter_rows(), formulas[chosen].iter_rows()):
                row = []
                for cell, original in zip(cached, source):
                    if original.data_type == "f":
                        formula_count += 1
                        missing_cache += cell.value is None
                    value = cell.value
                    if isinstance(value, (date, datetime)):
                        value = value.isoformat()
                    row.append("" if value is None else str(value))
                rows.append(row)
            while rows and not any(c.strip() for c in rows[-1]):
                rows.pop()
            if not rows:
                raise SafetyError("The worksheet is empty.")
            width = max((i + 1 for row in rows for i, value in enumerate(row) if value.strip()), default=0)
            from .plate import spark_table
            normalized=spark_table(rows)
            if normalized is None and width>64:
                raise SafetyError('Ordinary worksheets are limited to 64 columns. Recognized Spark kinetics tables are converted automatically.')
            output = io.StringIO(newline="")
            csv.writer(output).writerows(row[:width] for row in rows)
            notes = []
            if len(names) > 1:
                notes.append(f'Using worksheet "{chosen}"; other worksheets were not sent. Choose another worksheet if needed.')
            if formula_count:
                notes.append(f"{formula_count} formulas use saved cached values without recalculation; {missing_cache} have no cached value and are treated as missing.")
            if normalized is not None:
                text,extra=normalized;notes.extend(extra)
            else:
                text=output.getvalue()
            return text, names, chosen, tuple(notes)
        finally:
            values.close()
            if formulas is not None:
                formulas.close()
    except SafetyError:
        raise
    except Exception as exc:
        raise SafetyError("Cannot parse Excel. Verify that this is a valid .xlsx file.") from exc
