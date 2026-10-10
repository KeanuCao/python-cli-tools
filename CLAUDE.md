# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库定位

这是一个 Python CLI 工具源码的合集。用户可以下载源码、自行部署，因此每个工具都必须是能够独立安装、独立运行的完整项目，不依赖仓库里的其他目录。

## 结构约定

- 每个工具一个目录，**目录名即工具名**（同时作为包名和命令行命令名）
- 工具目录下有自己的 `CLAUDE.md`，写该工具的约束、功能等，**优先级高于本文件**；改动某个工具前先读它
- 工具的 `CLAUDE.md` 是规格，可能先于代码存在——`portrait-cutout/` 目前只有规格，尚无 `core.py` / `cli.py` / `pyproject.toml`
- 各工具相互独立，不要为了"统一风格"去改动未被要求改动的工具

## CLI 契约（所有工具必须遵守）

| 参数 | 输出内容 |
|---|---|
| `--description` | 一段人能看懂的**简要说明**：这是什么工具。是"说明"，不是用法 |
| `-h` / `--help` | 这个工具**如何使用** |

`<工具名> --description` 和 `<工具名> -h` 都要能在不提供任何其他必需参数的情况下直接执行成功。

## 工具项目骨架

现有工具（见 `portrait-cutout/CLAUDE.md`）确立的约定：

```
<工具名>/
├── pyproject.toml   # setuptools 后端；[project.scripts] 中 <工具名> = "cli:main"
├── cli.py           # argparse 参数定义 + main()，只负责解析参数与输出
├── core.py          # 核心逻辑，不依赖 CLI
└── CLAUDE.md        # 工具级规格与约束
```

- 源码平铺在工具根目录，不使用 `src/` 布局，用 `[tool.setuptools] py-modules = ["core", "cli"]`
- **核心逻辑与 CLI 分离**：新功能先在 `core.py` 实现，再通过 `cli.py` 暴露
- CLI 参数用 kebab-case（如 `--open-ksize`）

## 环境与部署

根目录本身不是 Python 包，没有统一的构建 / 测试 / lint 入口，所有命令都在**具体工具目录内**执行：

```bash
cd <工具名>
python -m venv .venv                # 隔离开发环境
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e .                    # 开发调试
pipx install .                      # 部署（推荐）
```

各工具都没有测试目录，也没有配置 linter / formatter；改动后请手动运行命令验证效果。

## 已知问题

- 根目录 `README.md` 是 UTF-16LE 编码的空壳（内容仅一行 `# python-cli-tool`），按 UTF-8 读取会得到乱码，git 也将其视为二进制文件
