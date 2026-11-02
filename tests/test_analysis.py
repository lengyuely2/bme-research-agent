import json

import pytest

from bioagent.analysis import CHART_TYPES, Dataset, render_chart
from bioagent.agent import EvidenceTools, Packet, tools_for
from bioagent.library import Evidence
from bioagent.safety import ReportStore, SafetyError, digest


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    path = root / "signal.csv"
    path.write_text("time_s,EMG_mV,subject\n0,1,private_a\n1,2,private_b\n2,,private_c\n3,NaN,private_d\n4,4,private_e\n", encoding="utf-8")
    return Dataset.load(path)


@pytest.mark.parametrize("kind", CHART_TYPES)
def test_charts_exclude_invalid_values_and_preserve_input(dataset, kind):
    original = (dataset.root / dataset.name).read_bytes()
    chart = render_chart(dataset, kind, "time_s", "EMG_mV")
    assert chart.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert chart.used == 3
    assert chart.excluded == 2
    assert digest(original) == dataset.sha256
    assert (dataset.root / dataset.name).read_bytes() == original


def test_plot_parameters_are_not_executable(dataset):
    with pytest.raises(SafetyError):
        render_chart(dataset, "run Python", "time_s", "EMG_mV")
    with pytest.raises(SafetyError):
        render_chart(dataset, "折线图", "../../secret", "EMG_mV")


def test_agent_approved_plotting_keeps_raw_rows_local(dataset, monkeypatch):
    evidence = Evidence("S900-C0001", dataset.name, "统计", dataset.summary, dataset.sha256, True)
    packet = Packet("绘图", (evidence,), dataset)
    assert "private_a" not in packet.serialized()
    assert "private_a" not in packet.manifest()
    tools = EvidenceTools(packet)
    result = json.loads(tools.invoke("plot_data", '{"kind":"折线图","x":"time_s","y":"EMG_mV"}'))
    assert result["used_rows"] == 3
    assert "private" not in json.dumps(result)
    assert len(tools.charts) == 1
    with pytest.raises(SafetyError):
        tools.invoke("plot_data", '{"kind":"折线图","x":"time_s","y":"EMG_mV","path":"secret"}')
    with pytest.raises(SafetyError):
        tools.invoke("plot_data", '{"kind":"折线图","x":"time_s","y":"subject"}')
    assert "plot_data" not in {t["name"] for t in tools_for(Packet("q", (evidence,)))}


def test_chart_saving_is_exclusive_and_disjoint(dataset, tmp_path):
    chart = render_chart(dataset, "散点图", "time_s", "EMG_mV")
    store = ReportStore(tmp_path / "reports", dataset.root)
    first, second = store.create_chart(chart.png), store.create_chart(chart.png)
    assert first != second
    assert first.read_bytes() == chart.png
    with pytest.raises(SafetyError):
        ReportStore(dataset.root / "output", dataset.root)
    with pytest.raises(SafetyError):
        store.create_chart(b"not a PNG")
