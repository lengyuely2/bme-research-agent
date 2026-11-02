import xml.etree.ElementTree as ET

import pytest

from bioagent.safety import SafetyError
from bioagent.sandbox import generate


@pytest.mark.parametrize("online", [False, True])
def test_sandbox_has_os_readonly_source_and_separate_output(tmp_path, online):
    app, source, output, configs = [tmp_path / name for name in ("app", "资料 & evidence", "reports", "configs")]
    app.mkdir()
    source.mkdir()
    binary = app / "BioResearch.exe"
    binary.write_bytes(b"test fixture, not an executable")
    path = generate(binary, source, output, online=online, config_dir=configs)
    config = ET.parse(path).getroot()
    folders = config.findall("MappedFolders/MappedFolder")
    assert len(folders) == 3
    assert [f.findtext("ReadOnly") for f in folders] == ["true", "true", "false"]
    assert folders[1].findtext("HostFolder") == str(source)
    assert config.findtext("Networking") == ("Enable" if online else "Disable")
    assert config.findtext("ClipboardRedirection") == "Disable"
    assert config.findtext("vGPU") == "Disable"
    assert config.findtext("ProtectedClient") == "Enable"
    assert str(source) not in config.findtext("LogonCommand/Command")
    assert path.parent == configs
    assert not path.is_relative_to(output)


def test_sandbox_refuses_nested_writable_mapping(tmp_path):
    app, source = tmp_path / "app", tmp_path / "source"
    app.mkdir()
    source.mkdir()
    binary = app / "BioResearch.exe"
    binary.write_bytes(b"test")
    with pytest.raises(SafetyError):
        generate(binary, source, app / "reports", config_dir=tmp_path / "configs")
