"""单场预测分享海报（Pillow 生成 PNG）。

中文需 CJK 字体：按常见路径探测；找不到则回退英文队名 + Pillow 自带字体，
保证任何环境都能出图（服务器无 CJK 字体时显示英文）。
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

_CJK_FONTS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
_LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _cjk_path() -> str | None:
    import os
    for p in _CJK_FONTS:
        if os.path.exists(p):
            return p
    return None


def _font(size: int, path: str | None):
    try:
        if path:
            return ImageFont.truetype(path, size)
        return ImageFont.truetype(_LATIN, size)
    except Exception:
        return ImageFont.load_default()


def _center(draw, cx, y, text, font, fill):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (r - l) / 2, y), text, font=font, fill=fill)


def match_poster_png(home: str, away: str, probs: dict, upset: dict | None = None,
                     home_rank=None, away_rank=None, result: str | None = None,
                     subtitle: str = "") -> bytes:
    """生成单场预测海报 PNG（bytes）。home/away 已是展示名（中文或英文）。"""
    W, H = 1000, 560
    bg, card, teal, amber, muted, white = (14, 20, 30), (27, 33, 48), (20, 184, 166), (245, 158, 11), (154, 167, 182), (241, 245, 249)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    cjk = _cjk_path()
    f_kick = _font(22, cjk); f_team = _font(58, cjk); f_small = _font(26, cjk)
    f_big = _font(96, cjk); f_tiny = _font(20, cjk)

    d.rounded_rectangle([24, 24, W - 24, H - 24], radius=24, fill=card, outline=(44, 52, 66), width=2)
    _center(d, W / 2, 48, "2026 FIFA WORLD CUP · AI 预测", f_kick, amber)
    if subtitle:
        _center(d, W / 2, 84, subtitle, f_tiny, muted)

    # 队名
    d.text((70, 150), home, font=f_team, fill=white)
    rt = away
    rb = d.textbbox((0, 0), rt, font=f_team)
    d.text((W - 70 - (rb[2] - rb[0]), 150), rt, font=f_team, fill=white)
    _center(d, W / 2, 175, "VS", f_small, muted)
    if home_rank:
        d.text((70, 224), f"FIFA #{home_rank}", font=f_tiny, fill=muted)
    if away_rank:
        s = f"FIFA #{away_rank}"
        sb = d.textbbox((0, 0), s, font=f_tiny)
        d.text((W - 70 - (sb[2] - sb[0]), 224), s, font=f_tiny, fill=muted)

    # 比分或胜平负
    if result:
        _center(d, W / 2, 280, result, f_big, teal)
    else:
        ph, pd, pa = probs.get("home", 0), probs.get("draw", 0), probs.get("away", 0)
        bx0, bx1, by, bh = 70, W - 70, 320, 34
        wtot = bx1 - bx0
        x = bx0
        for frac, col in ((ph, teal), (pd, muted), (pa, (37, 99, 235))):
            w = wtot * frac
            d.rectangle([x, by, x + w, by + bh], fill=col)
            x += w
        _center(d, W / 2, by + bh + 14, f"胜 {ph:.0%}    平 {pd:.0%}    负 {pa:.0%}", f_small, white)

    if upset:
        _center(d, W / 2, 430, f"爆冷指数 {upset.get('index','-')}/100 · {upset.get('level','')}", f_small, amber)
    _center(d, W / 2, H - 66, "模型概率仅供参考 · 非投注建议", f_tiny, muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
