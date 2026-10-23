"""图片附件校验与编码，不依赖界面或数据库。"""

from pathlib import Path

from PIL import Image, ImageOps


def save_attachment_image(source: Path, target: Path) -> tuple[int, int]:
    """完整解码后保存标准 PNG，返回页面上的初始显示尺寸。"""
    # 不将未验证的原文件交给客户端解码。统一成静态 RGBA，保留透明背景，
    # 同时修正手机照片的 EXIF 旋转；损坏图片在数据库写入前就会失败。
    with Image.open(source) as original:
        original.seek(0)
        image = ImageOps.exif_transpose(original).convert("RGBA")
        image.load()
    image.save(target, format="PNG")
    image.thumbnail((240, 180))
    return image.size
