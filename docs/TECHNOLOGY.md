# 技术说明 / Technical Documentation

[中文](#chinese) | [English](#english)

<a id="chinese"></a>

## 中文

本文描述 0.5.1 的实际实现。主入口是 Electron 桌面；旧 Tk 界面代码仅为兼容和历史保留。

### 进程与通信

Electron 主进程创建窗口、打开系统文件选择器、启动 Python 服务，并校验 IPC 的发送者与操作名。preload 用 `contextBridge` 暴露窄接口，渲染端不能直接调用文件系统或执行进程。

Python 使用 stdin / stdout 上的逐行 JSON（NDJSON）处理请求，通过 ID 对应返回结果。监控与流式文本通过事件返回。服务不启动本地 HTTP 监听端口。固定操作受白名单和串行操作锁约束。

对应代码：[main.cjs](../desktop/main.cjs)、[preload.cjs](../desktop/preload.cjs)、[desktop_service.py](../bioagent/desktop_service.py)。

### AI 的职责与权限

研究问答使用 OpenAI Responses API 的文本流和函数调用。模型只能请求当前冻结资料包开放的工具：

| 工具 | 范围 |
| --- | --- |
| `list_evidence` | 列出当前资料包的证据 |
| `read_evidence` | 读取批准的片段 |
| `search_evidence` | 在当前片段中词法检索 |
| `table_summary` | 读取本地已计算的摘要 |
| `plot_data` | 关联数据快照后，用受限图形和列生成基础图 |

工具不接受磁盘路径或任意代码。调用轮数、工具次数和图表数量均有上限。AI 分析方案另外使用严格 JSON Schema 返回列角色与图形建议，本地再次校验列名、互斥角色和枚举，不能直接更改数据。

API 固定为官方端点，Key 只保留在内存中。账户模型列表从实际连接加载，不预设模型权限。错误处理区分认证、模型、余额、用量和短期限速，只展示白名单字段。

对应代码：[agent.py](../bioagent/agent.py)、[connection.py](../bioagent/connection.py)、[billing.py](../bioagent/billing.py)。

### 文件读取与来源追踪

`safety.py` 检查根目录、路径边界、重解析点和硬链接。Windows 使用只读句柄，验证最终路径与链接数。资料读取为内存快照，不写回原始内容。

普通检索使用来源与片段编号，PDF 附件支持物理页编号。引用定位到回答绑定的快照；只能说明来源属于资料包，不能证明模型解释正确。

导出记录包含来源名称、SHA-256、工作表、参数、逐条筛选原因和统计。输出目录不能与输入目录相互包含，文件采用排他新建。

对应代码：[safety.py](../bioagent/safety.py)、[library.py](../bioagent/library.py)、[attachments.py](../bioagent/attachments.py)。

### 表格与仪器格式

CSV / TSV 使用标准库读取。XLSX 使用 openpyxl 的只读、缓存值模式，并禁用外部链接。不计算公式。压缩体积、条目数、行列数和最终记录数均有上限。

Spark 适配需要明确软件标记与单个动力学表头，提取实际 `Time [s]` 并换算为分钟，保留信号、物理列、孔号、周期和源单元格。它校验周期数与时间轴，不使用设定间隔替代实际采样，也不自动推断浓度或实验独立性。

对应代码：[tables.py](../bioagent/tables.py)、[plate.py](../bioagent/plate.py)、[analysis.py](../bioagent/analysis.py)。

### 筛选与统计

参数校验后生成不可变预览。出图必须使用该预览令牌。导入新数据、修改表单或重新预览会使旧的前端生成授权失效。

缺失或无效的所选字段不能参与该图。数值范围与手动排除分别记录原因；手动排除必须说明。重复记录和 IQR 候选只标记，不自动剔除。

指定重复时，同组、同时间点、同重复编号的技术测量先平均，再计算重复之间的均值与样本标准差：

```text
sample SD = sqrt(sum((value - mean)^2) / (n - 1))
SEM = sample SD / sqrt(n)
```

`n < 2` 时误差缺失，不画成零误差。未指定重复编号时，`n` 仅表示记录数。生物学独立性需要由实验设计确认。

### 孤立跳点候选

每条组别 / 孔号曲线按实际时间排序，用左右相邻点计算线性参考值，得到当前点残差。以残差中位数为中心计算：

```text
MAD = median(abs(residual - median(residual)))
scaled MAD = 1.4826 * MAD
```

候选同时满足残差超阈值、左右差分异号和两侧邻点恢复条件，跨大时间缺口不检查。默认阈值是探索性工程选择，不是经本项目实验验证的检测性能保证。

该方法跳过首尾点、短序列、重复时间和 MAD 为零的曲线，可能漏掉连续异常或真实快速事件。它不要求时间或浓度单调上升，不补值、不平滑。候选只有在用户应用并预览后才影响图表。

有手动排除时，同范围的排除前与排除后图一起保存。范围外数据的“不绘制”与异常剔除应分别解释。

对应代码：[workflow.py](../bioagent/workflow.py)、[workflow.js](../desktop/workflow.js)。

### 绘图与结果包

Matplotlib 使用 Agg 生成 PNG，用 SVG 后端输出矢量图。字体设置含 Windows 中文回退，文本不按 LaTeX 执行。

结果 ZIP 包含 `figure.png` / `figure.svg`、冻结参数与决策 `analysis.json`、逐条记录 `row_decisions.csv`、筛选后测量 `processed_points.csv`、图上统计 `summary.csv`。有手动排除时增加 `before_exclusion.*` 和 `before_summary.csv`。

CSV 为可能解释成公式的字符串增加单引号，JSON 保留原文。SVG 文本仍依赖接收设备字体。当前没有显著性检验、自动平滑或曲线拟合。

### 图片监控

只监控用户选定目录的第一层。现有文件作为基线，新建或修改文件在连续两次轮询的大小与修改时间一致后提示。只读预览首帧，有大小与像素上限，不自动上传。稳定检测不能保证设备已完成全部写入。

对应代码：[monitor.py](../bioagent/monitor.py)。

### 构建与验证

`tools/fetch_runtime.py` 下载并校验固定 Electron 版本；PyInstaller 打包 Python 服务、解析器与合成样例；`tools/package_desktop.py` 组装独立桌面目录。构建产物不提交到源码仓库。

pytest 覆盖文件保护、解析限额、统计、预览失效、快照、导出一致性、孤立候选、模拟 API 和真实 stdio 子进程。Electron `--self-test` 用合成文件及离线响应检查界面桥接，不使用真实账户 Key。

### 扩展约定

新分析方法先实现确定性函数与校验，再加入服务白名单和界面预览。模型工具只引用批准的内存对象，不接收路径、脚本或任意 URL。仪器适配保留源坐标与时间单位，拒绝模糊或不完整格式，不静默截断。

外部软件控制、会话持久化与更多统计方法尚未接入，不应通过无限制终端工具绕过现有权限设计。

---

<a id="english"></a>

## English

This document describes the implementation in version 0.5.1. The primary entry point is the Electron desktop application. Legacy Tk interface code is retained for compatibility and historical reference.

### Processes and communication

The Electron main process creates windows, opens native file pickers, starts the Python service, and validates IPC senders and operation names. The preload script exposes a narrow `contextBridge` interface. The renderer cannot directly access the filesystem or execute processes.

Python handles newline-delimited JSON (NDJSON) requests through stdin and stdout, matching results to request IDs. Monitoring and streaming text are returned as events. The service does not open a local HTTP listening port. Fixed operations are controlled by an allowlist and a serial operation lock.

Code: [main.cjs](../desktop/main.cjs), [preload.cjs](../desktop/preload.cjs), [desktop_service.py](../bioagent/desktop_service.py).

### AI responsibilities and permissions

Research conversations use text streaming and function calling through the OpenAI Responses API. The model can request only tools exposed by the current frozen evidence packet:

| Tool | Scope |
| --- | --- |
| `list_evidence` | List evidence in the current packet |
| `read_evidence` | Read an approved excerpt |
| `search_evidence` | Perform lexical search within the current excerpts |
| `table_summary` | Read a summary already computed locally |
| `plot_data` | Generate a basic plot from an associated snapshot using approved chart types and columns |

Tools do not accept disk paths or arbitrary code. Request rounds, tool calls, and plot counts are bounded. AI analysis plans use a separate strict JSON Schema for column roles and chart suggestions. The local service validates column names, mutually exclusive roles, and allowed values again; the model cannot directly modify data.

Requests use a fixed official endpoint, and keys remain in memory. The available model list is loaded from the actual connection rather than assuming account permissions. Error handling distinguishes authentication, models, balances, usage limits, and temporary rate limits, exposing only allowlisted fields.

Code: [agent.py](../bioagent/agent.py), [connection.py](../bioagent/connection.py), [billing.py](../bioagent/billing.py).

### File access and source tracking

`safety.py` checks roots, path boundaries, reparse points, and hard links. On Windows, it opens read-only handles and validates the final path and link count. Source contents are held as in-memory snapshots and are not written back.

Local retrieval uses source and excerpt identifiers. PDF attachments additionally support physical-page identifiers. Citations open the snapshot associated with the answer. Identifier validation establishes that a source belongs to the packet, not that the model's interpretation is correct.

Exports record source names, SHA-256 hashes, worksheets, parameters, record-level filtering reasons, and statistics. Input and output directories cannot contain one another. Files are created exclusively to prevent overwriting existing files.

Code: [safety.py](../bioagent/safety.py), [library.py](../bioagent/library.py), [attachments.py](../bioagent/attachments.py).

### Tables and instrument formats

CSV and TSV use Python's standard library. XLSX uses openpyxl in read-only, cached-value mode, with external links disabled. Formulas are not evaluated. Limits apply to compressed-file expansion, entry counts, worksheet dimensions, and final record counts.

The Spark adapter requires an explicit software marker and a single kinetic header. It reads actual `Time [s]` values and converts them to minutes, retaining signal values, physical columns, wells, cycles, and source cells. It validates cycle counts and the time axis, does not substitute the configured interval for actual sampling, and does not infer concentrations or experimental independence.

Code: [tables.py](../bioagent/tables.py), [plate.py](../bioagent/plate.py), [analysis.py](../bioagent/analysis.py).

### Filtering and statistics

Validated parameters produce an immutable preview. Plot generation requires that preview's token. Importing new data, changing form values, or creating a new preview invalidates the previous frontend generation authorization.

Records with missing or invalid selected fields cannot participate in that plot. Range filters and manual exclusions retain separate reasons; manual exclusions require an explanation. Duplicate records and IQR candidates are flagged without automatic removal.

When replicate identifiers are supplied, technical measurements sharing a group, time point, and replicate identifier are averaged first. The application then calculates the mean and sample standard deviation across replicate-level values:

```text
sample SD = sqrt(sum((value - mean)^2) / (n - 1))
SEM = sample SD / sqrt(n)
```

Uncertainty is unavailable when `n < 2`, rather than displayed as zero. Without a replicate identifier, `n` denotes record count only. Biological independence must be established from the experimental design.

### Isolated-point candidates

Each group / well trace is sorted by actual time. A linear reference between adjacent points defines the residual at the current point. The residual median is used as the center:

```text
MAD = median(abs(residual - median(residual)))
scaled MAD = 1.4826 * MAD
```

A candidate must meet the residual threshold, reverse direction on either side, and satisfy the neighbor-recovery condition. Checks do not cross large time gaps. The default threshold is an exploratory engineering choice, not a detector-performance guarantee validated by experiments in this project.

The method skips endpoints, short sequences, duplicate timestamps, and traces with zero MAD. It can miss sustained anomalies or flag genuine rapid events. It does not require a monotonic time course or concentration response, and it does not impute or smooth values. Candidates affect a plot only after they are applied and the filtering preview is reviewed.

With manual exclusions, plots before and after exclusion are saved over the same range. Hiding records outside a selected display range must be distinguished from excluding anomalous measurements.

Code: [workflow.py](../bioagent/workflow.py), [workflow.js](../desktop/workflow.js).

### Plotting and result archives

Matplotlib's Agg backend generates PNG files, and its SVG backend generates vector graphics. Font settings include a Windows Chinese fallback; text is not executed as LaTeX.

The result ZIP contains `figure.png` / `figure.svg`, frozen parameters and decisions in `analysis.json`, record-level decisions in `row_decisions.csv`, retained measurements in `processed_points.csv`, and plotted statistics in `summary.csv`. Manual exclusions add `before_exclusion.*` and `before_summary.csv`.

CSV exports prefix potentially formula-like strings with an apostrophe; JSON preserves their original text. SVG text still requires suitable fonts on the receiving device. Significance tests, automatic smoothing, and curve fitting are not implemented.

### Image monitoring

Only the first level of the selected directory is monitored. Existing files form the baseline. New or modified files are reported after size and modification time remain unchanged across two polls. Previews are read-only and use the first frame, with file-size and pixel limits. Images are not automatically uploaded. A stable file does not guarantee that a device has completed every write.

Code: [monitor.py](../bioagent/monitor.py).

### Packaging and verification

`tools/fetch_runtime.py` downloads and verifies a pinned Electron runtime. PyInstaller packages the Python service, parsers, and synthetic samples. `tools/package_desktop.py` assembles the standalone application directory. Build artifacts are excluded from the source repository.

pytest covers file protection, parsing limits, statistics, invalidated previews, snapshots, export consistency, isolated candidates, mocked API requests, and real stdio subprocesses. Electron's `--self-test` uses synthetic files and offline responses to check interface bridging without real account keys.

### Extension guidelines

Implement a new analysis method as a deterministic function with input validation before adding it to the service allowlist and preview workflow. Model tools should reference only approved in-memory objects, not paths, scripts, or arbitrary URLs. Instrument adapters should preserve source coordinates and time units, reject ambiguous or incomplete formats, and avoid silent truncation.

External application control, session persistence, and additional statistical methods are not implemented. An unrestricted terminal tool should not be used to bypass the existing permission design.
