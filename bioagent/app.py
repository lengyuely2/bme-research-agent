from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .agent import (DEFAULT_MODEL, INSTRUCTIONS, Packet, ResearchAgent, tools_for,
                    cloud_report, local_report, openai_client)
from .library import Cancelled, Library
from .safety import ReportStore, SafetyError

PROJECT = Path(__file__).resolve().parents[1]
if getattr(sys, "frozen", False):
    PROJECT = Path(sys.executable).resolve().parent
    DEFAULT_OUTPUT = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "BioResearchReports"
else:
    DEFAULT_OUTPUT = PROJECT / "output"
SAMPLES = Path(getattr(sys, "_MEIPASS", PROJECT)) / "samples"

SAFETY_TEXT = """你的资料如何被保护

原始资料通过只读文件句柄读取。程序没有删除、移动原文件、写回原文件或执行任意命令的接口。
只接受选定目录中的 PDF / TXT / MD / CSV / TSV。跳过隐藏目录；拒绝链接、联接点、硬链接与越界路径。
索引保存在内存，退出即释放。CSV 仅整理描述性统计，不将原始数据行交给模型。
模型只拿到本次预览并批准的数据包；其工具不能继续扫描磁盘。报告必须由你点击保存，且只创建新文件。

发送到 OpenAI 的内容

点击“预览并交给 GPT”后，你可以逐项检查问题、相对文件名、位置和片段全文。
只有点击“允许本次发送”后才调用 API；后续工具调用最多 5 轮、16 次，仅使用该数据包。
不自动调用外部数据库或第三方 MCP。API 固定连接 https://api.openai.com/v1，不使用环境中的代理或自定义 API 地址。
Key 只在内存中，日志不包含 Key、问题、文件路径或资料内容。报告本身会含研究资料，请妥善保管。
store=False 用于关闭响应存储，但不等于零留存；请查阅 OpenAI 的数据政策。
关闭窗口或取消可以停止后续请求，不能撤回已发送的数据；正在进行的请求最长等待约 60 秒。

保护边界

本程序的权限检查属于应用级保护，不等同于操作系统沙盒。普通启动时，Python 进程仍继承你的账户权限。
如需更强隔离，请使用附带的 Windows Sandbox 配置生成器：资料和程序只读映射，报告目录单独映射。
沙盒需要系统支持并启用 Windows Sandbox；程序不会自动更改系统功能或资料目录 ACL。
联网模式允许沙盒访问网络，离线模式禁网且不能使用 GPT。不能承诺抵御所有系统漏洞或硬件故障。

研究能力与局限

本版为本地中文/英文词法检索；中英文同义词不会自动关联。可同时输入中文术语和英文基因名称提高召回。
PDF 保留页码；扫描件需先在本地 OCR。本版不运行用户脚本、不做推断统计，也不接管实验设备。
引用检查只能验证证据标识，不能自动证明每个医学结论。演示资料是合成示例，不是医学文献。
本工具用于科研资料辅助，不能作为独立临床决策系统。
"""


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("BME Agent · 生物医学工程工作台")
        root.geometry("1440x900")
        root.minsize(1000, 720)
        root.configure(bg="#edf4f8")
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.library: Library | None = None
        self.matches = ()
        self.report = ""
        self.report_packet: Packet | None = None
        self.report_event = "local_report"
        self.report_calls = ()
        self.busy = False
        self.dataset = None
        self.analysis_packet_dataset = None
        self.chart = None
        self.agent_charts = ()
        self.plot_image = None
        self.original_image = None
        self.photos = {}
        self.folder_monitor = None
        self.monitor_running = False
        self.monitor_scanning = False
        self.monitor_generation = 0
        self.image_generation = 0
        self.buttons: list[ttk.Button] = []
        self.source_var = tk.StringVar(value="尚未选择资料目录")
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.key_var = tk.StringVar(value=os.environ.get("OPENAI_API_KEY", ""))
        self.model_var = tk.StringVar(value=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
        self.status_var = tk.StringVar(value="离线就绪 · 选择资料后即可开始")
        self._style()
        self._build()
        root.after(100, self._poll)
        root.after(2000, self._monitor_tick)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        from .ui import theme
        self.style = theme(self.root)

    def _button(self, parent, text, command, primary=False):
        button = ttk.Button(parent, text=text, command=command,
                            style="Primary.TButton" if primary else "TButton")
        self.buttons.append(button)
        return button

    def _build(self):
        from .ui import build
        build(self, samples=SAMPLES, safety_text=SAFETY_TEXT)

    @staticmethod
    def _set_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if getattr(widget, "markdown", False):
            from .ui import render_markdown
            render_markdown(widget, text)
        else:
            widget.insert("1.0", text)
        widget.configure(state="disabled")

    def navigate(self, index):
        self.tabs.select(index)
        self.sync_navigation()

    def sync_navigation(self):
        index = self.tabs.index(self.tabs.select())
        self.page_title.configure(text=self.tabs.tab(index, "text"))
        for page, button in self.nav_buttons.items():
            button.configure(style="Selected.Nav.TButton" if page == index else "Nav.TButton")

    def new_research(self):
        self.question.delete("1.0", "end")
        self.chat_mode.set("自动判断")
        self.question_placeholder.place(x=3, y=3)
        self._fill(())
        self.navigate(0)
        self.status_var.set("新的研究问题 · 已载入的资料仍可使用")

    def use_prompt(self, text):
        self.question.delete("1.0", "end")
        self.question.insert("1.0", text)
        self.question_placeholder.place_forget()
        self.navigate(0)
        self.question.focus_set()

    def _store(self, output=None, extra_root=None):
        output = Path(output or self.output_var.get())
        roots = [r for r in (self.library.root if self.library else None,
                            self.dataset.root if self.dataset else None,
                            self.report_packet.dataset.root if self.report_packet and self.report_packet.dataset else None,
                            self.folder_monitor.root if self.folder_monitor else None,
                            extra_root) if r is not None]
        if not roots:
            return ReportStore(output, None)
        stores = [ReportStore(output, root) for root in roots]
        return stores[0]

    def choose_dataset(self):
        path = filedialog.askopenfilename(title="选择 BME 实验数据", parent=self.root,
            filetypes=[("实验数据", "*.csv *.tsv")])
        if not path:
            return
        self.load_dataset(Path(path))

    def load_dataset(self, path):
        from .analysis import Dataset
        try:
            self._store(extra_root=Path(path).parent)
        except SafetyError as exc:
            messagebox.showerror("目录不符合要求", str(exc), parent=self.root)
            return
        def worker():
            self.events.put(("progress", "正在本地读取数据并计算描述统计…"))
            self.events.put(("dataset", Dataset.load(Path(path))))
        self._start(worker)

    def make_chart(self):
        if self.dataset is None:
            messagebox.showinfo("先导入数据", "请先导入 CSV / TSV 实验数据。", parent=self.root)
            return
        from .analysis import render_chart
        self.agent_charts = ()
        self.chart_gallery_row.pack_forget()
        data, kind, x, y = self.dataset, self.chart_kind.get(), self.chart_x.get(), self.chart_y.get()
        def worker():
            self.events.put(("progress", "正在本地生成图表…"))
            self.events.put(("chart", render_chart(data, kind, x, y)))
        self._start(worker)

    def show_dataset_summary(self):
        if self.dataset is None:
            messagebox.showinfo("先导入数据", "请先导入实验数据。", parent=self.root)
            return
        from .ui import BG, text_area
        dialog = tk.Toplevel(self.root)
        dialog.title("本地描述统计")
        dialog.configure(bg=BG)
        dialog.geometry("760x620")
        dialog.transient(self.root)
        view = text_area(dialog, height=20)
        view.pack(fill="both", expand=True, padx=20, pady=20)
        self._set_text(view, self.dataset.name + "\n\n" + self.dataset.summary)

    def discuss_dataset(self):
        if self.dataset is None:
            self.choose_dataset()
            return
        from .library import Evidence
        data = self.dataset
        evidence = Evidence("S900-C0001", data.name, "本地描述统计（不含原始行）", data.summary, data.sha256, True)
        self._fill((evidence,))
        self.analysis_packet_dataset = data
        self.chat_mode.set("结合资料")
        self.question.delete("1.0", "end")
        self.question.insert("1.0", "请分析这份 BME 实验数据的描述统计、采样和测量局限，并按需要调用本地绘图工具生成合适的图表。")
        self.question_placeholder.place_forget()
        self.navigate(0)
        self.status_var.set("已准备本地统计与绘图权限 · 修改问题后可预览交给 GPT")

    def save_chart(self):
        if self.chart is None or self.dataset is None:
            messagebox.showinfo("先生成图表", "导入数据并生成图表后即可保存。", parent=self.root)
            return
        try:
            path = self._store().create_chart(self.chart.png)
            self.status_var.set(f"图表已保存：{path.name}")
            messagebox.showinfo("已创建新图表", str(path), parent=self.root)
        except (OSError, SafetyError):
            messagebox.showerror("无法保存", "请检查独立结果目录和写入权限。", parent=self.root)

    def _fit_preview(self, widget, original, key):
        if original is None or not widget.winfo_viewable():
            return
        from PIL import ImageTk
        width, height = max(30, widget.winfo_width()-24), max(30, widget.winfo_height()-24)
        cache_key = (id(original), width, height)
        if self.photos.get(key, (None, None))[0] == cache_key:
            return
        image = original.copy()
        image.thumbnail((width, height))
        photo = ImageTk.PhotoImage(image, master=self.root)
        self.photos[key] = (cache_key, photo)
        widget.configure(image=photo, text="")

    def resize_plot(self):
        self._fit_preview(self.plot_label, self.plot_image, "plot")

    def select_agent_chart(self):
        index = self.gallery_combo.current()
        if 0 <= index < len(self.agent_charts):
            self.events.put(("chart", self.agent_charts[index]))

    def resize_image(self):
        self._fit_preview(self.image_label, self.original_image, "monitor")

    def choose_monitor_folder(self):
        folder = filedialog.askdirectory(title="选择只读监控的图片文件夹", parent=self.root)
        if folder:
            self.set_monitor_folder(Path(folder))

    def set_monitor_folder(self, root):
        from .monitor import FolderMonitor
        try:
            self._store(extra_root=root)
            self.folder_monitor = FolderMonitor(root)
        except (OSError, SafetyError) as exc:
            messagebox.showerror("目录不符合要求", str(exc), parent=self.root)
            return
        self.monitor_generation += 1
        self.image_generation += 1
        self.monitor_scanning = False
        self.monitor_running = False
        self.image_tree.delete(*self.image_tree.get_children())
        self.original_image = None
        self.image_label.configure(image="", text="选择一张图片预览。")
        self.monitor_info.configure(text=str(self.folder_monitor.root))
        self.monitor_badge.configure(text="●  已连接 · 未开始")
        self._scan_monitor()

    def start_monitor(self):
        if not self.folder_monitor:
            self.choose_monitor_folder()
        if self.folder_monitor:
            self.monitor_running = True
            self.monitor_badge.configure(text="●  监控中", fg="#6d86ac")
            self._scan_monitor()

    def stop_monitor(self):
        self.monitor_running = False
        self.monitor_badge.configure(text="●  已暂停", fg="#7d8c9c")

    def _monitor_tick(self):
        if self.monitor_running:
            self._scan_monitor()
        self.root.after(2000, self._monitor_tick)

    def _scan_monitor(self):
        if self.monitor_scanning or self.folder_monitor is None:
            return
        monitor, generation = self.folder_monitor, self.monitor_generation
        self.monitor_scanning = True
        def worker():
            try:
                files, changes = monitor.poll()
                self.events.put(("monitor_files", (generation, files, changes)))
            except Exception:
                self.events.put(("monitor_error", generation))
        threading.Thread(target=worker, daemon=True).start()

    def select_monitored_image(self, _event=None):
        selected = self.image_tree.selection()
        if not selected or self.folder_monitor is None:
            return
        self._load_monitored_image(self.image_tree.item(selected[0], "values")[0])

    def _load_monitored_image(self, name):
        from .monitor import image_preview
        monitor = self.folder_monitor
        self.image_generation += 1
        generation = self.image_generation
        def worker():
            try:
                preview, info = image_preview(monitor.root, name)
                self.events.put(("image", (generation, name, preview, info)))
            except Exception:
                self.events.put(("image_error", generation))
        threading.Thread(target=worker, daemon=True).start()

    def _busy(self, active: bool):
        self.busy = active
        for button in self.buttons:
            button.configure(state="disabled" if active else "normal")
        self.cancel_button.configure(state="normal" if active else "disabled")
        if active:
            self.cancel_button.pack(side="right", before=self.send_button, padx=3)
        else:
            self.cancel_button.pack_forget()
        if active:
            self.cancel = threading.Event()

    def _start(self, worker):
        self._busy(True)
        def wrapped():
            try:
                worker()
            except Cancelled:
                self.events.put(("error", "任务已取消。已发送的数据无法撤回。"))
            except SafetyError as exc:
                self.events.put(("error", str(exc)))
            except Exception as exc:
                # Never display SDK response bodies or raw exception strings containing secrets.
                name = type(exc).__name__
                messages = {"AuthenticationError": "API Key 无效或已过期。", "RateLimitError": "API 配额不足或请求过于频繁。",
                            "APITimeoutError": "API 请求超时，请检查网络后重试。", "APIConnectionError": "无法连接 OpenAI；本程序不使用系统代理。",
                            "NotFoundError": "模型不存在或当前账户无权访问，请修改模型名称。", "BadRequestError": "API 不接受当前模型或请求参数，请检查模型是否支持 Responses 与函数调用。"}
                self.events.put(("error", messages.get(name, "操作未完成。请检查文件格式、网络和模型设置；原文件未写入。")))
            finally:
                self.events.put(("done", None))
        threading.Thread(target=wrapped, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "loaded":
                    self.library = value
                    self.report, self.report_packet, self.report_calls = "", None, ()
                    self._set_text(self.report_view, "")
                    self.source_var.set(str(value.root))
                    self.library_info.configure(text=f"{len(value.sources)} 个文件 · {len(value.evidence)} 个片段\n索引在内存中，未发送到网络")
                    names = "\n".join(s.name for s in value.sources)
                    if value.warnings:
                        names += "\n\n读取提示：\n" + "\n".join(value.warnings)
                    self._set_text(self.source_list, names)
                    self._fill(())
                    self.status_var.set("资料已就绪 · 可以本地检索")
                elif kind == "dataset":
                    self.dataset = value
                    self.agent_charts = ()
                    self.chart_gallery_row.pack_forget()
                    self.chart, self.plot_image = None, None
                    self.plot_label.configure(image="", text="选择横轴、纵轴与图形，然后生成图表。")
                    self.dataset_info.configure(text=f"{value.name}  ·  {len(value.rows):,} 行  ·  {len(value.headers)} 列  ·  {len(value.numeric)} 个可绘图数值列")
                    self.x_combo.configure(values=("行号", *value.numeric))
                    self.y_combo.configure(values=value.numeric)
                    self.chart_x.set(value.numeric[0] if len(value.numeric) > 1 else "行号")
                    self.chart_y.set(value.numeric[1] if len(value.numeric) > 1 else value.numeric[0])
                    self.chart_note.configure(text="数据已载入，原始文件未修改。可查看描述统计或选择列生成图表。")
                    self.navigate(3)
                    self.status_var.set("实验数据已载入 · 未联网")
                elif kind == "chart":
                    import io
                    from PIL import Image
                    self.chart = value
                    with Image.open(io.BytesIO(value.png)) as image:
                        self.plot_image = image.copy()
                    self.chart_note.configure(text=value.note)
                    self.resize_plot()
                    self.status_var.set("图表已生成 · 未保存 · 原始数据未修改")
                elif kind == "monitor_files":
                    generation, files, changes = value
                    if generation != self.monitor_generation:
                        continue
                    self.monitor_scanning = False
                    selection = self.image_tree.selection()
                    selected_name = self.image_tree.item(selection[0], "values")[0] if selection else None
                    names = tuple(self.image_tree.item(i, "values")[0] for i in self.image_tree.get_children())
                    if names != tuple(item.name for item in files):
                        self.image_tree.delete(*self.image_tree.get_children())
                        for index, item in enumerate(files):
                            self.image_tree.insert("", "end", iid=f"image-{index}", values=(item.name,))
                            if item.name == selected_name:
                                self.image_tree.selection_set(f"image-{index}")
                    if changes:
                        newest = changes[0]
                        self.status_var.set(f"发现 {len(changes)} 张新增或更新图片 · {newest.name}")
                        self._load_monitored_image(newest.name)
                    state = "监控中" if self.monitor_running else "已暂停"
                    self.monitor_badge.configure(text=f"●  {state} · {len(files)} 张")
                elif kind == "monitor_error":
                    if value == self.monitor_generation:
                        self.monitor_scanning = False
                        self.monitor_running = False
                        self.monitor_badge.configure(text="●  读取失败 · 已暂停")
                        self.status_var.set("图片目录无法读取，请检查目录、权限和文件数量。")
                elif kind == "image":
                    generation, name, preview, info = value
                    if generation != self.image_generation:
                        continue
                    self.original_image = preview
                    self.resize_image()
                    self.image_details.configure(text=f"{name}  ·  {info['width']} × {info['height']}  ·  {info['mode']}  ·  {info['frames']} 帧（预览首帧） · 未上传")
                elif kind == "image_error":
                    if value == self.image_generation:
                        self.original_image = None
                        self.image_label.configure(image="", text="图片暂时无法预览。\n文件可能尚未写完、格式不支持或超过大小限制。")
                elif kind == "progress":
                    self.status_var.set(value)
                elif kind == "cloud":
                    packet, result, model = value
                    if result.charts:
                        self.dataset = packet.dataset
                        self.agent_charts = result.charts
                        self.gallery_combo.configure(values=tuple(f"图表 {i+1}" for i in range(len(result.charts))))
                        self.gallery_combo.current(len(result.charts)-1)
                        self.chart_gallery_row.pack(fill="x", padx=37, pady=(0, 10), before=self.plot_host)
                        self.events.put(("chart", result.charts[-1]))
                    self.report = cloud_report(packet, result, model)
                    self.report_packet, self.report_calls, self.report_event = packet, result.calls, "cloud_report"
                    self._set_text(self.report_view, self.report)
                    self.tabs.select(1)
                    self.status_var.set("分析完成 · " + ("引用需复核" if result.citation_issues else "报告待保存"))
                elif kind == "error":
                    self.status_var.set(value)
                    messagebox.showinfo("任务状态", value, parent=self.root)
                elif kind == "done":
                    self._busy(False)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def choose_source(self):
        folder = filedialog.askdirectory(title="选择本地科研资料文件夹", parent=self.root)
        if folder:
            self.load(Path(folder))

    def load(self, folder: Path):
        # Tk variables must only be read on the UI thread.
        try:
            self._store(extra_root=folder)
        except SafetyError as exc:
            messagebox.showerror("目录不符合要求", str(exc), parent=self.root)
            return
        output = Path(self.output_var.get())
        def safe_worker():
            self.events.put(("progress", "正在本地读取与索引资料…"))
            ReportStore(output, folder)
            library = Library.load(folder, self.cancel)
            self.events.put(("loaded", library))
        self._start(safe_worker)

    def choose_output(self):
        folder = filedialog.askdirectory(title="选择与资料目录相互独立的结果目录", parent=self.root)
        if folder:
            try:
                if self.library or self.dataset or self.folder_monitor:
                    self._store(output=Path(folder))
                self.output_var.set(folder)
            except SafetyError as exc:
                messagebox.showerror("目录不符合要求", str(exc), parent=self.root)

    def _fill(self, evidence):
        self.matches = tuple(evidence)
        self.analysis_packet_dataset = None
        if self.matches:
            self.hero.pack_forget()
            self.evidence_area.pack(fill="both", expand=True)
            self.question_placeholder.place_forget()
        else:
            self.evidence_area.pack_forget()
            self.hero.pack(fill="both", expand=True)
        self.tree.delete(*self.tree.get_children())
        for item in self.matches:
            self.tree.insert("", "end", iid=item.id, values=(item.id, item.source, item.location))
        self._set_text(self.excerpt, "点击证据查看原文；多选决定本次可以使用的资料。")
        self.arrange_home()

    def search(self):
        if not self.library:
            messagebox.showinfo("先选择资料", "请先选择资料文件夹，或载入演示资料。", parent=self.root)
            return
        query = self.question.get("1.0", "end").strip()
        self._fill(m.evidence for m in self.library.search(query))
        self.status_var.set(f"本地找到 {len(self.matches)} 个相关片段 · 尚未发送到网络")

    def show_all(self):
        if self.library:
            self._fill(self.library.evidence)
            self.status_var.set(f"全部 {len(self.matches)} 个证据片段 · 尚未发送到网络")

    def view_selected(self, _event=None):
        ids = set(self.tree.selection())
        selected = [e for e in self.matches if e.id in ids]
        if selected:
            self._set_text(self.excerpt, "\n\n".join(f"[{e.id}] {e.source}\n{e.location}\n\n{e.text}" for e in selected))

    def packet(self) -> Packet | None:
        try:
            ids = set(self.tree.selection())
            evidence = tuple(e for e in self.matches if e.id in ids) if ids else self.matches[:6]
            mode = self.chat_mode.get()
            if mode == "自由问答" or (mode == "自动判断" and not evidence):
                return Packet(self.question.get("1.0", "end").strip(), (), mode="chat")
            return Packet(self.question.get("1.0", "end").strip(), evidence, self.analysis_packet_dataset)
        except SafetyError as exc:
            messagebox.showinfo("请选择资料", str(exc), parent=self.root)
            return None

    def make_local(self):
        packet = self.packet()
        if packet:
            if packet.mode == "chat":
                messagebox.showinfo("需要本地证据", "本地摘录需要先检索或选择资料。自由问答请使用“预览并交给 GPT”。", parent=self.root)
                return
            self.report, self.report_packet = local_report(packet), packet
            self.report_event, self.report_calls = "local_report", ()
            self._set_text(self.report_view, self.report)
            self.tabs.select(1)
            self.status_var.set("本地摘录已生成 · 未联网 · 报告待保存")

    def prepare_cloud(self):
        if self.library and not self.matches and self.chat_mode.get() != "自由问答":
            self._fill(m.evidence for m in self.library.search(self.question.get("1.0", "end").strip()))
        packet = self.packet()
        if not packet:
            return
        key, model = self.key_var.get().strip(), self.model_var.get().strip()
        if not key:
            messagebox.showinfo("需要 API Key", "请在“连接与设置”中输入 API Key。Key 仅保留在内存中。", parent=self.root)
            self.navigate(2)
            return
        dialog = tk.Toplevel(self.root)
        from .ui import BG, text_area
        dialog.configure(bg=BG)
        dialog.title("发送前预览 · 仅本次授权")
        dialog.geometry("900x720")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="下面的问题、文件名和资料内容可能发送给 OpenAI。", font=("Microsoft YaHei UI", 12, "bold"), padding=16).pack(anchor="w")
        ttk.Label(dialog, text="请先检查患者信息与保密内容。CSV 为统计摘要；不会继续读取其他文件。", padding=(16, 0, 16, 12)).pack(anchor="w")
        preview = text_area(dialog, height=12)
        preview.pack(fill="both", expand=True, padx=16)
        import json
        self._set_text(preview, packet.serialized() + "\n\n—— 固定系统指令 ——\n" + INSTRUCTIONS
                       + "\n\n—— 可用工具定义 ——\n" + json.dumps(tools_for(packet), ensure_ascii=False, indent=2))
        ttk.Label(dialog, text=f"模型：{model} · 资料包 {len(packet.serialized()):,} 字符 · 最多 5 轮 API 请求\n"
                              "store=False 不等于零留存。工具只访问此包；后续请求还包含模型输出与调用记录。", padding=16).pack(anchor="w")
        row = ttk.Frame(dialog, padding=16)
        row.pack(side="bottom", before=dialog.winfo_children()[0], fill="x")
        ttk.Button(row, text="返回修改", command=dialog.destroy).pack(side="left")
        def approve():
            dialog.destroy()
            try:
                check_store = self._store(extra_root=packet.dataset.root if packet.dataset else None)
            except (OSError, SafetyError) as exc:
                messagebox.showerror("结果目录不可用", str(exc), parent=self.root)
                return
            def worker():
                try:
                    with openai_client(key) as client:
                        result = ResearchAgent(client).run(packet, model, self.cancel,
                            lambda text: self.events.put(("progress", text)))
                    # Audit is metadata only; no key, source path, question, or excerpt.
                    check_store.audit("cloud_report", evidence_ids=tuple(e.id for e in packet.evidence),
                                      tool_names=result.calls, packet_hash=packet.sha256)
                    self.events.put(("cloud", (packet, result, model)))
                except Exception:
                    try:
                        check_store.audit("cancelled" if self.cancel.is_set() else "cloud_failed", packet_hash=packet.sha256)
                    except (OSError, SafetyError):
                        pass
                    raise
            self._start(worker)
        ttk.Button(row, text="允许本次发送", style="Primary.TButton", command=approve).pack(side="right")

    def save_report(self):
        if not self.report or not self.report_packet:
            messagebox.showinfo("还没有报告", "请先生成本地摘录或 GPT 研究报告。", parent=self.root)
            return
        try:
            store = self._store()
            path = store.create(self.report)
            try:
                store.audit(self.report_event, evidence_ids=tuple(e.id for e in self.report_packet.evidence),
                            tool_names=self.report_calls, packet_hash=self.report_packet.sha256)
            except (OSError, SafetyError):
                self.status_var.set(f"报告已保存，操作记录未完成：{path.name}")
                messagebox.showinfo("报告已保存", f"报告位置：\n{path}\n\n操作记录写入失败。", parent=self.root)
                return
            self.status_var.set(f"已保存：{path.name}")
            messagebox.showinfo("已创建新报告", str(path), parent=self.root)
        except (OSError, SafetyError) as exc:
            messagebox.showerror("无法保存", str(exc) if isinstance(exc, SafetyError) else "无法写入结果目录，请检查权限。", parent=self.root)

    def prepare_sandbox(self):
        if not self.library:
            messagebox.showinfo("先选择资料", "请先选择资料文件夹。", parent=self.root)
            return
        from .sandbox import generate
        binary = Path(sys.executable) if getattr(sys, "frozen", False) else PROJECT / "dist" / "light" / "BMEWorkbench" / "BMEWorkbench.exe"
        if not binary.exists():
            messagebox.showinfo("先打包桌面程序", "请先运行项目中的 build.ps1 生成独立桌面程序，再创建沙盒配置。", parent=self.root)
            return
        online = messagebox.askyesnocancel("沙盒网络", "是否允许沙盒联网调用 GPT？\n\n是：联网模式，需在沙盒内填写 API Key。\n否：禁网，仅本地检索与统计。\n取消：返回。", parent=self.root)
        if online is None:
            return
        try:
            path = generate(binary, self.library.root, Path(self.output_var.get()), online=online)
            messagebox.showinfo("沙盒配置已生成", f"双击此文件启动（需系统已启用 Windows Sandbox）：\n{path}", parent=self.root)
        except (OSError, SafetyError) as exc:
            messagebox.showerror("无法创建沙盒配置", str(exc), parent=self.root)

    def close(self):
        self.cancel.set()
        self.monitor_running = False
        self.key_var.set("")
        self.root.destroy()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="本地生物医学科研助手")
    parser.add_argument("--source", type=Path, help="启动时载入的资料目录")
    parser.add_argument("--output", type=Path, help="独立的结果目录")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = tk.Tk()
    app = App(root)
    if args.output:
        app.output_var.set(str(args.output))
    if args.smoke_test:
        root.after(350, app.close)
    elif args.source:
        root.after(200, lambda: app.load(args.source))
    root.mainloop()


if __name__ == "__main__":
    main()
