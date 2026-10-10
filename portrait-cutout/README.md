# portrait-cutout

人像抠图命令行工具。输入一张人像照片，自动分离人物与背景，清理边缘多余的发丝，
铺上证件照标准背景色输出（默认标准蓝）。需要透明背景时加 `--transparent`。

流程：AI 分割（rembg）→ 取 alpha 通道 → OpenCV 形态学清理 → 铺背景色或保留透明 → 输出。

## 安装

```bash
cd portrait-cutout
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .                 # 开发调试
pipx install .                   # 部署（推荐）
```

## 使用

```bash
portrait-cutout photo.jpg                          # 标准蓝底 → photo_cutout.png
portrait-cutout photo.jpg --bg white               # 白底
portrait-cutout photo.jpg --bg 深蓝色               # 中文名也行
portrait-cutout photo.jpg --bg "#A0C8F0"           # 任意十六进制色值
portrait-cutout photo.jpg --transparent            # 透明背景 PNG
portrait-cutout photo.jpg -o out.jpg               # 输出格式按扩展名
portrait-cutout photo.jpg --threshold 180 --open-ksize 5
```

通用参数：

```bash
portrait-cutout --description    # 这个工具是做什么的
portrait-cutout -h               # 完整用法（含背景色表格）
```

## 参数

| 参数 | 作用 | 默认 |
|---|---|---|
| `--bg` | 背景色：预设名（中英文均可）或 `#RRGGBB` | `blue` 标准蓝 #438EDB |
| `--transparent` | 输出透明背景，不铺底色（与 `--bg` 互斥） | 关 |
| `-o` / `--output` | 输出路径，格式按扩展名 | `<文件名>_cutout.png` |
| `--threshold` | alpha 二值化阈值 | 160 |
| `--open-ksize` | 开运算核大小 | 3 |
| `--erode-iter` | 额外腐蚀次数 | 0 |
| `--blur-sigma` | 边缘羽化 sigma | 1.0 |
| `--model` | 分割模型 | `birefnet-portrait` |

边缘调整建议：

| 情况 | 调整 |
|---|---|
| 发丝多 / 边缘留光晕 | `--threshold 180~200` |
| 主体被吃掉 | 降低 `--threshold` |
| 发丝顽固 | `--open-ksize 5` 或 `7` |
| 仍有余发 | `--erode-iter 1~2` |
| 边缘生硬 | `--blur-sigma 1.5~2.0` |

## 背景色

证件照常用底色，`--bg` 直接传预设名（中文名同样可用）：

| 预设名 | HEX | 中文 | 常见适用场景 |
|---|---|---|---|
| `white` | `#FFFFFF` | 白色 | 身份证、护照、签证、驾驶证、部分考试报名 |
| `red` | `#FF0000` | 红色 | 结婚登记照、荣誉证书、保险、IC 卡、暂住证 |
| `blue` | `#438EDB` | 标准蓝色 | 求职简历、工作牌、企业入职、毕业照（**默认，最常用**） |
| `darkblue` | `#0066CC` | 深蓝色 | 国家公务员考试、事业单位报名、四六级（政务系统） |
| `lightblue` | `#64C5FF` | 浅蓝色 | 教育部学历证书电子注册图像采集标准 |
| `lightgray` | `#F0F0F0` | 浅灰色 | 教育部学历证书电子注册图像采集标准（与浅蓝、白并列可选） |

预设名大小写与 `-`/`_`/空格不敏感（`dark-blue`、`Dark Blue` 都可以），
也可以用中文名（`--bg 深蓝色`）。任何其他颜色直接给十六进制：`--bg "#A0C8F0"`。

背景色通过与 alpha 通道混合铺上，羽化边缘会和底色自然过渡。

## 模型

首次运行会自动下载模型到 `~/.rembg/models/<模型名>/`。

| 模型 | 推理分辨率 | 下载 | 特点 |
|---|---|---|---|
| `birefnet-portrait` | 1024×1024 | 927 MB | **默认**，能分辨单根发丝，CPU 推理较慢 |
| `isnet-general-use` | 1024×1024 | 170 MB | 通用模型，体积小，尚未实测对比 |
| `u2net_human_seg` | 320×320 | 167 MB | 最快最小，但抠不出发丝，见下 |

### 为什么默认不是 u2net_human_seg

它按 **320×320** 推理，整颗头在模型眼里只有约 100px 宽，物理上分辨不出发丝。
输出的 mask 是一个光滑团块，轮廓外带一圈背景光晕（浅色墙面上尤其明显）。

后处理参数救不了这种情况：腐蚀只能让轮廓整体缩小，没法让边界贴合头发。

`birefnet-portrait` 按 1024×1024 推理，同一张图光晕消失、飞散发丝根根分明。
代价是模型大 5.5 倍、CPU 推理更慢。

CPU 推理用 `onnxruntime`；装了 `onnxruntime-gpu` 则自动走 GPU（不要与 CPU 版同时安装）。

## 打包为独立可执行文件

```bash
pyinstaller --onefile --collect-all rembg --collect-all onnxruntime cli.py
```
