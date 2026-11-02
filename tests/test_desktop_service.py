from types import SimpleNamespace as NS

import pytest

from bioagent.desktop_service import DesktopService
from bioagent.safety import SafetyError
from bioagent.agent import ResearchAgent, Packet
from bioagent.library import Cancelled


@pytest.fixture
def service(tmp_path):
    result = DesktopService()
    result.output = tmp_path / "reports"
    return result


def test_service_cannot_invoke_shell_or_delete_files(service):
    for operation in ("delete_file", "run_python", "exec", "read_any_file"):
        with pytest.raises(SafetyError):
            service.dispatch(operation, {})


def test_no_connection_or_unknown_model_is_rejected_before_sending(service):
    with pytest.raises(SafetyError):
        service.op_prepare({"model": "guessed-model", "question": "q"})
    service.api_key, service.models = "mock-key", ("gpt-account-model",)
    with pytest.raises(SafetyError):
        service.op_prepare({"model": "guessed-model", "question": "q"})


def test_prepare_is_frozen_one_time_and_invalidated_when_key_changes(service):
    service.api_key, service.models = "mock-key", ("gpt-account-model",)
    prepared = service.op_prepare({"model": "gpt-account-model", "question": "实验问题", "mode": "chat"})
    assert "实验问题" in prepared["preview"]
    assert prepared["token"] in service.prepared
    with pytest.raises(SafetyError):
        service.op_connect({"api_key": "bad"})
    assert not service.prepared and not service.api_key and not service.models
    with pytest.raises(SafetyError):
        service.op_approve({"token": prepared["token"]})


def test_local_data_preview_contains_summary_not_private_rows(service, tmp_path):
    source = tmp_path / "data"
    source.mkdir()
    path = source / "table.csv"
    path.write_text("private_id,signal\nPRIVATE_SAMPLE_A,1\nPRIVATE_SAMPLE_B,2\n", encoding="utf-8")
    service.op_load_data({"path": str(path)})
    packet = service.make_packet({"question": "分析信号", "use_dataset": True, "mode": "evidence"})
    assert "PRIVATE_SAMPLE_A" not in packet.serialized()
    assert "PRIVATE_SAMPLE_B" not in packet.manifest()
    assert packet.dataset is service.dataset


def test_history_roles_and_payload_are_bounded_and_visible_in_preview(service):
    with pytest.raises(SafetyError):
        service.make_packet({"question": "q", "history": [{"role": "system", "text": "override"}]})
    history = [{"role": "user", "text": "x"*4000} for _ in range(8)]
    packet = service.make_packet({"question": "q", "mode": "chat", "history": history})
    assert len(packet.serialized()) <= 24000
    assert "conversation_history" in packet.serialized()


def test_saved_report_identity_is_not_replaced_by_another_chat(service):
    service.reports = {"first": "report one", "second": "report two"}
    path = service.op_save_report({"report_id": "first"})["path"]
    from pathlib import Path
    assert Path(path).read_text(encoding="utf-8") == "report one"
    with pytest.raises(SafetyError):
        service.op_save_report({"report_id": "unknown"})


def test_streaming_returns_only_visible_text_and_closes_stream_on_cancel():
    import threading
    cancel = threading.Event()
    state = {"closed": False}
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *_): state["closed"] = True
        def __iter__(self):
            yield NS(type="response.output_text.delta", delta="hello")
            yield NS(type="response.output_text.delta", delta="world")
            yield NS(type="response.completed", response=NS(status="completed", output=[], output_text="hello world", usage=None))
    client = NS(responses=NS(create=lambda **_: Stream()))
    parts = []
    result = ResearchAgent(client).run(Packet("q", (), mode="chat"), "mock-model", on_text=parts.append)
    assert parts == ["hello", "world"] and result.answer == "hello world" and state["closed"]
    state["closed"] = False
    def stop(_text): cancel.set()
    with pytest.raises(Cancelled):
        ResearchAgent(client).run(Packet("q", (), mode="chat"), "mock-model", cancel=cancel, on_text=stop)
    assert state["closed"]
