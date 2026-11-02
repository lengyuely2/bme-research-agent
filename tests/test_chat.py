from types import SimpleNamespace as NS

import pytest

from bioagent.agent import EvidenceTools, Packet, ResearchAgent, citation_issues, cloud_report, tools_for
from bioagent.library import Evidence
from bioagent.safety import ReportStore, SafetyError


def test_free_questions_need_no_files_and_have_no_local_tools():
    packet = Packet("帮我整理今天的待办", (), mode="chat")
    assert tools_for(packet) == []
    assert not citation_issues("可以先按优先级列出任务。", packet)
    with pytest.raises(SafetyError):
        EvidenceTools(packet).invoke("list_evidence", "{}")
    with pytest.raises(SafetyError):
        Packet("q", (Evidence("S001-C0001", "secret", "", "secret", "a"*64),), mode="chat")


def test_free_chat_request_never_invents_file_context():
    recorded = []
    def create(**kwargs):
        recorded.append(kwargs)
        return NS(status="completed", output=[], output_text="请描述你的实验异常与已做的对照。", usage=None)
    packet = Packet("生物传感实验背景信号偏高怎么办？", (), mode="chat")
    result = ResearchAgent(NS(responses=NS(create=create))).run(packet, "test-model")
    assert recorded[0]["tools"] == []
    assert '"approved_evidence": []' in recorded[0]["input"][0]["content"]
    assert not result.citation_issues
    assert "问答记录" in cloud_report(packet, result, "test-model")


def test_no_source_reports_still_only_create_new_files(tmp_path):
    store = ReportStore(tmp_path / "reports", None)
    first = store.create("first")
    second = store.create("second")
    assert first != second
    assert first.read_text(encoding="utf-8") == "first"
