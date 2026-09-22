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

`ads.create_project` 和 `project.scan` 会在现有结果中附带简短的 iLLD
版本提示及 `illdVersion` 对象（`status`、`version`、`sources`）。依据为
项目内 `IfxLldVersion.h` 的相对路径，解析 `IFX_LLD_VERSION_MAJOR`、
`MINOR` 及 `REVISION`（TC2xx/TC3xx）或 `PATCH`（TC4xx）宏。
创建项目时读取最终部署的库，包括被保留的工作区依赖；未指定工作区时读取
实际缓存中的库，不根据当前 IDE 或 initializer 的版本推断。

声明缺失、不可读或格式不受支持时报告 `unknown`，不同声明版本并存时报告
`conflict`。扫描遵守 `excludeDirs` 和 `maxFiles`，达到文件上限时不作确定的
单一版本结论。这是本地版本声明提示，不验证编译器的实际包含路径、文件完整性
或是否为最新版本，不增加工具调用、网络请求，也不执行版本升级。

## 文档索引

文档抽取和建索引（包括所有 Docling 处理）只在线下执行，不属于 MCP
服务器运行流程。服务器查询时只打开生成后的 SQLite 索引。VSIX 内置独立的
TC2xx、TC3xx 和 TC4Dx 索引，并根据查询、`device`/`family` 或 Configurator
所选板卡自动路由。PDF 不会进入 VSIX；独立 Python wheel 也不包含索引。

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
