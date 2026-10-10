# CLAUDE.md

本文件为 Claude Code / AI 助手提供 `portrait-cutout` 项目的开发上下文。

## 项目概述

`portrait-cutout` 是一个 Python 命令行工具，用于对人像图片进行智能抠图，并去除边缘多余发丝。  
核心流程：AI 分割 → 获取 alpha 通道 → OpenCV 形态学后处理 → 输出透明 PNG。

## 技术栈

- Python 3.9+
- rembg（ONNX Runtime 后端）
- OpenCV (`opencv-python`)
- Pillow
- NumPy
- argparse（命令行解析）
- setuptools + pyproject.toml（打包）

## 项目结构

```
portrait-cutout/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── core.py          # 核心抠图与 alpha 后处理
└── cli.py           # 命令行入口
```

源代码直接放在项目根目录，没有 `src/` 嵌套，也没有 `tests/` 目录。

## 开发环境设置

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

## 常用命令

```bash
# 运行 CLI
portrait-cutout input.jpg -o output.png --threshold 180 --open-ksize 5

# 查看帮助
portrait-cutout -h

# 打包为独立可执行文件
pyinstaller --onefile --collect-all rembg --collect-all onnxruntime cli.py
```

## 核心模块说明

### `core.py`

- `portrait_cutout(input_path, output_path, model_name, threshold, open_ksize, erode_iter, blur_sigma)`
  - 使用 `rembg.remove()` 获取 RGBA 图像，`alpha_matting=False`
  - 提取 alpha 通道，调用 `clean_alpha()` 清理发丝
  - 合成原图 RGB + 清理后的 alpha，保存 PNG
- `clean_alpha(alpha, threshold, open_ksize, erode_iter, blur_sigma)`
  - 二值化 → 开运算 → 可选腐蚀 → 高斯羽化

### `cli.py`

- 使用 `argparse` 定义参数
- 入口点：`main()`
- `pyproject.toml` 中配置 `[project.scripts] portrait-cutout = "cli:main"`

## 后处理参数调优

| 参数 | 作用 | 默认 | 调整建议 |
|---|---|---|---|
| `threshold` | alpha 二值化阈值 | 160 | 发丝多 → 180~200；主体被吃 → 降低 |
| `open_ksize` | 开运算核大小 | 3 | 发丝顽固 → 5 或 7 |
| `erode_iter` | 额外腐蚀次数 | 0 | 仍有余发 → 1~2 |
| `blur_sigma` | 边缘羽化 sigma | 1.0 | 边缘生硬 → 1.5~2.0 |

## 模型与运行环境

- 默认模型：`u2net_human_seg`
- 模型缓存：`~/.u2net`（首次运行自动下载）
- CPU 推理：`onnxruntime`
- GPU 推理：`onnxruntime-gpu`（不要与 CPU 版同时安装）
- 若需更高精度，可换 `isnet-general-use` 或 `birefnet-portrait`，但速度更慢

## 打包与分发

- 开发调试：`pip install -e .`
- 全局安装（推荐 pipx）：`pipx install .`
- 独立可执行：PyInstaller 命令见上

## pyproject.toml 关键配置

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "portrait-cutout"
version = "0.1.0"
dependencies = [
    "rembg[cli]",
    "opencv-python",
    "pillow",
    "numpy",
    "onnxruntime",
]

[project.scripts]
portrait-cutout = "cli:main"

[tool.setuptools]
py-modules = ["core", "cli"]
```

## 编码规范

- 使用类型注解
- 函数保持单一职责
- 命令行参数用 kebab-case（如 `--open-ksize`）
- 核心逻辑与 CLI 分离，便于复用

## 给 Claude 的提示

- 修改 `core.py` 时，保持 alpha 清理参数可配置，不要硬编码。
- 添加新功能时，优先在 `core.py` 中实现，再通过 `cli.py` 暴露。
- 若引入新模型，在 `core.py` 中抽象模型选择逻辑，避免 CLI 直接依赖 rembg 细节。
- 项目没有测试目录，修改后请手动运行命令验证效果。