# CLAUDE.md

本文件为 Claude Code / AI 助手提供 `portrait-cutout` 项目的开发上下文。

## 项目概述

`portrait-cutout` 是一个 Python 命令行工具，用于对人像图片进行智能抠图，并去除边缘多余发丝，
然后铺上证件照标准背景色输出（默认标准蓝，`--transparent` 则保留透明背景）。  
核心流程：AI 分割 → 获取 alpha 通道 → OpenCV 形态学后处理 → 铺背景色或保留透明 → 输出。

默认输出**不是**透明图：带背景色是常态，透明要靠 `--transparent` 显式要求。

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
# 运行 CLI（默认铺标准蓝底）
portrait-cutout input.jpg -o output.png

# 换背景色 / 透明背景
portrait-cutout input.jpg --bg white
portrait-cutout input.jpg --bg 深蓝色
portrait-cutout input.jpg --bg "#438EDB"
portrait-cutout input.jpg --transparent

# 调后处理参数
portrait-cutout input.jpg --threshold 180 --open-ksize 5

# 查看帮助（含背景色表格）
portrait-cutout -h

# 打包为独立可执行文件
pyinstaller --onefile --collect-all rembg --collect-all onnxruntime cli.py
```

## 核心模块说明

### `core.py`

- `portrait_cutout(input_path, output_path, model_name, threshold, open_ksize, erode_iter, blur_sigma, background)`
  - 使用 `rembg.remove()` 获取 RGBA 图像，`alpha_matting=False`
  - 提取 alpha 通道，调用 `clean_alpha()` 清理发丝
  - 合成原图 RGB + 清理后的 alpha；`background` 为 RGB 三元组时铺底色，为 `None` 时保留透明
  - 输出格式由扩展名决定；透明 + JPEG 会直接抛 `ValueError`
- `clean_alpha(alpha, threshold, open_ksize, erode_iter, blur_sigma)`
  - 二值化 → 开运算 → 可选腐蚀 → 高斯羽化
- `composite_on_color(rgba, color)`
  - 按 alpha 把 RGBA 混合到纯色背景，返回 RGB 数组；羽化边缘因此与底色自然过渡
- `parse_color(value)` / `BACKGROUND_PRESETS` / `BACKGROUND_ALIASES` / `STANDARD_BLUE` / `DEFAULT_BACKGROUND`
  - 背景色预设与解析（预设名、中文名、`#RRGGBB` 都支持）
- `validate_alpha_params(...)`
  - 后处理参数校验，被 `clean_alpha()` 和 `portrait_cutout()` 共用；
    `portrait_cutout()` 在**跑分割之前**调用它，参数写错不会白等一次推理

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

## 背景色

默认铺标准蓝（`#438EDB`），透明背景需要显式 `--transparent`。

| 预设名 | HEX | 中文 | 场景 |
|---|---|---|---|
| `white` | `#FFFFFF` | 白色 | 身份证、护照、签证、驾驶证 |
| `red` | `#FF0000` | 红色 | 结婚登记照、荣誉证书、保险、IC 卡 |
| `blue` | `#438EDB` | 标准蓝色 | 简历、工作牌、入职、毕业照（**默认**） |
| `darkblue` | `#0066CC` | 深蓝色 | 公务员考试、事业单位报名、四六级 |
| `lightblue` | `#64C5FF` | 浅蓝色 | 教育部学历证书图像采集标准 |
| `lightgray` | `#F0F0F0` | 浅灰色 | 教育部学历证书图像采集标准 |

设计约束（改动时注意）：

- `--bg` 与 `--transparent` 用 argparse **互斥组**，不要改成"后者覆盖前者"
- `--bg` 通过 `type=color_arg` 在**解析阶段**校验，错误以 `ArgumentTypeError` 抛出，
  这样 `-h` 之外的非法输入能给出可读提示而不是堆栈
- 预设表在 `core.BACKGROUND_PRESETS`，`cli.COLOR_TABLE` 是它的展示副本，**改一处要同步另一处**
- 输出格式跟随 `-o` 的扩展名；透明 + `.jpg` 明确报错，不要把 PNG 数据塞进 .jpg

## 模型与运行环境

- 默认模型：`birefnet-portrait`（1024×1024 推理，927MB）
- 模型缓存：`~/.rembg/models/<模型名>/`（首次运行自动下载；旧版 rembg 平铺在 `~/.u2net`，仍会被复用）
- CPU 推理：`onnxruntime`
- GPU 推理：`onnxruntime-gpu`（不要与 CPU 版同时安装）
- 备选：`isnet-general-use`（1024×1024，170MB，尚未实测对比）、`u2net_human_seg`（320×320，167MB）
- **不要把默认换回 `u2net_human_seg`**：它按 320×320 推理，分辨不出发丝，mask 是光滑团块、边缘留一圈背景光晕，达不到本工具的目标。后处理参数也救不了——腐蚀只能整体缩小轮廓。实测对比见 README

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
    "rembg",
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

依赖用 `rembg` 而非 `rembg[cli]`：后者会额外拖入 gradio / fastapi / uvicorn 等 51 个包（整套 Web UI 栈），而本工具自带命令行入口，用不到 rembg 自带的 CLI。

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