"""Fixed local numerical and plotting operations. Never evaluate user code."""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from pathlib import Path

from .library import decode, table_summary
from .safety import SafetyError, checked_root, digest, read_source

CHART_TYPES = ("Line plot", "Scatter plot", "Histogram", "Box plot")


@dataclass(frozen=True)
class Dataset:
    root: Path
    name: str
    sha256: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    numeric: tuple[str, ...]
    summary: str
    sheet: str = ""
    warnings: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path, sheet: str | None = None):
        root = checked_root(path.parent)
        raw = read_source(root, path.name)
        return cls.from_bytes(root, path.name, raw, sheet)

    @classmethod
    def from_bytes(cls, root: Path, name: str, raw: bytes, sheet: str | None = None):
        suffix = Path(name).suffix.lower()
        if suffix not in {".csv", ".tsv", ".xlsx"}:
            raise SafetyError("Supported data files: CSV / TSV / XLSX.")
        selected, warnings = "", ()
        if suffix == ".xlsx":
            from .tables import spreadsheet_text
            text, _, selected, warnings = spreadsheet_text(raw, sheet)
        else:
            text = decode(raw)
        delim = "\t" if suffix == ".tsv" else ","
        summary = table_summary(text, delim)  # Validates row/column quotas before retaining data.
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        headers = tuple(next(reader))
        rows = tuple(tuple(row) for row in reader if row and any(c.strip() for c in row))
        numeric = []
        for index, header in enumerate(headers):
            if any(number(row[index]) is not None for row in rows):
                numeric.append(header)
        if not numeric:
            raise SafetyError("No finite numeric columns are available for plotting.")
        if selected:
            summary = f"Worksheet: {selected}\n" + "\n".join(warnings) + "\n" + summary
        return cls(root, name, digest(raw), headers, rows, tuple(numeric), summary, selected, warnings)


def number(text: str) -> float | None:
    try:
        value = float(text)
        return value if math.isfinite(value) and abs(value) <= 1e100 else None
    except ValueError:
        return None


@dataclass(frozen=True)
class Chart:
    png: bytes
    used: int
    excluded: int
    note: str


def render_chart(data: Dataset, kind: str, x: str, y: str) -> Chart:
    if kind not in CHART_TYPES or y not in data.numeric:
        raise SafetyError("Select a supported chart and numeric columns.")
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    yi = data.headers.index(y)
    y_values = [number(row[yi]) for row in data.rows]
    paired = kind in {"Line plot", "Scatter plot"}
    if paired:
        if x not in data.numeric and x != "Row index":
            raise SafetyError("The X axis requires a numeric column or Row index.")
        xi = data.headers.index(x) if x != "Row index" else None
        x_values = [float(i + 1) if xi is None else number(row[xi]) for i, row in enumerate(data.rows)]
        pairs = [(a, b) for a, b in zip(x_values, y_values) if a is not None and b is not None]
        if not pairs:
            raise SafetyError("No rows have valid values on both selected axes.")
        xs, ys = zip(*pairs)
    else:
        ys = tuple(v for v in y_values if v is not None)
        if not ys:
            raise SafetyError("The selected column contains no valid data.")
    fig = Figure(figsize=(9.6, 5.0), dpi=140, facecolor="#ffffff")
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.set_facecolor("#ffffff")
    # Fonts are bundled on Windows; fall back when installed elsewhere.
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "DejaVu Sans"]
    if kind == "Line plot":
        ax.plot(xs, ys, color="#8187df", linewidth=1.8, marker="o" if len(ys) < 40 else None, markersize=4)
    elif kind == "Scatter plot":
        ax.scatter(xs, ys, c="#8187df", s=28, alpha=.85, edgecolors="none")
    elif kind == "Histogram":
        ax.hist(ys, bins="auto", color="#8187df", edgecolor="#ffffff", alpha=.9)
    else:
        ax.boxplot(ys, patch_artist=True, boxprops={"facecolor": "#8187df", "alpha": .8},
                   medianprops={"color": "#6557a5"}, whiskerprops={"color": "#9cabc2"}, capprops={"color": "#9cabc2"})
        ax.set_xticks([1], [y])
    ax.set_title(f"{data.name}  ·  {y}", loc="left", color="#344257", fontsize=13, pad=22)
    ax.set_xlabel(x if paired else (y if kind == "Histogram" else ""), color="#7f8ea0", labelpad=12)
    ax.set_ylabel("Count" if kind == "Histogram" else y, color="#7f8ea0", labelpad=12)
    ax.tick_params(colors="#7f8ea0", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#dfe6ee")
    ax.grid(alpha=.15, color="#a2b1c3", linewidth=.5)
    ax.set_axisbelow(True)
    fig.subplots_adjust(left=.12, right=.97, top=.84, bottom=.17)
    fig.text(.12, .025, f"BME WORKBENCH   /   n = {len(ys)}   /   descriptive visualization", color="#98a6b8", fontsize=8)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    excluded = len(data.rows) - len(ys)
    note = f"Kept {len(ys)} rows; excluded {excluded} missing or nonfinite rows. No smoothing, interpolation, or automatic outlier filtering."
    if paired:
        note += " Lines follow source record order; X values are not sorted." if kind == "Line plot" else ""
    return Chart(buf.getvalue(), len(ys), excluded, note)
