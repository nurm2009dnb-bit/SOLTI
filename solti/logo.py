"""Логотип SOLTI - планета с кольцами, похожая на Сатурн.

Логотип не хранится картинкой, а рисуется кодом с помощью Pillow (PIL).
Плюсы: не нужно таскать файлы картинок вместе с программой и .exe,
а размер можно получить любой без потери качества.

Как рисуем:
  1. Кольцо - два эллипса: большой закрашенный и меньший "вырезанный" внутри.
  2. Планета - круг с плавным переходом цвета (сверху-слева светлее, как от солнца)
     и несколькими полосами, как у настоящего Сатурна.
  3. Порядок слоёв: задняя половина кольца -> планета -> передняя половина кольца.
     Так кажется, что кольцо проходит ЗА планетой и ПЕРЕД ней.
  4. Всё рисуется в 4 раза крупнее и потом уменьшается - так края получаются гладкими.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw   # Pillow - библиотека для работы с картинками

TILT_DEGREES = 18   # наклон кольца и полос планеты
SUPERSAMPLE = 4     # во сколько раз крупнее рисуем перед уменьшением

PLANET_DARK = (168, 112, 52)     # тень планеты
PLANET_LIGHT = (255, 222, 160)   # блик планеты
BAND_COLOR = (140, 90, 40, 70)   # полупрозрачные полосы на планете
RING_OUTER = (222, 200, 160, 235)
RING_GAP = (120, 95, 65, 200)    # тёмная щель между кольцами (как щель Кассини)
RING_INNER = (190, 160, 115, 235)
TRANSPARENT = (0, 0, 0, 0)


def _mix(color_a: tuple, color_b: tuple, amount: float) -> tuple:
    """Смешивает два цвета: amount=0 -> первый цвет, amount=1 -> второй."""
    return tuple(round(a + (b - a) * amount) for a, b in zip(color_a, color_b))


def _ellipse(draw: ImageDraw.ImageDraw, cx: float, cy: float, rx: float, ry: float, fill) -> None:
    """Рисует эллипс по центру и двум радиусам (Pillow хочет углы прямоугольника)."""
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=fill)


def _draw_ring(canvas: int) -> Image.Image:
    """Кольцо без наклона. Из нескольких эллипсов, середина прозрачная."""
    ring = Image.new("RGBA", (canvas, canvas), TRANSPARENT)
    draw = ImageDraw.Draw(ring)
    center = canvas / 2
    _ellipse(draw, center, center, canvas * 0.49, canvas * 0.155, RING_OUTER)
    _ellipse(draw, center, center, canvas * 0.44, canvas * 0.135, RING_GAP)
    _ellipse(draw, center, center, canvas * 0.425, canvas * 0.128, RING_INNER)
    # "вырезаем" середину: ImageDraw не смешивает цвета, а заменяет пиксели, поэтому получится дырка
    _ellipse(draw, center, center, canvas * 0.335, canvas * 0.092, TRANSPARENT)
    return ring


def _draw_planet(canvas: int) -> Image.Image:
    """Планета: круг с переходом от тени к блику и полосами."""
    planet = Image.new("RGBA", (canvas, canvas), TRANSPARENT)
    draw = ImageDraw.Draw(planet)
    center = canvas / 2
    radius = canvas * 0.27

    # Градиент: рисуем много кругов, каждый следующий меньше, светлее и сдвинут к левому верху.
    steps = 60
    for step in range(steps):
        t = step / steps
        r = radius * (1 - 0.85 * t)
        shift = radius * 0.35 * t
        color = _mix(PLANET_DARK, PLANET_LIGHT, t) + (255,)
        _ellipse(draw, center - shift, center - shift, r, r, color)

    # Полосы рисуем отдельным слоем и оставляем только то, что попало внутрь круга
    bands = Image.new("RGBA", (canvas, canvas), TRANSPARENT)
    bands_draw = ImageDraw.Draw(bands)
    for offset, thickness in ((-0.55, 0.08), (-0.15, 0.06), (0.25, 0.10), (0.6, 0.05)):
        y = center + radius * offset
        bands_draw.rectangle((0, y, canvas, y + radius * thickness), fill=BAND_COLOR)
    circle_mask = Image.new("L", (canvas, canvas), 0)
    _ellipse(ImageDraw.Draw(circle_mask), center, center, radius, radius, 255)
    clipped_bands = Image.new("RGBA", (canvas, canvas), TRANSPARENT)
    clipped_bands.paste(bands, (0, 0), circle_mask)

    return Image.alpha_composite(planet, clipped_bands)


def draw_saturn(size: int = 256) -> Image.Image:
    """Готовый логотип size x size пикселей с прозрачным фоном."""
    canvas = size * SUPERSAMPLE
    center = canvas / 2

    ring = _draw_ring(canvas)
    # Передняя половина кольца - это его нижняя часть (до наклона)
    ring_front = ring.copy()
    ImageDraw.Draw(ring_front).rectangle((0, 0, canvas, center), fill=TRANSPARENT)

    planet = _draw_planet(canvas)

    # Наклоняем всё на один и тот же угол, чтобы кольцо и полосы были параллельны
    ring = ring.rotate(TILT_DEGREES, resample=Image.BICUBIC)
    ring_front = ring_front.rotate(TILT_DEGREES, resample=Image.BICUBIC)
    planet = planet.rotate(TILT_DEGREES, resample=Image.BICUBIC)

    logo = Image.new("RGBA", (canvas, canvas), TRANSPARENT)
    logo = Image.alpha_composite(logo, ring)        # кольцо целиком (задняя часть останется видна)
    logo = Image.alpha_composite(logo, planet)      # планета закрывает середину кольца
    logo = Image.alpha_composite(logo, ring_front)  # передняя часть кольца поверх планеты

    return logo.resize((size, size), Image.LANCZOS)   # LANCZOS - качественное уменьшение


def save_icon(path: Path) -> Path:
    """Сохраняет логотип как .ico (в одном файле сразу несколько размеров для Windows)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    draw_saturn(256).save(path, format="ICO",
                          sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def ensure_icon_file(path: Path) -> Path:
    """Возвращает путь к иконке; если файла ещё нет - рисует его."""
    path = Path(path)
    if not path.exists():
        save_icon(path)
    return path


if __name__ == "__main__":
    # python -m solti.logo  -> сохранит логотип в папку assets (нужно для сборки .exe с иконкой)
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(exist_ok=True)
    draw_saturn(512).save(assets / "solti.png")
    save_icon(assets / "solti.ico")
    print("Логотип сохранён в", assets)
