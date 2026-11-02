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
                raise SafetyError("Excel 解压体积或内部文件数量超过限制。")
            if any(x.file_size > 50 * 1024 * 1024 for x in entries):
                raise SafetyError("Excel 内部文件过大，请另存需要的工作表。")
        values = load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
        formulas = None
        try:
            names = tuple(s.title for s in values.worksheets if s.sheet_state == "visible")
            if not names or (sheet is not None and sheet not in names):
                raise SafetyError("请选择文件中一个可见工作表。")
            chosen = sheet or names[0]
            ws = values[chosen]
            if (ws.max_row or 0) > 10001 or (ws.max_column or 0) > 256:
                raise SafetyError("工作表最多 10,000 行数据、64 列；请清理超出范围的格式或另存副本。")
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
                raise SafetyError("工作表为空。")
            width = max((i + 1 for row in rows for i, value in enumerate(row) if value.strip()), default=0)
            from .plate import spark_table
            normalized=spark_table(rows)
            if normalized is None and width>64:
                raise SafetyError('普通工作表最多 64 列；Spark 动力学仪器表可自动转换。')
            output = io.StringIO(newline="")
            csv.writer(output).writerows(row[:width] for row in rows)
            notes = []
            if len(names) > 1:
                notes.append(f"当前仅使用工作表“{chosen}”；其他工作表未发送，可在附件菜单切换。")
            if formula_count:
                notes.append(f"{formula_count} 个公式仅读取文件保存的缓存值，未重算；其中 {missing_cache} 个无缓存值，按缺失处理。")
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
        raise SafetyError("无法解析 Excel，请确认它是有效的 .xlsx 文件。") from exc
