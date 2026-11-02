import json
import queue
import subprocess
import sys
import threading


def test_stdio_broker_can_initialize_numerical_runtime_and_plot_without_hanging():
    process = subprocess.Popen([sys.executable, "-m", "bioagent.desktop_service"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1)
    output = queue.Queue()
    def read():
        for line in process.stdout:
            output.put(json.loads(line))
    threading.Thread(target=read, daemon=True).start()
    try:
        for identifier, operation, params in ((1, "demo_data", {}),
            (2, "plot", {"kind": "折线图", "x": "time_s", "y": "EMG_mV"})):
            process.stdin.write(json.dumps({"id": identifier, "operation": operation, "params": params}, ensure_ascii=False) + "\n")
            process.stdin.flush()
            result = output.get(timeout=15)
            assert result["ok"], result.get("error")
            assert result["id"] == identifier
        assert result["data"]["image"].startswith("data:image/png;base64,")
    finally:
        process.terminate()
        process.wait(timeout=5)
