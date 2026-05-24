"""登录验证码（SVG，无额外依赖）。"""
import random
import secrets

from flask import session

CAPTCHA_SESSION_KEY = "login_captcha_answer"
_CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def issue_captcha() -> str:
    code = "".join(random.choices(_CAPTCHA_CHARS, k=4))
    session[CAPTCHA_SESSION_KEY] = code
    return code


def verify_captcha(user_input: str) -> bool:
    expected = session.pop(CAPTCHA_SESSION_KEY, None)
    if not expected:
        return False
    return secrets.compare_digest(
        (user_input or "").strip().upper(),
        expected.upper(),
    )


def build_captcha_svg(code: str) -> str:
    width, height = 140, 48
    lines = []
    for _ in range(6):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        color = f"#{random.randint(0, 0xFFFFFF):06x}"
        lines.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1" opacity="0.35"/>'
        )

    letters = []
    for index, char in enumerate(code):
        x = 18 + index * 28 + random.randint(-2, 2)
        y = 32 + random.randint(-3, 3)
        rotate = random.randint(-18, 18)
        color = f"#{random.randint(0, 0x666666):06x}"
        letters.append(
            f'<text x="{x}" y="{y}" fill="{color}" font-size="26" font-family="Georgia, serif" '
            f'font-weight="700" transform="rotate({rotate} {x} {y})">{char}</text>'
        )

    dots = []
    for _ in range(18):
        cx, cy = random.randint(0, width), random.randint(0, height)
        dots.append(f'<circle cx="{cx}" cy="{cy}" r="1.2" fill="#999" opacity="0.5"/>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="#fffdf8" rx="8"/>'
        f'{"".join(lines)}{"".join(dots)}{"".join(letters)}'
        f"</svg>"
    )
