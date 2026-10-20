"""全局常量、主题、字体与路径工具。"""
from __future__ import annotations

import os

import pygame

APP_TITLE = "登塔者 · Climb Tower"
APP_VERSION = "1.0.0"

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)                 # build/
PROJECT_ROOT = os.path.dirname(ROOT)          # 工作区根目录

CONTENT_DIR = os.path.join(ROOT, "content")
LEVELS_DIR = os.path.join(CONTENT_DIR, "levels")
STORIES_DIR = os.path.join(CONTENT_DIR, "stories")
PRESETS_DIR = os.path.join(CONTENT_DIR, "presets")
AUDIO_DIR = os.path.join(CONTENT_DIR, "audio")
SAVES_DIR = os.path.join(ROOT, "saves")
SAVE_FILE = os.path.join(SAVES_DIR, "save.json")


def ensure_dirs() -> None:
    for d in (CONTENT_DIR, LEVELS_DIR, STORIES_DIR, PRESETS_DIR, AUDIO_DIR, SAVES_DIR):
        os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------- 主题
BG = (12, 14, 22)
BG2 = (17, 20, 30)
PANEL = (24, 28, 41)
PANEL2 = (33, 38, 54)
PANEL3 = (46, 53, 74)
LINE = (58, 67, 94)
LINE2 = (86, 97, 128)

TEXT = (228, 234, 246)
DIM = (148, 158, 183)
DIM2 = (104, 114, 140)

ACCENT = (96, 178, 255)
ACCENT2 = (48, 106, 186)
GOOD = (86, 219, 148)
BAD = (255, 104, 118)
WARN = (255, 198, 92)
GOLD = (255, 214, 120)
PURPLE = (188, 132, 252)
CYAN = (104, 220, 235)

BLOCK_COLORS = {
    1: (94, 196, 244),    # I
    2: (248, 206, 84),    # O
    3: (190, 132, 252),   # T
    4: (104, 222, 146),   # S
    5: (255, 116, 132),   # Z
    6: (92, 126, 246),    # J
    7: (255, 164, 80),    # L
}
WALL_COLOR = (74, 82, 106)


def blend(color, k: float):
    """k>1 变亮，k<1 变暗。"""
    r, g, b = color
    return (
        max(0, min(255, int(r * k))),
        max(0, min(255, int(g * k))),
        max(0, min(255, int(b * k))),
    )


def mix(a, b, t: float):
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


# ---------------------------------------------------------------- 字体
_FONT_NAMES = ("Microsoft YaHei", "SimHei", "DengXian", "Noto Sans SC",
               "Source Han Sans SC", "Arial")
_cache: dict = {}
_face_cache: dict = {}


def _face(bold: bool):
    if bold in _face_cache:
        return _face_cache[bold]
    path = None
    for name in _FONT_NAMES:
        found = pygame.font.match_font(name, bold=bold)
        if found:
            path = found
            break
    _face_cache[bold] = path
    return path


def font(size: int, bold: bool = False) -> pygame.font.Font:
    key = (size, bold)
    f = _cache.get(key)
    if f is not None:
        return f
    path = _face(bold)
    f = pygame.font.Font(path, size) if path else pygame.font.Font(None, size)
    _cache[key] = f
    return f


def text(s, size=16, color=TEXT, bold=False) -> pygame.Surface:
    return font(size, bold).render(str(s), True, color)


def wrap(s: str, fnt: pygame.font.Font, max_w: int) -> list:
    """中英混排按字符宽度换行，支持 \n 强制换行。"""
    out = []
    for para in str(s).split("\n"):
        if para == "":
            out.append("")
            continue
        cur = ""
        for ch in para:
            nxt = cur + ch
            if fnt.size(nxt)[0] > max_w and cur:
                out.append(cur)
                cur = ch
            else:
                cur = nxt
        out.append(cur)
    return out


def draw_text(surf, s, pos, size=16, color=TEXT, bold=False, anchor="topleft"):
    """anchor: topleft / center / midtop / midbottom / midleft / midright / topright。

    center / midleft / midright 会做垂直居中；midbottom 让 y 表示底边。
    """
    fnt = font(size, bold)
    x, y = pos
    lines = wrap(s, fnt, 1 << 30)
    heights = [fnt.size(l)[1] + 2 for l in lines]
    total = sum(heights)
    if anchor in ("center", "midleft", "midright"):
        y -= total // 2
    elif anchor == "midbottom":
        y -= total
    for l, hh in zip(lines, heights):
        img = fnt.render(l, True, color)
        w = img.get_width()
        if anchor in ("center", "midtop", "midbottom"):
            dx = x - w // 2
        elif anchor in ("midright", "topright", "bottomright"):
            dx = x - w
        else:
            dx = x
        surf.blit(img, (dx, y))
        y += hh
    return y


# ---------------------------------------------------------------- 图形
def round_rect(surface, rect, color, radius=8, width=0, border_color=None):
    r = pygame.Rect(rect)
    if radius > 0:
        pygame.draw.rect(surface, color, r, width, border_radius=radius)
    else:
        pygame.draw.rect(surface, color, r, width)
    if border_color and width == 0:
        pygame.draw.rect(surface, border_color, r, 1, border_radius=radius)


def panel(surface, rect, fill=PANEL, border=LINE, radius=10):
    round_rect(surface, rect, fill, radius)
    if border:
        round_rect(surface, rect, border, radius, 1)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def approach(cur, target, delta):
    if cur < target:
        return min(cur + delta, target)
    if cur > target:
        return max(cur - delta, target)
    return cur
