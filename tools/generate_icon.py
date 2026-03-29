"""Generate the integration icon: yellow circle + white robot vacuum silhouette."""
import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
OUT = Path(__file__).parent.parent / "custom_components" / "karcher" / "icon.png"

YELLOW = (255, 210, 0)   # Kärcher brand yellow
WHITE  = (255, 255, 255)
SHADOW = (200, 160, 0)   # slightly darker for depth


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # ── Background circle ────────────────────────────────────────────────────
    pad = 20
    d.ellipse([pad, pad, SIZE - pad, SIZE - pad], fill=YELLOW)

    # ── Robot vacuum body (rounded rectangle, centred, lower half) ──────────
    # Main disc body
    bx, by = SIZE // 2, SIZE // 2 + 30   # body centre
    br = 155                              # body radius
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=WHITE)

    # Flat edge on top (the "front" bumper side)
    bumper_h = 28
    d.rectangle([bx - br, by - br, bx + br, by - br + bumper_h], fill=WHITE)

    # ── Bumper strip (slightly darker grey) ──────────────────────────────────
    GREY = (230, 230, 230)
    bump_pad = 12
    d.ellipse(
        [bx - br + bump_pad, by - br + bump_pad,
         bx + br - bump_pad, by - br + bump_pad + 48],
        fill=GREY,
    )

    # ── Top sensor dome ──────────────────────────────────────────────────────
    DARK = (180, 180, 180)
    dome_r = 38
    d.ellipse(
        [bx - dome_r, by - 60 - dome_r,
         bx + dome_r, by - 60 + dome_r],
        fill=DARK,
    )
    # small highlight on dome
    d.ellipse(
        [bx - 14, by - 60 - 22,
         bx + 14, by - 60 + 8],
        fill=YELLOW,
    )

    # ── Two wheels ───────────────────────────────────────────────────────────
    wheel_w, wheel_h = 32, 70
    wheel_y = by + 60
    for wx in [bx - br + 18, bx + br - 18 - wheel_w]:
        d.rectangle([wx, wheel_y - wheel_h // 2,
                     wx + wheel_w, wheel_y + wheel_h // 2], fill=DARK)

    # ── Small front caster wheel ─────────────────────────────────────────────
    cw = 22
    d.ellipse([bx - cw // 2, by + br - 30,
               bx + cw // 2, by + br - 30 + cw], fill=DARK)

    return img


if __name__ == "__main__":
    icon = draw_icon()
    icon.save(OUT, "PNG")
    print(f"Icon saved to {OUT}  ({SIZE}×{SIZE})")
