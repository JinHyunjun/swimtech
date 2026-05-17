from PIL import Image, ImageDraw, ImageFont
import os

sizes = [72, 96, 128, 144, 152, 192, 384, 512]
out_dir = r"C:\swim\frontend\static\icons"
os.makedirs(out_dir, exist_ok=True)

bg_color = (26, 26, 46)    # #1a1a2e
accent   = (59, 130, 246)  # #3b82f6

for size in sizes:
    img  = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    pad = size // 8
    draw.ellipse([pad, pad, size - pad, size - pad], fill=accent)

    letter = "S"
    font_size = int(size * 0.55)
    font = None
    for fname in ["arialbd.ttf", "C:/Windows/Fonts/arialbd.ttf",
                  "C:/Windows/Fonts/arial.ttf"]:
        try:
            font = ImageFont.truetype(fname, font_size)
            break
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), letter, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), letter, fill=(255, 255, 255), font=font)

    path = os.path.join(out_dir, f"icon-{size}.png")
    img.save(path)
    print(f"Created {path}")

print("Done.")
