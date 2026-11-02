"""Light research workspace with a centered, compact conversation composer."""

from __future__ import annotations

import tkinter as tk
import re
import math
from tkinter import scrolledtext, ttk

BG = "#edf4f8"
SIDE = "#dceefa"
PANEL = "#ffffff"
INPUT = "#ffffff"
TEXT = "#2e3746"
MUTED = "#7d8c9c"
ACCENT = "#8270d4"
LINE = "#e0e8ef"
FONT = "Microsoft YaHei UI"


def theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT, font=(FONT, 10))
    style.configure("Muted.TLabel", foreground=MUTED, font=(FONT, 9))
    style.configure("Side.TLabel", background=SIDE, foreground=MUTED, font=(FONT, 9))
    style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    style.configure("TButton", background=INPUT, foreground=TEXT, bordercolor=INPUT,
                    lightcolor=INPUT, darkcolor=INPUT, borderwidth=0, relief="flat",
                    padding=(12, 7), font=(FONT, 9))
    style.map("TButton", background=[("active", "#f1f4fb"), ("disabled", "#f1f4f7")],
              foreground=[("disabled", "#a9b5c0")], bordercolor=[("focus", "#a7b9d4")])
    style.configure("Primary.TButton", background=ACCENT, foreground="#ffffff",
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, font=(FONT, 9, "bold"))
    style.map("Primary.TButton", background=[("active", "#9380e2"), ("disabled", "#ede9f7")],
              foreground=[("disabled", "#a6a0b7")])
    style.configure("Quiet.TButton", background=BG, bordercolor=BG, lightcolor=BG, darkcolor=BG, foreground=MUTED)
    style.map("Quiet.TButton", background=[("active", PANEL)])
    style.configure("Nav.TButton", background=SIDE, bordercolor=SIDE, lightcolor=SIDE, darkcolor=SIDE,
                    anchor="w", padding=(9, 8), font=(FONT, 9), foreground="#587690")
    style.map("Nav.TButton", background=[("active", "#e9f5fd")])
    style.configure("Selected.Nav.TButton", background="#eef8ff", bordercolor="#eef8ff",
                    lightcolor="#eef8ff", darkcolor="#eef8ff", foreground=ACCENT)
    style.map("Selected.Nav.TButton", background=[("active", "#f5fbff")])
    style.configure("Composer.TButton", background=INPUT, foreground=MUTED, bordercolor=INPUT,
                    lightcolor=INPUT, darkcolor=INPUT, padding=(7, 6), font=(FONT, 8))
    style.map("Composer.TButton", background=[("active", "#f4f2fb")], foreground=[("disabled", "#bac2cb")])
    style.configure("Composer.TCombobox", borderwidth=0, bordercolor=INPUT, lightcolor=INPUT,
                    darkcolor=INPUT, padding=(3, 4), font=(FONT, 8))
    style.configure("TEntry", fieldbackground=INPUT, foreground=TEXT, bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, padding=9, insertcolor=TEXT, font=(FONT, 10))
    style.configure("TCombobox", fieldbackground=INPUT, background=INPUT, foreground=TEXT,
                    arrowcolor=MUTED, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=8)
    style.map("TCombobox", fieldbackground=[("readonly", INPUT)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", INPUT)], selectforeground=[("readonly", TEXT)])
    root.option_add("*TCombobox*Listbox.background", INPUT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", "#dfeafa")
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground="#506579",
                    borderwidth=0, bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL,
                    rowheight=34, font=(FONT, 9))
    style.map("Treeview", background=[("selected", "#e5eafa")], foreground=[("selected", "#43598c")])
    style.configure("Treeview.Heading", background="#f5f8fb", foreground=MUTED,
                    borderwidth=0, relief="flat", padding=9, font=(FONT, 9))
    style.map("Treeview.Heading", background=[("active", "#eef3fb")])
    style.configure("Vertical.TScrollbar", background="#bed0e0", troughcolor=BG,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG, arrowcolor=MUTED, width=9, arrowsize=9)
    style.configure("Horizontal.TScrollbar", background="#bed0e0", troughcolor=BG,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG, arrowcolor=MUTED, width=9)
    style.configure("TSeparator", background=LINE, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    style.configure("Workspace.TNotebook", background=BG, borderwidth=0, tabmargins=0,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.layout("Workspace.TNotebook.Tab", [])
    root.after_idle(lambda: light_titlebar(root))
    return style


def light_titlebar(root):
    import os
    if os.name != "nt":
        return
    import ctypes
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        for attribute, value in ((20, 0), (35, 0xF8F4ED), (36, 0x46372E)):
            setting = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(setting), ctypes.sizeof(setting))
    except (OSError, AttributeError, tk.TclError):
        pass


def label(parent, text="", *, size=10, color=TEXT, bold=False, bg=None, **kwargs):
    return tk.Label(parent, text=text, bg=bg or parent.cget("background"), fg=color,
                    font=(FONT, size, "bold" if bold else "normal"), bd=0, **kwargs)


def text_area(parent, *, height=5, bg=PANEL, size=10, **kwargs):
    widget = scrolledtext.ScrolledText(parent, height=height, bg=bg, fg=TEXT, insertbackground=ACCENT,
        selectbackground="#dfe7f8", selectforeground="white", font=(FONT, size),
        relief="flat", borderwidth=0, highlightthickness=0, wrap="word", padx=16, pady=14, **kwargs)
    widget.vbar.destroy()
    widget.vbar = ttk.Scrollbar(widget.frame, orient="vertical", command=widget.yview)
    widget.vbar.pack(side="right", fill="y")
    widget.configure(yscrollcommand=widget.vbar.set)
    return widget


def render_markdown(widget, text):
    """Display basic Markdown as local text, never execute or fetch embedded content."""
    for name, size in (("h1", 21), ("h2", 15), ("h3", 12)):
        widget.tag_configure(name, font=(FONT, size, "bold"), foreground=TEXT, spacing1=16, spacing3=8)
    widget.tag_configure("bold", font=(FONT, 10, "bold"), foreground="#34445c")
    widget.tag_configure("code", font=("Consolas", 10), foreground=ACCENT, background=PANEL)
    widget.tag_configure("citation", foreground=ACCENT)
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            widget.insert("end", line + "\n", "code")
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            widget.insert("end", heading.group(2) + "\n", f"h{len(heading.group(1))}")
            continue
        if line.startswith("- "):
            line = "•  " + line[2:]
        for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`|\[S\d{3}-C\d{4}\])", line):
            if part.startswith("**") and part.endswith("**"):
                widget.insert("end", part[2:-2], "bold")
            elif part.startswith("`") and part.endswith("`"):
                widget.insert("end", part[1:-1], "code")
            elif re.fullmatch(r"\[S\d{3}-C\d{4}\]", part):
                widget.insert("end", part, "citation")
            else:
                widget.insert("end", part)
        widget.insert("end", "\n")


class RoundedPanel(tk.Canvas):
    def __init__(self, parent, *, height=140, fill=INPUT, radius=18, padding=16, shadow=False):
        super().__init__(parent, bg=parent.cget("background"), height=height, highlightthickness=0, bd=0)
        self.fill, self.radius, self.padding = fill, radius, padding
        self.shadow = shadow
        self.shadow_shape = self.create_polygon(0, 0, 0, 0, smooth=True, fill="#e6edf4", outline="") if shadow else None
        self.body = tk.Frame(self, bg=fill)
        self.background_shape = self.create_polygon(0, 0, 0, 0, smooth=True, fill=fill, outline=fill)
        self.window = self.create_window(padding, padding, window=self.body, anchor="nw")
        self.bind("<Configure>", self._resize)

    def _resize(self, event):
        w, h, r, p = event.width, event.height, self.radius, self.padding
        if self.shadow:
            h -= 4
            self.coords(self.shadow_shape, r, 4, w-r, 4, w, 4, w, r+4, w, h-r+4, w, h+4,
                        w-r, h+4, r, h+4, 0, h+4, 0, h-r+4, 0, r+4, 0, 4)
        self.coords(self.background_shape, r, 0, w-r, 0, w, 0, w, r, w, h-r, w, h,
                    w-r, h, r, h, 0, h, 0, h-r, 0, r, 0, 0)
        self.itemconfigure(self.window, width=max(1, w-2*p), height=max(1, h-2*p))


class SendButton(tk.Canvas):
    """Small keyboard-accessible send control; always opens the existing approval preview."""
    def __init__(self, parent, command):
        super().__init__(parent, width=32, height=32, bg=INPUT, highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=True)
        self.command = command
        self.disk = self.create_oval(2, 2, 30, 30, fill="#efebff", outline="")
        self.arrow = self.create_line(16, 23, 16, 10, 11, 15, 16, 10, 21, 15,
                                      fill="#9582d5", width=1.7, capstyle="round", joinstyle="round")
        self.bind("<Button-1>", self._invoke)
        self.bind("<Return>", self._invoke)
        self.bind("<space>", self._invoke)
        self.bind("<Enter>", lambda _e: self.itemconfigure(self.disk, fill="#e6dfff"))
        self.bind("<Leave>", lambda _e: self.itemconfigure(self.disk, fill="#efebff"))
        self.bind("<FocusIn>", lambda _e: self.itemconfigure(self.disk, outline="#b8a9e8"))
        self.bind("<FocusOut>", lambda _e: self.itemconfigure(self.disk, outline=""))

    def _invoke(self, _event=None):
        if self.cget("state") != "disabled":
            self.command()
        return "break"

    def cget(self, name):
        return "预览并交给 GPT" if name == "text" else super().cget(name)


def sparkle(parent, size=58):
    canvas = tk.Canvas(parent, width=size, height=size, bg=BG, bd=0, highlightthickness=0)
    base = tuple(int(BG[i:i+2], 16) for i in (1, 3, 5))
    for y in range(0, size, 2):
        for x in range(0, size, 2):
            a = .52 * math.exp(-((x-size*.38)**2 + (y-size*.45)**2)/(size*size*.055))
            b = .48 * math.exp(-((x-size*.63)**2 + (y-size*.57)**2)/(size*size*.05))
            rgb = tuple(round(base[i]*(1-a-b) + (132, 208, 255)[i]*a + (191, 159, 244)[i]*b) for i in range(3))
            color = "#" + "".join(f"{v:02x}" for v in rgb)
            canvas.create_rectangle(x, y, x+2, y+2, fill=color, outline="")
    c = size/2
    canvas.create_polygon(c, c-9, c+3, c-3, c+9, c, c+3, c+3, c, c+9,
                          c-3, c+3, c-9, c, c-3, c-3,
                          fill="", outline="#ffffff", width=1.7, joinstyle="round")
    canvas.create_line(c+10, c-12, c+10, c-6, fill="#ffffff", width=1.5)
    canvas.create_line(c+7, c-9, c+13, c-9, fill="#ffffff", width=1.5)
    return canvas


def arrange_home(app):
    home = app.home
    width, height = home.winfo_width(), home.winfo_height()
    if width < 100 or height < 100:
        return
    composer_width = min(720, width-86)
    if app.matches:
        app.feed.place(x=37, y=12, width=width-74, height=max(160, height-188))
        app.composer_host.place(x=(width-composer_width)//2, y=height-164, width=composer_width, height=155)
    else:
        app.feed.place(relx=.5, rely=.59, anchor="s", width=composer_width, height=173)
        app.composer_host.place(relx=.5, rely=.59, anchor="n", width=composer_width, height=155)


def card(parent, *, padding=18):
    outer = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
    inner = tk.Frame(outer, bg=PANEL)
    inner.pack(fill="both", expand=True, padx=padding, pady=padding)
    return outer, inner


def nav_icon(parent, kind):
    icon = tk.Canvas(parent, width=17, height=20, bg=SIDE, highlightthickness=0)
    options = {"fill": "#7797b0", "width": 1.15, "capstyle": "round", "joinstyle": "round"}
    if kind == "flask":
        icon.create_line(6, 4, 10, 4, **options)
        icon.create_line(7, 4, 7, 8, 3, 16, 13, 16, 9, 8, 9, 4, **options)
        icon.create_line(5, 12, 11, 12, **options)
    elif kind == "chart":
        icon.create_line(3, 4, 3, 16, 15, 16, **options)
        icon.create_line(5, 13, 8, 9, 11, 11, 15, 5, **options)
    elif kind == "image":
        icon.create_rectangle(2, 4, 15, 16, outline="#7797b0", width=1.1)
        icon.create_line(3, 14, 6, 10, 10, 14, 13, 11, 15, 14, **options)
        icon.create_oval(10, 6, 12, 8, outline="#7797b0")
    elif kind == "pulse":
        icon.create_line(1, 11, 5, 11, 7, 6, 10, 15, 12, 10, 16, 10, **options)
    else:
        icon.create_line(12, 3, 3, 3, 3, 17, 14, 17, 14, 6, 12, 3, **options)
        for y in (8, 11, 14):
            icon.create_line(6, y, 11, y, **options)
    return icon


def build(app, *, samples, safety_text):
    root = app.root
    app.sample_dir = samples
    sidebar = tk.Frame(root, bg=SIDE, width=194)
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)
    brand = tk.Frame(sidebar, bg=SIDE)
    brand.pack(fill="x", padx=17, pady=(21, 15))
    logo = tk.Canvas(brand, width=21, height=25, bg=SIDE, highlightthickness=0)
    logo.pack(side="left", padx=(0, 7))
    logo.create_polygon(10, 4, 12, 10, 18, 12, 12, 14, 10, 20, 8, 14, 2, 12, 8, 10,
                        fill="", outline="#6196f1", width=1.5)
    logo.create_line(17, 3, 17, 8, fill="#6196f1", width=1.2)
    logo.create_line(14.5, 5.5, 19.5, 5.5, fill="#6196f1", width=1.2)
    brand_text = tk.Frame(brand, bg=SIDE)
    brand_text.pack(side="left")
    label(brand_text, "BME Agent", size=11, color="#446581", bold=True).pack(anchor="w")
    label(brand_text, "生物传感与疾病检测助手", size=7, color="#7a99af").pack(anchor="w", pady=(3, 0))
    label(sidebar, "研究工作台", size=8, color="#7795ad").pack(anchor="w", padx=20, pady=(10, 10))
    new_button = app._button(sidebar, "＋   新建研究", app.new_research)
    new_button.pack(fill="x", padx=13, pady=(0, 22))
    label(sidebar, "AI 科研功能", size=8, color="#7795ad").pack(anchor="w", padx=20, pady=(0, 10))
    app.nav_buttons = {}
    prompts = {
        "design": "请围绕生物传感与疾病检测，帮我梳理实验目标、传感原理、操作步骤、关键条件、对照设置和结果判定。请先确认缺失信息。",
        "troubleshoot": "我在生物传感/疾病检测实验中遇到问题。请先询问目标物、传感器类型、实验步骤、异常表现和已有对照，再分析可能原因并提出验证与改进方案。",
        "paper": "请基于我提供的论文或实验记录，总结研究目的、传感原理、检测流程、关键参数、对照设置、性能指标和局限，区分原文结果与推断。没有资料时先提示我提供。",
    }
    for title, icon, target in (("实验设计", "flask", "design"), ("数据分析与绘图", "chart", 3),
                                ("图片监控", "image", 4), ("实验问题排查", "pulse", "troubleshoot"),
                                ("论文总结", "paper", "paper"), ("研究报告", "document", 1)):
        row = tk.Frame(sidebar, bg=SIDE)
        row.pack(fill="x", padx=15, pady=1)
        nav_icon(row, icon).pack(side="left", padx=(4, 2))
        command = (lambda i=target: app.navigate(i)) if isinstance(target, int) else (lambda key=target: app.use_prompt(prompts[key]))
        button = ttk.Button(row, text=title, style="Nav.TButton", command=command)
        button.pack(side="left", fill="x", expand=True)
        if isinstance(target, int):
            app.nav_buttons[target] = button
    ttk.Separator(sidebar).pack(fill="x", padx=22, pady=18)
    library_row = tk.Frame(sidebar, bg=SIDE)
    library_row.pack(fill="x", padx=23)
    label(library_row, "本地资料", size=8, color="#7795ad").pack(side="left")
    ttk.Button(library_row, text="＋", width=2, style="Nav.TButton", command=app.choose_source).pack(side="right")
    app.library_info = label(sidebar, "尚未连接资料库", size=9, color=MUTED, wraplength=150, justify="left")
    app.library_info.pack(fill="x", padx=24, pady=(12, 7))
    app.source_list = text_area(sidebar, height=5, bg=SIDE, size=8)
    app.source_list.configure(padx=3, pady=4, fg="#7894a9")
    app.source_list.pack(fill="both", expand=True, padx=17)
    app._set_text(app.source_list, "导入论文或实验记录后，\n在此查看本地资料。")
    bottom = tk.Frame(sidebar, bg=SIDE)
    bottom.pack(side="bottom", before=brand, fill="x", padx=15, pady=17)
    app._button(bottom, "体验合成演示资料", lambda: app.load(samples)).pack(fill="x", pady=(0, 9))
    ttk.Button(bottom, text="连接与设置", style="Nav.TButton", command=lambda: app.navigate(2)).pack(fill="x")
    label(bottom, "● 本地优先   ·   原始资料只读", size=8, color="#7c97a7").pack(pady=(13, 0))

    main = tk.Frame(root, bg=BG)
    main.pack(side="left", fill="both", expand=True)
    top = tk.Frame(main, bg=BG, height=59)
    top.pack(fill="x", padx=27, pady=(16, 5))
    app.page_title = label(top, "研究助手", size=9, color="#7d91a5")
    app.page_title.pack(side="left", pady=8)
    label(top, "生物传感 · 疾病检测", size=8, color="#a0afbd").pack(side="left", padx=12)
    app.mode_badge = label(top, "本地工作区", size=8, color="#91a6b6")
    app.mode_badge.pack(side="right", padx=10)
    footer = tk.Frame(main, bg=BG)
    footer.pack(side="bottom", fill="x", padx=31, pady=(3, 10))
    label(footer, textvariable=app.status_var, size=8, color=MUTED, anchor="w").pack(side="left", fill="x", expand=True)
    label(footer, "v0.2  /  科研参考", size=8, color="#9badbc").pack(side="right")
    app.tabs = ttk.Notebook(main, style="Workspace.TNotebook")
    app.tabs.pack(fill="both", expand=True)
    pages = [tk.Frame(app.tabs, bg=BG) for _ in range(5)]
    for page, title in zip(pages, ("研究助手", "研究报告", "连接与设置", "数据分析与绘图", "图片监控")):
        app.tabs.add(page, text=title)
    app.tabs.bind("<<NotebookTabChanged>>", lambda _event: app.sync_navigation())
    home, report, settings, analysis, monitoring = pages

    app.home = home
    app.composer_host = tk.Frame(home, bg=BG)
    composer_host = app.composer_host
    composer = RoundedPanel(composer_host, height=120, padding=12, radius=17, shadow=True)
    composer.pack(fill="x")
    app.question = tk.Text(composer.body, height=2, bg=INPUT, fg=TEXT, insertbackground=ACCENT,
                           selectbackground="#e5e9fb", font=(FONT, 10), bd=0, relief="flat", wrap="word")
    app.question.pack(fill="both", expand=True, padx=2, pady=(4, 10))
    def enter(event):
        if event.state & 1:
            return None
        if not app.busy:
            app.prepare_cloud()
        return "break"
    app.question.bind("<Return>", enter)
    app.question.bind("<Control-Return>", lambda _e: (app.search(), "break")[1])
    placeholder = label(app.question, "描述研究问题，输入或选择一项科研功能…", size=9, color="#9b9fae", bg=INPUT)
    placeholder.place(x=3, y=3)
    placeholder.bind("<Button-1>", lambda _e: app.question.focus_set())
    app.question.bind("<FocusIn>", lambda _e: placeholder.place_forget())
    app.question.bind("<FocusOut>", lambda _e: placeholder.place(x=3, y=3) if not app.question.get("1.0", "end").strip() else None)
    app.question_placeholder = placeholder
    actions = tk.Frame(composer.body, bg=INPUT)
    actions.pack(fill="x")
    attach = ttk.Button(actions, text="＋", width=2, style="Composer.TButton", command=app.choose_source)
    attach.pack(side="left", padx=(0, 3))
    app.chat_mode = tk.StringVar(value="自动判断")
    ttk.Combobox(actions, textvariable=app.chat_mode, values=("自动判断", "结合资料", "自由问答"),
                 state="readonly", width=8, style="Composer.TCombobox").pack(side="left", padx=(0, 4))
    for title, action in (("本地检索", app.search), ("生成本地摘录", app.make_local)):
        button = app._button(actions, title, action)
        button.configure(style="Composer.TButton")
        button.pack(side="left", padx=1)
    app.send_button = SendButton(actions, app.prepare_cloud)
    app.send_button.pack(side="right", padx=(9, 0))
    app.buttons.append(app.send_button)
    app.cancel_button = ttk.Button(actions, text="停止", command=lambda: app.cancel.set(), state="disabled", style="Composer.TButton")
    label(actions, textvariable=app.model_var, size=8, color="#959bad", bg=INPUT, width=16, anchor="e").pack(side="right", padx=4)
    helper = tk.Frame(composer_host, bg=BG)
    helper.pack(fill="x", padx=2, pady=(7, 0))
    label(helper, "Enter 预览发送 · Shift + Enter 换行", size=7, color="#91a1b4").pack(side="left")
    label(helper, "本地只读 · 发送前确认", size=7, color="#91a1b4").pack(side="right")
    app.feed = tk.Frame(home, bg=BG)
    app.hero = tk.Frame(app.feed, bg=BG)
    app.hero.pack(fill="both", expand=True)
    sparkle(app.hero, 58).pack(pady=(4, 15))
    label(app.hero, "今天，推进哪一步研究？", size=16, bold=True).pack()
    label(app.hero, "让研究思路，走向下一步。", size=10, color="#8190a2").pack(pady=(9, 8))
    hints = tk.Frame(app.hero, bg=BG)
    hints.pack()
    for text in ("生物传感与疾病检测", "实验问题排查", "文献依据溯源"):
        label(hints, "•", size=9, color="#9280dd").pack(side="left", padx=(7, 3))
        label(hints, text, size=7, color="#8d9caf").pack(side="left", padx=(0, 7))
    app.arrange_home = lambda: arrange_home(app)
    home.bind("<Configure>", lambda _e: arrange_home(app))
    root.after_idle(app.arrange_home)
    app.evidence_area = tk.Frame(app.feed, bg=BG)
    row = tk.Frame(app.evidence_area, bg=BG)
    row.pack(fill="x", pady=(5, 12))
    label(row, "本地证据", size=12, bold=True).pack(side="left")
    ttk.Button(row, text="全部片段", style="Quiet.TButton", command=app.show_all).pack(side="right")
    label(app.evidence_area, "Ctrl / Shift 多选，最多 8 项；未选择时使用前 6 项。", size=9, color=MUTED).pack(anchor="w", pady=(0, 12))
    table_frame = tk.Frame(app.evidence_area, bg=PANEL)
    table_frame.pack(fill="both", expand=True)
    app.tree = ttk.Treeview(table_frame, columns=("id", "source", "location"), show="headings", height=4, selectmode="extended")
    for name, title, width in (("id", "证据", 118), ("source", "来源", 250), ("location", "位置", 190)):
        app.tree.heading(name, text=title)
        app.tree.column(name, width=width, minwidth=70)
    tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=app.tree.yview)
    app.tree.configure(yscrollcommand=tree_scroll.set)
    tree_scroll.pack(side="right", fill="y")
    app.tree.pack(fill="both", expand=True)
    app.tree.bind("<<TreeviewSelect>>", app.view_selected)
    label(app.evidence_area, "原文与本地统计", size=9, color=MUTED).pack(anchor="w", pady=(14, 8))
    app.excerpt = text_area(app.evidence_area, height=4)
    app.excerpt.pack(fill="both", expand=True)
    app.excerpt.configure(state="disabled")

    # Report reader uses typography rather than a large raw-form control.
    report_actions = tk.Frame(report, bg=BG)
    report_actions.pack(side="bottom", fill="x", padx=37, pady=10)
    label(report_actions, "仅在点击保存后写入独立结果目录。", size=8, color=MUTED).pack(side="left")
    app._button(report_actions, "保存新报告与操作记录", app.save_report, True).pack(side="right")
    label(report, "研究报告", size=18, bold=True).pack(anchor="w", padx=38, pady=(23, 8))
    label(report, "证据、分析与复核记录，汇集于此。", size=10, color=MUTED).pack(anchor="w", padx=38, pady=(0, 20))
    app.report_view = text_area(report, bg=BG, size=11)
    app.report_view.markdown = True
    app.report_view.configure(spacing1=6, spacing3=7, padx=10, pady=8)
    app.report_view.pack(fill="both", expand=True, padx=28)
    app._set_text(app.report_view, "还没有研究报告。\n\n你可以从研究助手生成本地摘录，或预览资料后交给 GPT 分析。")
    configure_settings(app, settings, safety_text)
    configure_analysis(app, analysis)
    configure_monitor(app, monitoring)
    app.sync_navigation()


def configure_settings(app, page, safety_text):
    action = tk.Frame(page, bg=BG)
    action.pack(side="bottom", fill="x", padx=35, pady=12)
    app._button(action, "生成 Windows Sandbox 启动配置", app.prepare_sandbox).pack(side="right")
    label(page, "连接与设置", size=18, bold=True).pack(anchor="w", padx=37, pady=(22, 8))
    label(page, "按研究需要连接模型、资料和输出目录。", size=10, color=MUTED).pack(anchor="w", padx=37, pady=(0, 20))
    columns = tk.Frame(page, bg=BG)
    columns.pack(fill="x", padx=35)
    for i in range(2):
        columns.columnconfigure(i, weight=1, uniform="settings")
    left, inner = card(columns)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
    label(inner, "GPT 连接", size=12, bold=True).pack(anchor="w")
    label(inner, "API Key · 仅保留在本次会话", size=9, color=MUTED).pack(anchor="w", pady=(16, 7))
    ttk.Entry(inner, textvariable=app.key_var, show="●").pack(fill="x")
    label(inner, "模型名称", size=9, color=MUTED).pack(anchor="w", pady=(13, 7))
    ttk.Entry(inner, textvariable=app.model_var).pack(fill="x")
    label(inner, "没有 Key 也可进行本地分析与绘图。", size=8, color=MUTED).pack(anchor="w", pady=(13, 0))
    right, inner = card(columns)
    right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
    label(inner, "资料与结果", size=12, bold=True).pack(anchor="w")
    label(inner, textvariable=app.source_var, size=9, color=MUTED, wraplength=320, justify="left").pack(anchor="w", pady=(13, 8))
    app._button(inner, "选择资料文件夹", app.choose_source).pack(anchor="w")
    label(inner, textvariable=app.output_var, size=9, color=MUTED, wraplength=320, justify="left").pack(anchor="w", pady=(13, 8))
    app._button(inner, "选择独立结果目录", app.choose_output).pack(anchor="w")
    label(page, "安全与使用边界", size=12, bold=True).pack(anchor="w", padx=37, pady=(22, 9))
    safety = text_area(page, bg=BG, height=5, size=9)
    safety.pack(fill="both", expand=True, padx=25)
    app._set_text(safety, safety_text)


def configure_analysis(app, page):
    footer = tk.Frame(page, bg=BG)
    footer.pack(side="bottom", fill="x", padx=35, pady=(10, 8))
    app.chart_note = label(footer, "全部计算在本地完成。", size=8, color=MUTED, anchor="w", wraplength=650)
    app.chart_note.pack(side="left", fill="x", expand=True)
    app._button(footer, "保存 PNG 图表", app.save_chart, True).pack(side="right", padx=(12, 0))
    app._button(footer, "交给 AI 分析", app.discuss_dataset).pack(side="right", padx=(10, 0))
    heading = tk.Frame(page, bg=BG)
    heading.pack(fill="x", padx=37, pady=(22, 8))
    label(heading, "数据分析与绘图", size=18, bold=True).pack(side="left")
    app._button(heading, "导入 CSV / TSV", app.choose_dataset, True).pack(side="right")
    app._button(heading, "演示数据", lambda: app.load_dataset(app.sample_dir / "EMG_demo.csv")).pack(side="right", padx=8)
    app.dataset_info = label(page, "用实验数据绘制趋势、分布与相关关系。原始文件保持只读。", size=10, color=MUTED)
    app.dataset_info.pack(anchor="w", padx=37, pady=(0, 18))
    options, inner = card(page, padding=12)
    options.pack(fill="x", padx=35, pady=(0, 14))
    app.chart_kind = tk.StringVar(value="折线图")
    app.chart_x = tk.StringVar(value="行号")
    app.chart_y = tk.StringVar()
    from .analysis import CHART_TYPES
    for title, variable, values in (("图形", app.chart_kind, CHART_TYPES), ("横轴", app.chart_x, ("行号",)), ("纵轴", app.chart_y, ())):
        col = tk.Frame(inner, bg=PANEL)
        col.pack(side="left", fill="x", expand=True, padx=5)
        label(col, title, size=8, color=MUTED).pack(anchor="w", pady=(0, 6))
        combo = ttk.Combobox(col, textvariable=variable, values=values, state="readonly", width=15)
        combo.pack(fill="x")
        if title == "横轴": app.x_combo = combo
        if title == "纵轴": app.y_combo = combo
    app._button(inner, "生成图表", app.make_chart, True).pack(side="right", padx=(12, 3), pady=(19, 0))
    app._button(inner, "查看统计", app.show_dataset_summary).pack(side="right", padx=(6, 0), pady=(19, 0))
    app.chart_gallery_row = tk.Frame(page, bg=BG)
    label(app.chart_gallery_row, "AI 生成的图表", size=9, color=MUTED).pack(side="left", padx=(0, 12))
    app.gallery_var = tk.StringVar()
    app.gallery_combo = ttk.Combobox(app.chart_gallery_row, textvariable=app.gallery_var, state="readonly", width=14)
    app.gallery_combo.pack(side="left")
    app.gallery_combo.bind("<<ComboboxSelected>>", lambda _event: app.select_agent_chart())
    app.plot_host = tk.Frame(page, bg=PANEL)
    app.plot_host.pack(fill="both", expand=True, padx=35)
    app.plot_label = label(app.plot_host, "⌁\n\n导入一份数据，开始你的第一张图表。", size=12, color=MUTED, bg=PANEL)
    app.plot_label.pack(fill="both", expand=True)
    app.plot_label.bind("<Configure>", lambda _event: app.resize_plot())
    label(page, "内置 Matplotlib 绘图已可用  ·  Origin / Prism / MATLAB 等外部软件尚未接入", size=8, color="#91a0b2").pack(anchor="w", padx=37, pady=(10, 0))


def configure_monitor(app, page):
    heading = tk.Frame(page, bg=BG)
    heading.pack(fill="x", padx=37, pady=(22, 8))
    label(heading, "图片监控", size=18, bold=True).pack(side="left")
    app._button(heading, "选择图片文件夹", app.choose_monitor_folder, True).pack(side="right")
    app.monitor_info = label(page, "监控本地文件夹中的新图片，自动发现，按需预览。", size=10, color=MUTED, anchor="w")
    app.monitor_info.pack(fill="x", padx=37, pady=(0, 13))
    controls = tk.Frame(page, bg=BG)
    controls.pack(fill="x", padx=35, pady=(0, 12))
    app._button(controls, "开始监控", app.start_monitor).pack(side="left")
    app._button(controls, "暂停监控", app.stop_monitor).pack(side="left", padx=8)
    app.monitor_badge = label(controls, "●  未开始", size=9, color=MUTED)
    app.monitor_badge.pack(side="right", padx=7)
    body = tk.Frame(page, bg=BG)
    body.pack(fill="both", expand=True, padx=35)
    files = tk.Frame(body, bg=PANEL, width=230)
    files.pack(side="left", fill="y", padx=(0, 12))
    files.pack_propagate(False)
    app.image_tree = ttk.Treeview(files, columns=("name",), show="headings", selectmode="browse")
    app.image_tree.heading("name", text="本地图片")
    app.image_tree.column("name", width=210)
    scroll = ttk.Scrollbar(files, orient="vertical", command=app.image_tree.yview)
    app.image_tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    app.image_tree.pack(fill="both", expand=True)
    app.image_tree.bind("<<TreeviewSelect>>", app.select_monitored_image)
    app.image_preview_host = tk.Frame(body, bg=PANEL)
    app.image_preview_host.pack(side="left", fill="both", expand=True)
    app.image_label = label(app.image_preview_host, "▧\n\n图片会显示在这里\n\nPNG · JPG · TIFF · BMP", size=11, color=MUTED, bg=PANEL)
    app.image_label.pack(fill="both", expand=True, padx=10, pady=10)
    app.image_label.bind("<Configure>", lambda _event: app.resize_image())
    app.image_details = label(page, "只读监控  ·  每 2 秒检查一次  ·  图片稳定后提示  ·  不自动上传", size=8, color="#91a0b2", anchor="w", wraplength=1000)
    app.image_details.pack(fill="x", padx=37, pady=13)
