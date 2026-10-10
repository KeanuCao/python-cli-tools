"""portrait-cutout 命令行入口。

只负责参数解析与结果输出，抠图逻辑全部在 core.py 中。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple, Union

from core import (
    AVAILABLE_MODELS,
    DEFAULT_BACKGROUND,
    DEFAULT_MODEL,
    MODEL_SIZES_MB,
    is_model_cached,
    model_dir,
    parse_color,
    portrait_cutout,
)

# --description 的输出：讲清"这是什么工具"，不是用法
DESCRIPTION = (
    "portrait-cutout 是一个人像抠图工具：输入一张人像照片，"
    "自动分离人物与背景，清理边缘多余的发丝，并铺上证件照标准背景色"
    "（默认标准蓝）输出；加 --transparent 则输出透明背景 PNG。"
)

# 帮助里展示的背景色表格，和 core.BACKGROUND_PRESETS 保持一致
COLOR_TABLE = """\
背景色预设（--bg）：
  white      #FFFFFF   白色    身份证、护照、签证、驾驶证、考试报名
  red        #FF0000   红色    结婚登记照、荣誉证书、保险、IC 卡
  blue       #438EDB   标准蓝  简历、工作牌、入职、毕业照（默认，最常用）
  darkblue   #0066CC   深蓝色  公务员考试、事业单位报名、四六级
  lightblue  #64C5FF   浅蓝色  教育部学历证书图像采集标准
  lightgray  #F0F0F0   浅灰色  教育部学历证书图像采集标准

预设名也接受中文（--bg 深蓝色），或直接给十六进制色值（--bg "#A0C8F0"）。
"""


def color_arg(value: str) -> Tuple[int, int, int]:
    """argparse 的 type 钩子：把颜色解析失败转成可读的参数错误。"""
    try:
        return parse_color(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def force_utf8_output() -> None:
    """把 stdout/stderr 固定为 UTF-8。

    Windows 上输出被重定向（管道、写文件）时 Python 默认用本地编码（简体中文
    为 GBK），输出中一旦出现 GBK 编不了的字符（比如文件路径里的生僻字）就会抛
    UnicodeEncodeError 直接崩掉。终端直连时 Python 走 WriteConsoleW，不受影响。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="portrait-cutout",
        description="对人像图片进行智能抠图，去除边缘多余发丝，输出证件照标准底色的图片。",
        epilog=(
            "示例：\n"
            "  portrait-cutout photo.jpg                   # 铺标准蓝底（默认）\n"
            "  portrait-cutout photo.jpg --bg white        # 白底\n"
            "  portrait-cutout photo.jpg --bg \"#A0C8F0\"    # 自定义底色\n"
            "  portrait-cutout photo.jpg --transparent     # 透明背景 PNG\n"
            "\n" + COLOR_TABLE
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # nargs="?" 是为了让 --description / -h 在缺少输入图片时也能正常执行
    parser.add_argument(
        "input",
        nargs="?",
        help="输入图片路径（jpg / png / webp 等）",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="输出路径（格式按扩展名，如 .png / .jpg），"
        "默认为输入图片同目录下的 <文件名>_cutout.png",
    )

    # 铺底色还是保留透明，二选一
    background_group = parser.add_mutually_exclusive_group()
    background_group.add_argument(
        "--bg",
        default=DEFAULT_BACKGROUND,
        type=color_arg,
        metavar="颜色",
        help=f"背景色，预设名或 #RRGGBB（默认 {DEFAULT_BACKGROUND} 标准蓝 #438EDB），预设见下",
    )
    background_group.add_argument(
        "--transparent",
        action="store_true",
        help="输出透明背景，不铺底色（与 --bg 互斥；JPEG 不支持透明，需配 .png）",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=AVAILABLE_MODELS,
        help=f"分割模型（默认 {DEFAULT_MODEL}）",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=160,
        help="alpha 二值化阈值；发丝多则调高，主体被吃掉则调低（默认 160）",
    )
    parser.add_argument(
        "--open-ksize",
        type=int,
        default=3,
        help="开运算核大小；发丝顽固可调到 5 或 7（默认 3）",
    )
    parser.add_argument(
        "--erode-iter",
        type=int,
        default=0,
        help="额外腐蚀次数；仍有余发时用 1~2（默认 0）",
    )
    parser.add_argument(
        "--blur-sigma",
        type=float,
        default=1.0,
        help="边缘羽化 sigma；边缘生硬时用 1.5~2.0（默认 1.0）",
    )
    parser.add_argument(
        "--description",
        action="store_true",
        help="输出本工具的简要说明后退出",
    )
    return parser


def default_output_path(input_path: Union[str, Path]) -> Path:
    """未指定 -o 时，在输入图片旁生成 <文件名>_cutout.png。"""
    path = Path(input_path)
    return path.with_name(f"{path.stem}_cutout.png")


def main(argv: Optional[List[str]] = None) -> int:
    force_utf8_output()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.description:
        print(DESCRIPTION)
        return 0

    if not args.input:
        parser.error("缺少输入图片路径（用 -h 查看用法，用 --description 查看工具说明）")

    if not is_model_cached(args.model):
        size = MODEL_SIZES_MB.get(args.model)
        size_hint = f"约 {size}MB，" if size else ""
        print(
            f"首次使用模型 {args.model}，正在下载（{size_hint}缓存于 {model_dir(args.model)}）…",
            file=sys.stderr,
        )

    try:
        output = portrait_cutout(
            args.input,
            args.output or default_output_path(args.input),
            model_name=args.model,
            threshold=args.threshold,
            open_ksize=args.open_ksize,
            erode_iter=args.erode_iter,
            blur_sigma=args.blur_sigma,
            background=None if args.transparent else args.bg,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(f"已输出：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
