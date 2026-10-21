"""Create the ReadDraw Windows icon in deterministic raster sizes."""

from pathlib import Path

from PIL import Image, ImageDraw


def draw_icon(size: int) -> Image.Image:
    scale = size / 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    def box(values):
        return tuple(round(value * scale) for value in values)

    draw.rounded_rectangle(box((8, 8, 248, 248)), radius=round(52 * scale), fill="#1D2939")
    draw.rounded_rectangle(box((54, 42, 184, 211)), radius=round(12 * scale), fill="#FFFFFF")
    draw.polygon([box((154, 42))[0:2], box((184, 72))[0:2], box((154, 72))[0:2]], fill="#D0D5DD")
    draw.line([box((78, 97))[0:2], box((160, 97))[0:2]], fill="#3857D6", width=max(2, round(9 * scale)))
    draw.line([box((78, 124))[0:2], box((151, 124))[0:2]], fill="#12B76A", width=max(2, round(9 * scale)))
    draw.line([box((78, 151))[0:2], box((135, 151))[0:2]], fill="#F79009", width=max(2, round(9 * scale)))
    draw.polygon([box((138, 199))[0:2], box((195, 142))[0:2], box((215, 162))[0:2], box((158, 219))[0:2]], fill="#E45756")
    draw.polygon([box((138, 199))[0:2], box((158, 219))[0:2], box((132, 226))[0:2]], fill="#FDEAD7")
    return image


output = Path(__file__).resolve().parent.parent / "assets" / "ReadDraw.ico"
output.parent.mkdir(parents=True, exist_ok=True)
draw_icon(1024).save(output, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print(output)
