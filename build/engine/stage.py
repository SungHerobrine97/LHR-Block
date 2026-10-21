"""舞台：网格、地形、碰撞查询。"""
from __future__ import annotations

import math
from typing import List, Tuple

from .pieces import Piece

EMPTY = 0
WALL = -1

# 地形字符
CH_EMPTY = "."
CH_WALL = "#"


class Stage:
    def __init__(self, w: int = 10, h: int = 20):
        self.w = max(3, int(w))
        self.h = max(4, int(h))
        self.grid: List[List[int]] = [[EMPTY] * self.w for _ in range(self.h)]

    # -------------------------------------------------- 基础
    def clear(self) -> None:
        self.grid = [[EMPTY] * self.w for _ in range(self.h)]

    def resize(self, w: int, h: int) -> None:
        old = self.grid
        ow, oh = self.w, self.h
        self.w = max(3, int(w))
        self.h = max(4, int(h))
        self.grid = [[EMPTY] * self.w for _ in range(self.h)]
        for r in range(min(oh, self.h)):
            for c in range(min(ow, self.w)):
                self.grid[r][c] = old[r][c]

    def in_bounds(self, c: int, r: int) -> bool:
        return 0 <= c < self.w and 0 <= r < self.h

    def get(self, c: int, r: int) -> int:
        if not self.in_bounds(c, r):
            return WALL
        return self.grid[r][c]

    def set(self, c: int, r: int, v: int) -> None:
        if self.in_bounds(c, r):
            self.grid[r][c] = v

    def is_solid(self, c: int, r: int) -> bool:
        """越界左右下均为实心（边界算作墙）；舞台顶部之上为空，允许探头。"""
        if c < 0 or c >= self.w:
            return True
        if r >= self.h:
            return True
        if r < 0:
            return False
        return self.grid[r][c] != EMPTY

    # -------------------------------------------------- 方块
    def fits(self, piece: Piece, col=None, row=None, rot=None) -> bool:
        for c, r in piece.cells(col, row, rot):
            if r >= self.h:
                return False
            if c < 0 or c >= self.w:
                return False
            if r >= 0 and self.grid[r][c] != EMPTY:
                return False
        return True

    def lock(self, piece: Piece) -> List[Tuple[int, int]]:
        placed = []
        for c, r in piece.cells():
            if r < 0:
                continue
            if self.in_bounds(c, r):
                self.grid[r][c] = piece.color
                placed.append((c, r))
        return placed

    def drop_row(self, piece: Piece, start_row: int) -> int:
        """给定列与朝向，返回能落到的最深合法 row。"""
        row = start_row
        while self.fits(piece, None, row + 1):
            row += 1
        return row

    def full_rows(self) -> List[int]:
        """被实心格填满的行（含墙的行不算，避免把关卡地形消掉）。"""
        out = []
        for r in range(self.h):
            row = self.grid[r]
            if any(v == WALL for v in row):
                continue
            if all(v != EMPTY for v in row):
                out.append(r)
        return out

    def clear_rows(self, rows) -> None:
        """删除指定行，其上方整体下落一格，顶部补空行。"""
        drop = set(int(r) for r in (rows or []))
        if not drop:
            return
        keep = [list(self.grid[r]) for r in range(self.h) if r not in drop]
        while len(keep) < self.h:
            keep.insert(0, [EMPTY] * self.w)
        self.grid = keep

    def highest_solid_row(self) -> int:
        for r in range(self.h):
            if any(v != EMPTY for v in self.grid[r]):
                return r
        return self.h

    # -------------------------------------------------- 地形读写
    def to_rows(self) -> List[str]:
        out = []
        for r in range(self.h):
            line = []
            for c in range(self.w):
                v = self.grid[r][c]
                line.append(CH_EMPTY if v == EMPTY else CH_WALL if v == WALL else str(v))
            out.append("".join(line))
        return out

    def load_rows(self, rows) -> None:
        self.clear()
        for r, line in enumerate(rows):
            if r >= self.h:
                break
            for c, ch in enumerate(line):
                if c >= self.w:
                    break
                if ch == CH_EMPTY or ch in " 0":
                    self.grid[r][c] = EMPTY
                elif ch == CH_WALL or ch == "*":
                    self.grid[r][c] = WALL
                elif ch.isdigit():
                    self.grid[r][c] = int(ch) if 1 <= int(ch) <= 7 else EMPTY


def tiles_of(x: float, y: float, w: float, h: float):
    """返回 AABB 覆盖的所有格子坐标。"""
    c0 = math.floor(x + 1e-6)
    c1 = math.floor(x + w - 1e-6)
    r0 = math.floor(y + 1e-6)
    r1 = math.floor(y + h - 1e-6)
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            yield c, r


def touching(stage: Stage, x: float, y: float, w: float, h: float) -> bool:
    """AABB 是否与实心格重叠。"""
    for c, r in tiles_of(x, y, w, h):
        if stage.is_solid(c, r):
            return True
    return False
