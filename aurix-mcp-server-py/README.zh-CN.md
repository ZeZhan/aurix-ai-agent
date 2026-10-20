# AURIX MCP Server

<p align="right"><a href="./README.md">English</a> | <b>简体中文</b></p>

为 AURIX AI 扩展提供项目创建、构建、烧录、示例导入和文档检索能力，
可在 Copilot Chat 中直接使用。

## 功能

| 工具 | 用途 |
|------|------|
| `ads.create_project` | 创建 AURIX 项目 |
| `build.run` | 构建项目 |
| `flash.program` | 烧录固件 |
| `illd.provision` | 添加所需的 iLLD 源码 |
| `project.scan` | 查看项目结构、iLLD 版本和可用的板级引脚标签 |
| `examples.search` | 查找 AURIX 示例 |
| `examples.import` | 将示例导入工作区 |
| `examples.read_source` | 查看示例源码 |
| `documentation.search` | 检索 AURIX 文档并提供来源引用 |

## 使用

1. 安装 [AURIX AI 扩展](../aurix-ai-agent-extension/README.zh-CN.md)。
2. 打开项目，在 Configurator 中选择板卡并设置 AURIX IDE 路径。
3. 在 Copilot Chat 的 Agent 模式中启用 AURIX MCP 工具，然后直接描述需求。

例如：

- “查找适用于 TC375 Lite 的 LED 闪烁示例。”
- “构建当前项目。”
- “查看当前项目使用的 iLLD 版本。”

扩展会自动启动服务器，无需手动安装 Python 或配置运行环境。
查询板级引脚时，请提供具体板卡型号和硬件版本，并核对结果的来源及适用范围。
