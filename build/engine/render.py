"""舞台、方块、小人的绘制。"""
from __future__ import annotations

import math

import pygame

from . import settings as S
from .actor import H as AH
from .actor import W as AW
from .pieces import color_of, rotations_of
from .stage import EMPTY, WALL

TOP_ROWS = 3          # 舞台上方预留给「待落方块」的空间（单位：行）


def make_view(area: pygame.Rect, cols: int, rows: int,
              max_cell: int = 34, min_cell: int = 9):
    total_rows = rows + TOP_ROWS
    cell = int(min(area.w // max(cols, 1), area.h // max(total_rows, 1)))
    cell = max(min_cell, min(cell, max_cell))
    w = cell * cols
    h = cell * rows
    x = area.x + (area.w - w) // 2
    y = area.y + (area.h - h - cell * TOP_ROWS) // 2 + cell * TOP_ROWS
    return pygame.Rect(x, y, w, h), cell


def _tile_rect(view, cell, c, r):
    return pygame.Rect(view.x + c * cell, view.y + r * cell, cell, cell)


# ---------------------------------------------------------------- 背景
def draw_stage_bg(surf, core, view, cell, t):
    pad = cell
    frame = pygame.Rect(view.x - pad // 3, view.y - cell * TOP_ROWS - pad // 3,
                        view.w + pad * 2 // 3, view.h + cell * TOP_ROWS + pad * 2 // 3)
    S.round_rect(surf, frame, S.BG2, 12)
    S.round_rect(surf, frame, S.LINE, 12, 1)
    sky = pygame.Rect(view.x, view.y - cell * TOP_ROWS, view.w, cell * TOP_ROWS)
    S.round_rect(surf, sky, (16, 19, 29), 8)

    # 网格
    for c in range(core.stage.w + 1):
        x = view.x + c * cell
        pygame.draw.line(surf, (28, 33, 47), (x, view.y), (x, view.y + view.h))
    for r in range(core.stage.h + 1):
        y = view.y + r * cell
        pygame.draw.line(surf, (28, 33, 47), (view.x, y), (view.x + view.w, y))

    # 目标线
    g = core.level["goal"]
    if g.get("type", "reach_row") == "reach_row":
        grow = int(g.get("row", 0))
        if 0 <= grow <= core.stage.h:
            y = view.y + grow * cell
            for x in range(view.x, view.x + view.w, max(6, cell // 3)):
                pygame.draw.line(surf, S.mix(S.GOLD, S.BG2, 0.35),
                                 (x, y), (x + max(3, cell // 5), y), 2)
            lab = S.text("目标", 11, S.GOLD, True)
            surf.blit(lab, (view.x + view.w - lab.get_width() - 2, y - lab.get_height() - 1))


# ---------------------------------------------------------------- 方块
def draw_block(surf, rect, color_id, alpha=255, ghost=False):
    base = S.BLOCK_COLORS.get(color_id, (120, 130, 150))
    if ghost:
        ov = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        pygame.draw.rect(ov, (*base, 70), pygame.Rect(0, 0, rect.w, rect.h),
                         border_radius=max(2, rect.w // 8))
        pygame.draw.rect(ov, (*base, 150), pygame.Rect(0, 0, rect.w, rect.h), 1,
                         border_radius=max(2, rect.w // 8))
        surf.blit(ov, rect.topleft)
        return
    r = max(2, rect.w // 8)
    S.round_rect(surf, rect, base, r)
    hi = S.blend(base, 1.45)
    lo = S.blend(base, 0.62)
    inner = rect.inflate(-max(2, rect.w // 7), -max(2, rect.w // 7))
    top = pygame.Rect(inner.x, inner.y, inner.w, max(2, inner.h // 5))
    S.round_rect(surf, top, hi, max(1, r // 2))
    bot = pygame.Rect(inner.x, inner.bottom - max(2, inner.h // 6), inner.w,
                      max(2, inner.h // 6))
    S.round_rect(surf, bot, lo, max(1, r // 2))


def draw_wall(surf, rect):
    S.round_rect(surf, rect, S.WALL_COLOR, max(2, rect.w // 9))
    pygame.draw.line(surf, S.blend(S.WALL_COLOR, 1.35), rect.topleft, rect.bottomright, 2)
    pygame.draw.line(surf, S.blend(S.WALL_COLOR, 0.7),
                     (rect.right, rect.top), (rect.left, rect.bottom), 2)


def draw_stage_blocks(surf, core, view, cell, t):
    st = core.stage
    for r in range(st.h):
        for c in range(st.w):
            v = st.grid[r][c]
            if v == EMPTY:
                continue
            rect = _tile_rect(view, cell, c, r)
            if v == WALL:
                draw_wall(surf, rect)
            else:
                draw_block(surf, rect, v)


# ---------------------------------------------------------------- 落点预览 / 当前块
def active_pieces(core):
    """舞台上所有正在瞄准 / 下落的方块（兼容只有 piece 的旧对象）。"""
    ps = getattr(core, "pieces", None)
    if ps is None:
        p = getattr(core, "piece", None)
        return [p] if p is not None else []
    return list(ps)


def piece_visual_row(core, p=None):
    p = p if p is not None else getattr(core, "piece", None)
    if p is None:
        return None
    if getattr(p, "phase", "aim") == "fall" and p.interval > 0:
        return p.row - 1 + max(0.0, min(1.0, p.fall_t / p.interval))
    return float(p.row)


def draw_ghost(surf, core, view, cell, t):
    pulse = 0.35 + 0.2 * math.sin(t * 4.5)
    for p in active_pieces(core):
        _draw_ghost_one(surf, core, view, cell, p, pulse)


def _draw_ghost_one(surf, core, view, cell, p, pulse):
    if p is None:
        return
    land = core.stage.drop_row(p, p.row)
    if land < 0:
        return
    for c, r in p.cells(None, land):
        if r < 0:
            continue
        rect = _tile_rect(view, cell, c, r)
        draw_block(surf, rect, p.color, ghost=True)
    # 下落引导光柱
    x0 = view.x + p.col * cell + p.width * cell / 2
    top = view.y + p.row * cell
    bottom = view.y + land * cell
    if bottom > top:
        col = S.BLOCK_COLORS.get(p.color, (200, 200, 200))
        lw = max(1, int(cell * 0.16))
        band = pygame.Surface((lw, int(bottom - top)), pygame.SRCALPHA)
        band.fill((*col, int(50 + 60 * pulse)))
        surf.blit(band, (int(x0 - lw / 2), int(top)))


def draw_piece(surf, core, view, cell, t):
    for p in active_pieces(core):
        _draw_piece_one(surf, core, view, cell, t, p)


def _draw_piece_one(surf, core, view, cell, t, p):
    if p is None:
        return
    vy = piece_visual_row(core, p)
    if vy is None:
        return
    off = (vy - p.row) * cell
    shining = getattr(p, "phase", "aim") == "aim" and \
        getattr(p, "aim_t", 99) < 1.2
    for c, r in p.cells():
        rect = _tile_rect(view, cell, c, r)
        rect.y += int(off)
        if rect.bottom <= view.y - cell * TOP_ROWS:
            continue
        if shining and int(t * 14) % 2 == 0:
            rect.inflate_ip(-2, -2)
            S.round_rect(surf, rect, S.blend(S.BLOCK_COLORS.get(p.color,
                         (200, 200, 200)), 1.6), max(2, rect.w // 8))
        else:
            draw_block(surf, rect, p.color)


def draw_aim_meter(surf, core, view, cell, t):
    p = getattr(core, "aiming", None) or getattr(core, "piece", None)
    if p is None or getattr(p, "phase", "aim") != "aim":
        return
    k = max(0.0, min(1.0, getattr(p, "aim_t", 0.0)
                     / max(getattr(p, "aim_total", 1.0), 0.001)))
    x0 = view.x + p.col * cell
    w = max(cell, p.width * cell)
    y = view.y - int(cell * 0.55)
    S.round_rect(surf, pygame.Rect(x0, y, w, max(4, int(cell * 0.16))), (40, 47, 66),
                 max(2, int(cell * 0.08)))
    remain = S.mix(S.GOOD, S.BAD, 1.0 - k)
    S.round_rect(surf, pygame.Rect(x0, y, int(w * k), max(4, int(cell * 0.16))),
                 remain, max(2, int(cell * 0.08)))
    txt = S.text(f"{getattr(p, 'aim_t', 0.0):.1f}s",
                 max(10, int(cell * 0.42)), remain, True)
    surf.blit(txt, (x0 + w + 6, y - 4))


# ---------------------------------------------------------------- 小人
def draw_actor(surf, core, view, cell, t):
    a = core.actor
    x = view.x + a.x * cell
    y = view.y + a.y * cell
    w = AW * cell
    h = AH * cell
    dead = core.result and core.result["kind"] == "lose"

    # 影子
    shadow = pygame.Rect(x + w * 0.1, y + h * 0.92, w * 0.8, h * 0.12)
    S.round_rect(surf, shadow, (0, 0, 0, 90), int(shadow.h / 2))

    bob = math.sin(a.walk_phase * 3.0) * h * 0.03 if a.grounded else 0.0
    y += bob

    robe = S.mix((86, 200, 240), (60, 130, 220), 0.4) if not dead else (120, 90, 100)
    skin = (250, 220, 190)
    # 身体
    bw, bh = w * 0.74, h * 0.50
    S.round_rect(surf, pygame.Rect(x + (w - bw) / 2, y + h * 0.40, bw, bh), robe,
                 int(bw / 3))
    # 披风 / 围巾
    S.round_rect(surf, pygame.Rect(x + (w - bw) / 2 - w * 0.04, y + h * 0.36,
                                   bw * 1.08, h * 0.10), S.GOLD, int(h * 0.05))
    # 腿
    lw = bw * 0.26
    swing = math.sin(a.walk_phase * 3.4) * bw * 0.18 if abs(a.vx) > 0.3 else 0.0
    for dx, sgn in ((-bw * 0.22, -1), (bw * 0.10, 1)):
        lx = x + w / 2 + dx
        ly = y + h * 0.86
        pygame.draw.line(surf, S.blend(robe, 0.7),
                         (lx, ly - h * 0.12), (lx + swing * sgn, ly), max(2, int(cell * 0.09)))
    # 头
    hr = bw * 0.40
    hx = x + w / 2
    hy = y + h * 0.28
    pygame.draw.circle(surf, skin, (int(hx), int(hy)), int(hr))
    pygame.draw.circle(surf, (60, 60, 80), (int(hx), int(hy)), int(hr), 1)
    # 头发
    pygame.draw.arc(surf, S.blend(S.GOLD, 0.85),
                    pygame.Rect(hx - hr, hy - hr, hr * 2, hr * 2),
                    math.pi * 0.15, math.pi * 0.95, max(2, int(hr * 0.28)))
    # 眼睛
    ex = hx + a.facing * hr * 0.22
    ey = hy + hr * 0.10
    er = max(1, int(hr * 0.16))
    if dead:
        for ox in (-hr * 0.3, hr * 0.3):
            pygame.draw.line(surf, (60, 60, 70),
                             (ex + ox - er, ey - er), (ex + ox + er, ey + er), 2)
            pygame.draw.line(surf, (60, 60, 70),
                             (ex + ox + er, ey - er), (ex + ox - er, ey + er), 2)
    else:
        for ox in (-hr * 0.3, hr * 0.3):
            pygame.draw.circle(surf, (40, 44, 58), (int(ex + ox), int(ey)), er)


def draw_next(surf, core, rect):
    """右上角下一块预览。"""
    S.panel(surf, rect, S.PANEL, S.LINE, 8)
    S.draw_text(surf, "下一块", (rect.x + 10, rect.y + 6), 12, S.DIM)
    kind = core.bag.peek()
    cells = rotations_of(kind)[0]
    color = color_of(kind)
    maxx = max(x for x, _ in cells) + 1
    maxy = max(y for _, y in cells) + 1
    size = min((rect.w - 24) // maxx, (rect.h - 34) // maxy)
    ox = rect.x + (rect.w - size * maxx) // 2
    oy = rect.y + 26 + (rect.h - 30 - size * maxy) // 2
    for c, r in cells:
        draw_block(surf, pygame.Rect(ox + c * size, oy + r * size, size, size), color)
