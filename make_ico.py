# make_ico.py
from pathlib import Path
from PIL import Image

BASE = Path(__file__).resolve().parent
ASSETS = BASE / "assets"

src = None
for name in ("miku_nobg.png", "miku.png"):
    p = ASSETS / name
    if p.exists():
        src = p
        break

if src is None:
    print("Не нашёл ни miku_nobg.png, ни miku.png в assets/")
    raise SystemExit(1)

img = Image.open(src).convert("RGBA")
# делаем квадрат по центру
w, h = img.size
side = min(w, h)
left = (w - side) // 2
top = (h - side) // 2
img = img.crop((left, top, left + side, top + side))

sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
out = ASSETS / "miku.ico"
img.save(out, format="ICO", sizes=sizes)
print("Готово:", out)
