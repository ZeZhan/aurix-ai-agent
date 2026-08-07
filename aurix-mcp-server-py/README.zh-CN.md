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
python tests/smoke_stdio.py
```

## 目录结构

```
src/aurix_mcp_server/
  __init__.py          constants (name, version, protocol)
  __main__.py          CLI entry (stdio | doctor | version)
  server_fastmcp.py    FastMCP wiring (tool registration + instructions)
  context.py           .aurix-ai/context.json loader
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
tests/
  smoke_stdio.py       end-to-end stdio client test
```
