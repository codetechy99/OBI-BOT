from PIL import Image, ImageDraw, ImageFont
import os

def create_app_icon(size):
    # Dark black background
    img = Image.new("RGBA", (size, size), (18, 18, 18, 255))
    draw = ImageDraw.Draw(img)

    # Outer border circle
    padding = size // 10
    draw.ellipse(
        [padding, padding, size - padding, size - padding],
        outline=(252, 213, 53, 255),  # Gold #FCD535
        width=max(2, size // 30)
    )

    # Draw OBI text / Chart Arrow shape
    # Upward green candle and downward red candle symbol with gold arrow
    cx, cy = size // 2, size // 2
    r = size // 4

    # Green bar (Bid)
    draw.rectangle([cx - r//1.2, cy - r//2, cx - r//4, cy + r], fill=(14, 203, 129, 255))
    # Red bar (Ask)
    draw.rectangle([cx + r//4, cy - r, cx + r//1.2, cy + r//1.5], fill=(246, 70, 93, 255))

    # Gold central trend arrow
    arrow_points = [
        (cx - r, cy + r//1.5),
        (cx - r//3, cy),
        (cx + r//3, cy - r//3),
        (cx + r, cy - r*1.2),
        (cx + r, cy - r//2),
        (cx + r//3, cy),
        (cx - r//3, cy + r//3),
        (cx - r, cy + r)
    ]
    draw.polygon(arrow_points, fill=(252, 213, 53, 255))

    return img

os.makedirs("static", exist_ok=True)
icon_512 = create_app_icon(512)
icon_512.save("static/icon-512.png")

icon_192 = create_app_icon(192)
icon_192.save("static/icon-192.png")

icon_192.save("static/favicon.ico", format="ICO", sizes=[(32, 32), (64, 64), (128, 128)])
print("Icons generated successfully in static/")
