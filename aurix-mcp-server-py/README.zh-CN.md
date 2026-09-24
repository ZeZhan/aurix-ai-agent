# AURIX MCP Server (Python)

<p align="right"><a href="./README.md">English</a> | <b>简体中文</b></p>

AURIX MCP 服务器，基于官方
[`mcp`](https://pypi.org/project/mcp/) Python SDK 构建。工具通过
`FastMCP` 注册，并经 SDK 的 stdio 传输通道对外提供服务。

## 工具

| 工具 | 用途 |
|------|------|
| `ads.create_project` | 生成一个新的 AURIX ADS 项目脚手架 |
| `build.run` | 构建项目（将 tricore-gcc + make 前置到 PATH） |
| `flash.program` | 通过 aurixflasher 烧录 `.elf`/镜像 |
| `illd.provision` | 为某个设备变体供给 iLLD 源码 |
| `project.scan` | 扫描并报告项目结构 |
| `examples.search` | 搜索内置示例索引 |
| `examples.import` | 将某个示例导入工作区 |
| `examples.read_source` | 读取指定示例的源码 |
| `documentation.search` | 按设备路由离线 AURIX 文档，并返回 PDF 物理页码引用 |

## iLLD 版本提示

`ads.create_project` 和 `project.scan` 会提示本地库头文件中声明的 iLLD 版本。
无法识别或存在冲突时分别标记为 `unknown` 或 `conflict`，不检查更新或执行升级。

## 板级引脚标签

`ads.create_project` 和 `project.scan` 支持可选 `board`，例如
`KIT_A2G_TC375_LITE`。省略时可使用 `device` 中的板卡 ID、工作区上下文或
Configurator 所选板卡；仅有芯片型号不会默认选板。优先读取项目根目录的
`board_pin_label.bpl`，缺失时查找所选本地 ADS/ACS 安装中的对应 BSP。

创建项目时复制可用 BPL，保留已有文件，不向共享芯片缓存写入板卡文件；扫描只读。
结果中的 `boardPins` 包含带注释的引脚、别名、来源路径/哈希和原始行证据。
BPL 缺失或格式异常不阻断普通创建/扫描；可识别的板卡冲突不返回可用映射，
项目板卡身份无法核实时会明确提示。BPL 不证明有效电平或电气限制，未注明的
硬件版本保持未知。扩展不打包厂商 BPL 文件。

## 已核对的板级电气事实

`documentation.search` 内置小型离线板级事实索引。引用包含官方手册修订、章节/表号、
PDF 物理页、来源 URL 和 PDF 哈希；不推断电压、电流或上拉配置。

| 板卡 / 硬件版本 | 已核对信号 | 出处 |
| --- | --- | --- |
| TC375 Lite V2 | LED1 P00.5、LED2 P00.6、BUTTON1 P00.7，均低有效 | 手册 2.2，第 10/11 页 |
| TC4D7 Lite V2.x | LED1 P03.9、LED2 P03.10、BUTTON1 P03.11，均低有效 | 002-41555 Rev. *A，第 9 页 |
| TC397 5V TFT V2.0 | D107-D110 对应 P13.0-P13.3，低有效；S101 复位、S102 PMIC 唤醒并非 GPIO 按钮 | 手册 V2.0，第 14/25 页 |

```json
{"query":"LED和按钮的引脚与有效电平","board":"KIT_A2G_TC375_LITE","hardwareVersion":"V2"}
```

TC4D7 使用 `KIT_A3G_TC4D7_LITE` 和 `V2.0`（来源明确覆盖 `2.x`）。TC397 使用
`KIT_A2G_TC397_5V_TFT` 和精确的 `V2.0`，查询全部六条事实时设置 `topK: 10`。
不能套用到 TriBoard 或 3.3 V 版本。TC397 按钮的 `level_at` 区分电平作用点，
并用 `usageRestriction: not_a_gpio` 阻止当作普通 GPIO 按钮使用。

可选 `projectPath` 用于对照项目 BPL（缺失时查找匹配的本地 BSP）。不覆盖任何来源；
引脚冲突时抑制可用事实。未明确硬件版本时返回 `hardware_version_required`，
不能把手册修订 2.2 当作硬件 V2。使用前检查 `requiresConfirmation`、`applicability`
和 `usableForCodeGeneration`。未传项目路径时仅为手册证据，不表示已核验连接的实物。
BPL 缺失标签时返回 `not_mapped`，不伪造匹配，也不误报引脚冲突；核验的 TC397
安装 BPL 没有 LED/按钮标签。支持中英文查询及板卡实际信号名称；仅有芯片型号
不会默认选板。其他板卡、硬件版本和未核对的电气限制不会套用这些证据。

板级小索引位于 Python 包内，不依赖芯片索引或联网。显式 `indexPath` 会覆盖它，
且须包含板卡元数据。[证据与重建说明](src/aurix_mcp_server/data/board_manuals/README.md)。

## 文档索引

文档抽取和建索引（包括所有 Docling 处理）只在线下执行，不属于 MCP
服务器运行流程。服务器查询时只打开生成后的 SQLite 索引。VSIX 内置独立的
TC2xx、TC3xx 和 TC4Dx 索引，并根据查询、`device`/`family` 或 Configurator
所选板卡自动路由。PDF 不会进入 VSIX；独立 Python wheel 不包含这些芯片索引。

独立运行服务器时可以配置索引目录，也可以用 `indexPath` 覆盖：

```pwsh
$env:AURIX_DOCUMENTATION_INDEX_DIR = "C:\path\to\documentation-indexes"
# 兼容旧版的单索引覆盖：
$env:AURIX_DOCUMENTATION_INDEX = "C:\path\to\aurix-documentation.sqlite"
```

## 运行

### 使用 uv（推荐 —— 无需手动配置 Python）

[uv](https://docs.astral.sh/uv/) 会自动准备 Python 解释器和服务器依赖：

```pwsh
# 在本目录下
uv run --with mcp --with httpx --python 3.12 python -m aurix_mcp_server
```

VS Code 扩展默认就是以这种方式启动内置服务器的。

### 使用已有的 Python

```pwsh
# 在本目录下，激活工作区的 .venv
$env:PYTHONPATH = "src"
python -m aurix_mcp_server            # 启动 stdio MCP 服务器
python -m aurix_mcp_server --doctor   # 输出健康报告 JSON
python -m aurix_mcp_server --version
```

或以可编辑方式安装：

```pwsh
pip install -e .
aurix-mcp-server --doctor
```

## 测试

```pwsh
python -m unittest discover -s tests -p "test_*.py"
python tests/smoke_stdio.py
```

## 目录结构

```
src/aurix_mcp_server/
  __init__.py          constants (name, version, protocol)
  __main__.py          CLI entry (stdio | doctor | version)
  server_fastmcp.py    FastMCP wiring (tool registration + instructions)
  context.py           .aurix-ai/context.json loader
  documentation_retrieval.py  SQLite FTS 检索与物理页码引用
  utils.py             helpers (LimitedBuffer, path/address parsing)
  tooldef.py           ToolResult / ToolContext primitives
  tools/
    __init__.py        tool package doc (registration lives in server_fastmcp)
    ads_create_project.py
    build_run.py
    flash_program.py
    illd_provision.py
    scan_project.py
    examples.py        examples.search / import / read_source
    documentation_search.py  documentation.search MCP 业务逻辑
tests/
  smoke_stdio.py       end-to-end stdio client test
```
