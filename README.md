# BME Agent

**面向生物传感与疾病检测实验的本地科研工作台。**

Local-first biomedical research assistant for biosensing experiments, literature review, data analysis, and scientific plotting.

当前版本：**0.5.1**。采用 Electron 界面和 Python 本地分析服务。AI 理解研究问题并提出受限建议，数据筛选、计算与绘图由本地固定函数执行。

## 功能

| 模块 | 当前实现 |
| --- | --- |
| 研究对话 | 论文总结、实验步骤梳理、实验问题排查、日常问答和有限历史上下文 |
| 单文件附件 | PDF、TXT、Markdown、CSV、TSV、XLSX 和图片；支持拖放、本地预览及 PDF 物理页引用 |
| 本地资料 | 中文双字词 / 英文词法检索、证据片段选择与来源核对 |
| 实验分析 | 数据预览、列映射、范围筛选、手动排除原因、分组均值、SD / SEM |
| 科研绘图 | 多组时间曲线与误差带、重复散点与均值误差线，以及基础折线、散点、直方、箱线图 |
| Spark 仪器表 | 单测量段动力学 XLSX 宽表转长表，保留实际时间、孔号、周期和原始单元格 |
| 跳点检查 | 按单孔曲线标记探索性孤立候选，应用筛选前预览，保存排除前后对比 |
| 图片监控 | 每 2 秒检查选定目录，文件稳定后本地预览，不自动上传 |
| 结果导出 | PNG、SVG、统计 CSV，以及带参数、来源哈希和逐条筛选记录的 ZIP |
| 连接与用量 | 加载账户实际模型列表、测试连接、Token 统计、手动余额记录 |

公开示例均为**合成数据**，不是真实论文、人体数据或实验依据。真实实验文件、分析副本与输出不包含在仓库中。

## 安装与启动

### 环境

- Windows x64。
- Python 3.11+；当前验证使用 Python 3.12。
- 推荐 `uv`。没有 `uv` 时，安装脚本使用 Python 自带的 `venv` 和 `pip`。
- 云端 AI 功能需要 OpenAI 官方 API Key；离线数据分析、绘图、预览和图片监控不需要 Key。

### 从源码构建

```powershell
git clone https://github.com/lengyuely2/bme-research-agent.git
cd bme-research-agent
.\setup.ps1
.\build.ps1
.\start.ps1
```

`build.ps1` 下载固定版本的 Electron，校验官方发布的 SHA-256，再用 PyInstaller 打包 Python 服务并组装桌面程序。首次构建需要网络。

构建产物位于 `dist/v0.5.1/BMEWorkbench/`。双击其中的 `BMEWorkbench.exe`，或使用项目根目录的 `start.bat`。分发时保留整个程序目录，不能只复制 EXE。仓库不包含预编译程序、虚拟环境或运行库。

若执行策略阻止 PowerShell 脚本，请按所在设备的管理策略处理；项目不会自动修改系统安全设置。

### 开发启动

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe tools\fetch_runtime.py
.\.runtime\electron\electron.exe desktop
```

`pyproject.toml` 声明依赖范围。`requirements.lock` 记录开发环境的精确版本快照；复现时可在虚拟环境中运行 `python -m pip install -r requirements.lock`，随后执行 `python -m pip install --no-deps -e .`。

## 使用

### 论文与实验问答

1. 在“设置”中输入 Key，加载可用模型，从账户实际返回的列表选择模型。
2. 可发送测试请求验证连接，测试会产生少量 API 用量。
3. 拖入论文或资料，点击附件名称本地预览。
4. 输入问题，或选择“精读论文”“梳理实验步骤”“排查实验问题”。
5. 点击发送或按 Enter 直接提交，Shift + Enter 换行。“查看发送内容”可按需使用，不会每次弹出确认。

同一任务的附件用于后续追问，新任务不继承其他任务的附件。Key、聊天、索引、余额记录和未导出结果仅在本次启动保留。

### 实验分析流程

1. 导入 CSV / TSV / XLSX，或先体验合成演示。推荐长表：每行一条测量，每列一个变量。
2. 核对横轴、信号、分组和重复编号。可使用本地初始方案，也可点击“AI 建议方案”。
3. 填写可选范围或排除记录号及原因，点击“预览筛选与统计”。
4. 检查保留数、排除原因、样本数与误差，再点击“确认筛选并生成图”。
5. 导出完整结果 ZIP。改变条件后重新预览与生成，避免旧图和新参数混用。

同组、同时间点和同重复编号的技术测量先平均，再汇总重复。没有指定独立实验重复时，`n` 只表示记录数，不代表已确认生物学独立性；`n < 2` 时不估计 SD / SEM。

### Spark 与跳点检查

Spark 导入需要软件标记和单个 `Cycle Nr.` / `Time [s]` 动力学段。程序使用实际时间，校验周期数和时间轴，不从信号反推浓度。按物理列分组、按孔号区分曲线仅是待核对的候选布局。

“检查孤立跳点”使用左右邻点线性参考残差和 scaled MAD 标记候选，同时要求反向变化与邻点恢复。默认阈值 3.5，可调范围 3–10。首尾点、短序列、重复时间及 MAD 为零的曲线不作该检查。

这是探索性规则，不能证明仪器错误，不能检测所有连续异常。程序不为得到单调趋势或显著结果自动删点。候选先应用到条件，再预览和出图；原始测量不写回、不补值、不平滑。有手动排除时，界面与 ZIP 同时提供同范围的排除前参考图。

## 技术栈

| 层次 | 技术 | 用途 |
| --- | --- | --- |
| 桌面壳 | Electron 45.2.1 | Windows 窗口、原生文件选择、preload 与 IPC 隔离 |
| 界面 | HTML / CSS / 原生 JavaScript | 深色对话、附件、分析流程和预览 |
| 本地服务 | Python、NDJSON over stdio | 固定操作分发、快照与结果管理 |
| AI | OpenAI Python SDK、Responses API | 流式回答、Function Calling、结构化方案建议 |
| 网络 | HTTPX | 固定官方端点、禁用环境代理与自动重试 |
| 数据 | csv、statistics、NumPy、openpyxl | 表格读取、分组汇总、Spark 表转换 |
| 绘图 | Matplotlib Agg / SVG | 本地 PNG 和矢量图 |
| 文档与图片 | pypdf、pypdfium2、Pillow | PDF 提取、物理页预览、图像副本 |
| XML 解析防护 | defusedxml | 配合 Excel XML 解析依赖 |
| 打包与测试 | PyInstaller、pytest、HTTPX MockTransport | Windows 分发、文件保护与离线 API 测试 |

```text
Electron renderer
    → preload 受限接口
    → Electron main 校验
    → NDJSON stdio
    → Python broker
        ├─ 只读文件代理 → 数据快照 → 本地统计 / 绘图 / 导出
        └─ 冻结资料包 → OpenAI → 白名单工具请求 → 校验 → 回答与引用
```

AI 不执行任意生成代码。模型只请求当前资料包允许的固定工具，Python 再校验参数与来源。筛选、统计、跳点检查及科研图使用确定性本地函数。

详细实现、算法与扩展方式见 [技术说明](docs/TECHNOLOGY.md)。

## 文件安全与数据发送

- 模型不具备删除、覆盖、终端、任意脚本或外部软件执行工具。
- 输入通过只读代理校验边界、链接和 Windows 最终文件句柄路径。
- 输出目录与输入目录相互独立，文件以随机名称排他新建，避免覆盖。
- Electron 启用沙盒、上下文隔离与 CSP；渲染端无 Node 和外部网络权限。
- Python 服务通过 stdio 通信，不监听本地 HTTP 端口。
- Key 仅存于内存；错误信息使用白名单字段，不输出 SDK 原始错误正文。

普通启动仍继承当前 Windows 账户权限，应用级限制不等于操作系统隔离。项目提供 Windows Sandbox 配置生成器，但虚拟化环境内的实际启动与只读映射尚未验证。详见 [SECURITY.md](SECURITY.md)。

| 场景 | 发送给模型的内容 |
| --- | --- |
| 自由问答 | 当前问题和有限历史，不附加本地资料 |
| 资料问答 | 当前选定片段、来源标识及统计摘要 |
| PDF 附件 | 完整 PDF，可能包括正文、附录与页面图像 |
| 图片附件 | 经尺寸限制、方向校正和元数据移除的视觉副本 |
| 表格附件 | 当前工作表描述统计，不含原始样本行 |
| AI 分析方案 | 列名、行数、聚合计数 / 数值范围和用户填写的说明 |

添加、预览和监控不自动上传。点击发送会提交当前关联资料。文件名、列名和统计也可能敏感，可先查看发送内容。`store=False` 不等于服务端零留存。

余额功能是**手动记录**，不是实时余额接口；Token 统计仅覆盖本进程取得 API 用量的请求。

## 项目结构

```text
bioagent/              Python 服务、文件代理、Agent 与分析模块
desktop/               Electron 主进程、preload、界面与流程
samples/               已审核的合成示例
tests/                 单元、协议与子进程测试
tools/                 运行库校验、桌面组装及合成 PDF 生成器
docs/TECHNOLOGY.md      技术架构、算法与扩展方式
SECURITY.md            安全设计和已知边界
setup.ps1              环境安装
build.ps1              打包桌面
start.ps1 / start.bat   启动入口
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q --ignore=tests/test_layout.py
.\dist\v0.5.1\BMEWorkbench\BMEWorkbench.exe --self-test
```

当前核心测试 **145 项通过**。`test_layout.py` 属于旧 Tk 界面，不用于当前 Electron 桌面。API 协议测试使用离线 MockTransport，不读取用户 Key、不上传实验文件、不验证实际账户权限。

安装包自检覆盖原生附件桥接、PDF 页面、本地绘图、预览失效、前后对比导出、直接发送交互与界面隔离。仓库包含 Windows CI；生成的测试报告不提交到 Git。

## 当前限制

- 科研辅助原型，未完成临床验证，不用于自动患者诊断或处方。
- 尚未接入 Origin、GraphPad Prism、MATLAB、ImageJ/Fiji 的外部控制，不生成 Prism 原生工程。
- 标准曲线拟合、LOD / LOQ、显著性检验、专门 FTIR 处理和多面板排版尚未实现。
- 会话与项目没有持久化，关闭前请导出需要保留的结果。
- 引用检查只能验证来源与页码范围，不证明模型结论符合原文。
- Excel 不执行公式、宏或外部链接，无缓存值的公式按缺失处理。
- 图像视觉副本不能替代原始像素定量。
- 本仓库发布源码与合成示例，不包含真实实验数据或预编译安装包。

当前未指定开源许可证。
