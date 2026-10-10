"""portrait-cutout 核心逻辑：AI 分割 + alpha 通道后处理。

本模块不依赖 CLI，可单独导入使用。
流程：rembg 分割 → 取 alpha 通道 → OpenCV 形态学清理 → 铺背景色或保留透明 → 输出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image
from rembg import new_session, remove
from rembg.sessions import sessions

# 默认模型：1024x1024 推理，能分辨出单根发丝。
# 不用 u2net_human_seg 当默认——它是 320x320 推理，mask 是个光滑团块，
# 边缘会留一圈背景光晕，达不到本工具"去发丝"的目标（实测见 README）。
DEFAULT_MODEL = "birefnet-portrait"

# 可选模型，按精度 / 速度 / 体积取舍
AVAILABLE_MODELS = (
    "birefnet-portrait",
    "isnet-general-use",
    "u2net_human_seg",
)

# 各模型的下载体积（MB），只用于首次下载时的提示文案
MODEL_SIZES_MB = {
    "birefnet-portrait": 927,
    "isnet-general-use": 170,
    "u2net_human_seg": 167,
}

# new_session() 会加载 ONNX 模型（数百毫秒到数秒），缓存起来避免重复开销
_sessions: Dict[str, object] = {}

# 证件照标准背景色。右列是常见适用场景，仅作选色参考。
BACKGROUND_PRESETS: Dict[str, Tuple[int, int, int]] = {
    "white": (255, 255, 255),      # 白色：身份证、护照、签证、驾驶证、考试报名
    "red": (255, 0, 0),            # 红色：结婚登记照、荣誉证书、保险、IC 卡
    "blue": (67, 142, 219),        # 标准蓝色：简历、工作牌、入职、毕业照（最常用）
    "darkblue": (0, 102, 204),     # 深蓝色：公务员考试、事业单位报名、四六级
    "lightblue": (100, 197, 255),  # 浅蓝色：教育部学历证书图像采集标准
    "lightgray": (240, 240, 240),  # 浅灰色：教育部学历证书图像采集标准
}

# 标准蓝色，证件照最常用的底色，作为默认背景
STANDARD_BLUE: Tuple[int, int, int] = BACKGROUND_PRESETS["blue"]

# 默认背景色预设名（CLI 未指定 --bg / --transparent 时使用）
DEFAULT_BACKGROUND = "blue"

# 中文名（及少量同义写法）到预设名的映射，方便直接 --bg 深蓝色
BACKGROUND_ALIASES: Dict[str, str] = {
    "白色": "white",
    "红色": "red",
    "蓝色": "blue",
    "标准蓝色": "blue",
    "深蓝色": "darkblue",
    "浅蓝色": "lightblue",
    "灰色": "lightgray",
    "浅灰色": "lightgray",
}


def parse_color(value: str) -> Tuple[int, int, int]:
    """把预设名、中文名或十六进制色值解析成 RGB 三元组。

    支持：
    - 预设名，大小写和 -/_/空格 不敏感（blue、dark-blue、Dark Blue 都行）
    - 中文名（标准蓝色、深蓝色、浅灰色 …）
    - 十六进制（#438EDB、438edb、#FFF）
    """
    if not isinstance(value, str):
        raise ValueError(f"无法识别的颜色：{value!r}")

    raw = value.strip()
    if raw in BACKGROUND_ALIASES:
        return BACKGROUND_PRESETS[BACKGROUND_ALIASES[raw]]
    if raw in BACKGROUND_PRESETS:
        return BACKGROUND_PRESETS[raw]

    key = raw.lower().replace("-", "").replace("_", "").replace(" ", "")
    if key in BACKGROUND_PRESETS:
        return BACKGROUND_PRESETS[key]

    digits = key[2:] if key.startswith("0x") else key.lstrip("#")
    if len(digits) == 3 and all(c in "0123456789abcdef" for c in digits):
        digits = "".join(c * 2 for c in digits)  # #abc -> #aabbcc
    if len(digits) == 6 and all(c in "0123456789abcdef" for c in digits):
        return (
            int(digits[0:2], 16),
            int(digits[2:4], 16),
            int(digits[4:6], 16),
        )

    names = " / ".join(BACKGROUND_PRESETS)
    raise ValueError(f"无法识别的颜色：{value}（可用预设：{names}，或 #RRGGBB）")


def composite_on_color(
    rgba: np.ndarray, color: Tuple[int, int, int]
) -> np.ndarray:
    """把带 alpha 的 RGBA 合成到纯色背景上，返回 RGB 数组。

    边缘的半透明像素按 alpha 与背景色混合，羽化过渡因此保持自然。
    """
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"需要 RGBA 数组，收到 shape={rgba.shape}")

    alpha = rgba[:, :, 3:4].astype(np.float32) / 255.0
    foreground = rgba[:, :, :3].astype(np.float32)
    background = np.array(color, dtype=np.float32).reshape(1, 1, 3)

    blended = foreground * alpha + background * (1.0 - alpha)
    return np.clip(blended + 0.5, 0, 255).astype(np.uint8)


def model_dir(model_name: str = DEFAULT_MODEL) -> Path:
    """模型在本地的存放目录。

    路径交给 rembg 决定（当前版本是 ~/.rembg/models/<模型名>），不要自己拼：
    rembg 改过缓存布局，旧版平铺在 ~/.u2net，新版按模型分目录。
    """
    session_cls = sessions.get(model_name)
    if session_cls is None:
        raise ValueError(f"未知模型：{model_name}")
    return Path(session_cls.model_dir())


def is_model_cached(model_name: str = DEFAULT_MODEL) -> bool:
    """模型是否已下载到本地。未下载时首次运行会联网拉取。

    resolve_existing() 会同时检查新版分目录布局和旧版 ~/.u2net 平铺布局。
    """
    session_cls = sessions.get(model_name)
    if session_cls is None or not session_cls.is_local():
        return False
    return session_cls.resolve_existing(f"{model_name}.onnx") is not None


def get_session(model_name: str = DEFAULT_MODEL):
    """按模型名获取（并缓存）rembg 会话。

    把 rembg 的会话细节收敛在这里，CLI 不必直接依赖 rembg。
    """
    if model_name not in _sessions:
        _sessions[model_name] = new_session(model_name)
    return _sessions[model_name]


def smooth_outline(mask: np.ndarray, sigma: float) -> np.ndarray:
    """沿外轮廓做环绕高斯平滑，抹掉头发轮廓上的凸起（翘起的发绺、碎发团）。

    轮廓是一圈闭合的点序列，用首尾相接的高斯核做滑动平均即可把局部凸起
    抹平。因为只重排轮廓、不整体腐蚀，所以头部大小基本不变——这跟开运算
    的无差别削边有本质区别（见 README 的说明）。

    sigma 约等于能抹平的特征尺度（像素）：要消掉一撮约 100px 的发绺，
    sigma 需要给到 100 以上。代价是比它更细的发丝也会一起被抹平，所以
    默认 0（不平滑）。只处理外轮廓，不动内部空洞。
    """
    if sigma <= 0:
        return mask

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    smoothed = np.zeros_like(mask)

    radius = int(3 * sigma)
    offsets = np.arange(-radius, radius + 1)
    kernel = np.exp(-(offsets**2) / (2 * sigma**2))
    kernel /= kernel.sum()

    for contour in contours:
        points = contour[:, 0, :].astype(np.float64)
        count = len(points)
        if count < len(kernel):
            # 轮廓太短，平滑没有意义，原样保留
            cv2.fillPoly(smoothed, [contour], 255)
            continue
        # np.take 的 wrap 模式实现首尾相接，convolve 的 valid 模式让长度回到 count
        wrapped = np.arange(-radius, count + radius)
        xs = np.convolve(np.take(points[:, 0], wrapped, mode="wrap"), kernel, "valid")
        ys = np.convolve(np.take(points[:, 1], wrapped, mode="wrap"), kernel, "valid")
        polygon = np.stack([xs, ys], axis=1).astype(np.int32)
        cv2.fillPoly(smoothed, [polygon], 255)

    return smoothed


def validate_alpha_params(
    threshold: int = 160,
    open_ksize: int = 3,
    erode_iter: int = 0,
    blur_sigma: float = 1.0,
    smooth_edge: float = 0.0,
) -> None:
    """校验后处理参数，非法时抛 ValueError。

    单独抽出来是为了让 portrait_cutout() 能在跑分割之前先校验，
    避免参数写错还要白等一次模型推理。
    """
    if not 0 <= threshold <= 255:
        raise ValueError(f"threshold 必须在 0~255 之间，收到 {threshold}")
    if open_ksize < 1:
        raise ValueError(f"open-ksize 必须为正整数，收到 {open_ksize}")
    if erode_iter < 0:
        raise ValueError(f"erode-iter 不能为负数，收到 {erode_iter}")
    if blur_sigma < 0:
        raise ValueError(f"blur-sigma 不能为负数，收到 {blur_sigma}")
    if smooth_edge < 0:
        raise ValueError(f"smooth-edge 不能为负数，收到 {smooth_edge}")


def clean_alpha(
    alpha: np.ndarray,
    threshold: int = 160,
    open_ksize: int = 3,
    erode_iter: int = 0,
    blur_sigma: float = 1.0,
    smooth_edge: float = 0.0,
) -> np.ndarray:
    """清理 alpha 通道：二值化 → 开运算 → 可选腐蚀 → 轮廓平滑 → 高斯羽化。

    开运算和腐蚀负责去掉边缘多余发丝，轮廓平滑负责抹掉翘起的发绺等大块
    凸起，羽化让边界过渡自然。

    参数：
        alpha       二维 uint8 数组，rembg 分割出的前景置信度
        threshold   二值化阈值，发丝多则调高，主体被吃掉则调低
        open_ksize  开运算核大小，越大去发丝越狠
        erode_iter  额外腐蚀次数，开运算仍去不干净时使用
        blur_sigma  羽化 sigma，0 表示不羽化
        smooth_edge 轮廓平滑 sigma，0 表示不平滑；见 smooth_outline()

    返回同尺寸的 uint8 数组。
    """
    if alpha.ndim != 2:
        raise ValueError(f"alpha 必须是二维数组，收到 shape={alpha.shape}")
    validate_alpha_params(threshold, open_ksize, erode_iter, blur_sigma, smooth_edge)

    # 1. 二值化：低于阈值的半透明像素（多为发丝残留）直接判为背景
    _, mask = cv2.threshold(alpha, threshold, 255, cv2.THRESH_BINARY)

    # 2. 开运算（先腐蚀后膨胀）：抹掉细碎的前景噪点，主体轮廓基本不变
    if open_ksize > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_ksize, open_ksize))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    # 3. 额外腐蚀：对付开运算仍去不掉的顽固发丝
    if erode_iter > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.erode(mask, kernel, iterations=erode_iter)

    # 4. 轮廓平滑：抹掉翘起的发绺这类大块凸起，整理出干净的证件照外形
    if smooth_edge > 0:
        mask = smooth_outline(mask, smooth_edge)

    # 5. 羽化：高斯模糊把硬边变成渐变，避免锯齿状边界
    if blur_sigma > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), blur_sigma)

    return mask


def portrait_cutout(
    input_path: Union[str, Path],
    output_path: Union[str, Path],
    model_name: str = DEFAULT_MODEL,
    threshold: int = 160,
    open_ksize: int = 3,
    erode_iter: int = 0,
    blur_sigma: float = 1.0,
    smooth_edge: float = 0.0,
    background: Optional[Tuple[int, int, int]] = STANDARD_BLUE,
) -> Path:
    """对人像图片抠图并输出，返回实际写入的路径。

    background 传 RGB 三元组就铺该背景色（默认标准蓝）；传 None 则保留透明背景，
    此时输出格式必须支持 alpha（PNG / WebP），用 JPEG 会直接报错。
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    # 先校验参数：分割很贵，参数写错不该等到分割完才报
    validate_alpha_params(threshold, open_ksize, erode_iter, blur_sigma, smooth_edge)

    suffix = output_path.suffix.lower()
    if background is None and suffix in (".jpg", ".jpeg"):
        raise ValueError(
            f"{suffix} 不支持透明通道：透明背景请输出 .png，"
            "或去掉透明背景改为铺背景色"
        )

    if not input_path.is_file():
        raise FileNotFoundError(f"找不到输入图片：{input_path}")

    # 统一转成 RGB，顺带丢掉可能存在的 EXIF 方向等干扰
    source = Image.open(input_path).convert("RGB")

    # rembg 返回 RGBA：RGB 是原图，A 是分割出的前景置信度
    rgba = remove(source, session=get_session(model_name), alpha_matting=False)
    alpha = np.asarray(rgba)[:, :, 3]

    cleaned = clean_alpha(
        alpha, threshold, open_ksize, erode_iter, blur_sigma, smooth_edge
    )

    # 用清理后的 alpha 替换原 alpha，RGB 沿用原图，避免分割过程带来的颜色损失
    cutout = np.dstack([np.asarray(source), cleaned])

    if background is None:
        image = Image.fromarray(cutout)
    else:
        image = Image.fromarray(composite_on_color(cutout, background))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if suffix:
        image.save(output_path)  # 格式由扩展名决定
    else:
        image.save(output_path, format="PNG")  # 没写扩展名时按 PNG 存

    return output_path
