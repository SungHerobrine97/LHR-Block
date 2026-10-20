"""俄罗斯方块形状定义与旋转。"""
from __future__ import annotations

import random
from typing import List, Tuple

Cell = Tuple[int, int]

SHAPE_DEFS = {
    "I": {"cells": [(0, 0), (1, 0), (2, 0), (3, 0)], "color": 1},
    "O": {"cells": [(0, 0), (1, 0), (0, 1), (1, 1)], "color": 2},
    "T": {"cells": [(1, 0), (0, 1), (1, 1), (2, 1)], "color": 3},
    "S": {"cells": [(1, 0), (2, 0), (0, 1), (1, 1)], "color": 4},
    "Z": {"cells": [(0, 0), (1, 0), (1, 1), (2, 1)], "color": 5},
    "J": {"cells": [(0, 0), (0, 1), (1, 1), (2, 1)], "color": 6},
    "L": {"cells": [(2, 0), (0, 1), (1, 1), (2, 1)], "color": 7},
}

ALL_KINDS = tuple(SHAPE_DEFS.keys())


def _normalize(cells: List[Cell]) -> List[Cell]:
    xmin = min(x for x, _ in cells)
    ymin = min(y for _, y in cells)
    return sorted(((x - xmin, y - ymin) for x, y in cells))


def _rotate(cells: List[Cell]) -> List[Cell]:
    """顺时针旋转 90°（屏幕坐标 y 向下）。"""
    ymax = max(y for _, y in cells)
    return [(ymax - y, x) for (x, y) in cells]


def build_rotations(kind: str) -> List[List[Cell]]:
    rots = []
    cur = _normalize(SHAPE_DEFS[kind]["cells"])
    seen = set()
    for _ in range(4):
        key = tuple(cur)
        if key not in seen:
            seen.add(key)
            rots.append(cur)
        cur = _normalize(_rotate(cur))
    return rots


ROTATIONS = {k: build_rotations(k) for k in ALL_KINDS}


class Piece:
    """一个正在舞台上的方块。

    row 为整数（逐格下落），渲染时用 fall_t / interval 做插值。
    """

    __slots__ = ("kind", "rot", "col", "row", "fall_t", "interval", "landed")

    def __init__(self, kind: str, rot: int = 0, col: int = 0, row: int = -4):
        self.kind = kind
        self.rot = rot % len(ROTATIONS[kind])
        self.col = col
        self.row = row
        self.fall_t = 0.0
        self.interval = 1.0
        self.landed = False

    @property
    def color(self) -> int:
        return SHAPE_DEFS[self.kind]["color"]

    @property
    def shape(self) -> List[Cell]:
        return ROTATIONS[self.kind][self.rot]

    @property
    def width(self) -> int:
        return max(x for x, _ in self.shape) + 1

    @property
    def height(self) -> int:
        return max(y for _, y in self.shape) + 1

    def cells(self, col=None, row=None, rot=None) -> List[Cell]:
        base = ROTATIONS[self.kind][self.rot if rot is None else rot % len(ROTATIONS[self.kind])]
        c0 = self.col if col is None else col
        r0 = self.row if row is None else row
        return [(c0 + x, r0 + y) for (x, y) in base]

    def rotate(self, delta=1) -> None:
        self.rot = (self.rot + delta) % len(ROTATIONS[self.kind])

    def clone(self) -> "Piece":
        p = Piece(self.kind, self.rot, self.col, self.row)
        p.interval = self.interval
        return p


class Bag:
    """7-bag 随机器，避免长时间不出某个形状。"""

    def __init__(self, pool=None, rng: random.Random | None = None):
        self.pool = list(pool or ALL_KINDS)
        self.rng = rng or random.Random()
        self._queue: List[str] = []

    def next(self) -> str:
        if not self._queue:
            self._queue = list(self.pool)
            self.rng.shuffle(self._queue)
        return self._queue.pop(0)

    def peek(self) -> str:
        if not self._queue:
            self._queue = list(self.pool)
            self.rng.shuffle(self._queue)
        return self._queue[0]
