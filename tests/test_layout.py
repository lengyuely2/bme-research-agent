"""Guard against clipping the consent and save actions on smaller Windows displays."""

import tkinter as tk

import pytest

from bioagent.app import App


@pytest.mark.parametrize("size", ["1000x720", "1240x880"])
def test_primary_actions_keep_full_height_at_supported_sizes(size):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("A display with Tk is required")
    try:
        app = App(root)
        root.geometry(size)
        root.update()
        for tab in range(5):
            app.tabs.select(tab)
            root.update()
            for button in app.buttons:
                if button.cget("text") in {"预览并交给 GPT", "生成本地摘录", "保存新报告与操作记录", "生成 Windows Sandbox 启动配置", "保存 PNG 图表", "生成图表", "开始监控"}:
                    if not button.winfo_viewable():
                        continue
                    assert button.winfo_height() >= 30
                    assert button.winfo_rooty() + button.winfo_height() <= root.winfo_rooty() + root.winfo_height()
                    assert button.winfo_rootx() + button.winfo_width() <= root.winfo_rootx() + root.winfo_width()
    finally:
        root.destroy()
