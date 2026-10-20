"""俄罗斯方块形状定义与旋转。

内置 7 种经典形状，并允许关卡 / 编辑器注册「自定义形状」：
自定义形状以 cells（相对坐标列表）描述，旋转表按同一算法自动生成。
"""
from __future__ import annotations

import random
from typing import Dict, List, Tuple

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

# ---------------------------------------------------------------- 自定义形状
# kind -> {"cells": [...], "color": int, "name": str}
CUSTOM_SHAPES: Dict[str, dict] = {}
_ROT_CACHE: Dict[str, List[List[Cell]]] = {}

MAX_GRID = 6          # 形状网格边长上限（编辑器 6×6）


def _normalize(cells: List[Cell]) -> List[Cell]:
    cells = [(int(x), int(y)) for x, y in cells]
    if not cells:
        return []
    xmin = min(x for x, _ in cells)
    ymin = min(y for _, y in cells)
    return sorted(((x - xmin, y - ymin) for x, y in cells))


def _rotate(cells: List[Cell]) -> List[Cell]:
    """顺时针旋转 90°（屏幕坐标 y 向下）。"""
    ymax = max(y for _, y in cells)
    return [(ymax - y, x) for (x, y) in cells]


def rotations_from_cells(cells: List[Cell]) -> List[List[Cell]]:
    """由任意格子集合生成全部不同朝向（顺时针 90°，去重后归一化）。"""
    rots: List[List[Cell]] = []
    cur = _normalize(list(cells))
    if not cur:
        return [[(0, 0)]]
    seen = set()
    for _ in range(4):
        key = tuple(cur)
        if key not in seen:
            seen.add(key)
            rots.append(cur)
        cur = _normalize(_rotate(cur))
    return rots


def build_rotations(kind: str) -> List[List[Cell]]:
    """兼容旧接口：按形状名取旋转表。"""
    return rotations_of(kind)


# ---------------------------------------------------------------- 注册表
def register_shape(kind: str, cells, color: int = 1, name: str | None = None) -> bool:
    """注册（或覆盖）一个形状，内置名字也可以被覆盖。"""
    kind = str(kind).strip()
    if not kind:
        return False
    norm = _normalize(list(cells))
    if not norm:
        return False
    if max(max(x, y) for x, y in norm) >= MAX_GRID:
        return False
    CUSTOM_SHAPES[kind] = {"cells": norm, "color": int(color),
                           "name": str(name or kind)}
    _ROT_CACHE.pop(kind, None)
    return True


def unregister_shape(kind: str) -> None:
    CUSTOM_SHAPES.pop(str(kind), None)
    _ROT_CACHE.pop(str(kind), None)


def clear_custom_shapes() -> None:
    CUSTOM_SHAPES.clear()
    _ROT_CACHE.clear()


def custom_kinds() -> List[str]:
    return list(CUSTOM_SHAPES.keys())


def is_custom(kind: str) -> bool:
    return str(kind) in CUSTOM_SHAPES


def known_kinds() -> List[str]:
    """内置形状 + 已注册的自定义形状。"""
    out = list(ALL_KINDS)
    for k in CUSTOM_SHAPES:
        if k not in out:
            out.append(k)
    return out


def is_known(kind) -> bool:
    k = str(kind)
    return k in SHAPE_DEFS or k in CUSTOM_SHAPES


def shape_info(kind: str) -> dict:
    return CUSTOM_SHAPES.get(str(kind)) or SHAPE_DEFS.get(str(kind)) or SHAPE_DEFS["O"]


def rotations_of(kind: str) -> List[List[Cell]]:
    k = str(kind)
    cached = _ROT_CACHE.get(k)
    if cached is None:
        cached = rotations_from_cells(shape_info(k)["cells"])
        _ROT_CACHE[k] = cached
    return cached


def color_of(kind: str) -> int:
    return int(shape_info(kind).get("color", 1))


def name_of(kind: str) -> str:
    info = CUSTOM_SHAPES.get(str(kind))
    if info:
        return info.get("name") or str(kind)
    return str(kind)


def size_of(kind: str) -> Tuple[int, int]:
    cells = shape_info(kind)["cells"]
    return max(x for x, _ in cells) + 1, max(y for _, y in cells) + 1


class Piece:
    """一个正在舞台上的方块。

    row 为整数（逐格下落），渲染时用 fall_t / interval 做插值。
    支持舞台内同时存在多个方块：每块自带阶段（aim / fall）与自己的倒计时。
    """

    __slots__ = ("kind", "rot", "col", "row", "fall_t", "interval", "landed",
                 "phase", "aim_t", "aim_total", "aim_col", "instant")

    def __init__(self, kind: str, rot: int = 0, col: int = 0, row: int = -4):
        self.kind = str(kind) if is_known(kind) else "O"
        self.rot = int(rot) % len(rotations_of(self.kind))
        self.col = col
        self.row = row
        self.fall_t = 0.0
        self.interval = 1.0
        self.landed = False
        self.phase = "aim"          # aim | fall
        self.aim_t = 0.0
        self.aim_total = 1.0
        self.aim_col = float(col)
        self.instant = False        # 剧本投放：跳过倒计时直接下落

    @property
    def aiming(self) -> bool:
        return self.phase == "aim"

    @property
    def color(self) -> int:
        return color_of(self.kind)

    @property
    def rotations(self) -> List[List[Cell]]:
        return rotations_of(self.kind)

    @property
    def shape(self) -> List[Cell]:
        rots = self.rotations
        return rots[self.rot % len(rots)]

    @property
    def width(self) -> int:
        return max(x for x, _ in self.shape) + 1

    @property
    def height(self) -> int:
        return max(y for _, y in self.shape) + 1

    def cells(self, col=None, row=None, rot=None) -> List[Cell]:
        rots = self.rotations
        base = rots[self.rot if rot is None else int(rot) % len(rots)]
        c0 = self.col if col is None else col
        r0 = self.row if row is None else row
        return [(c0 + x, r0 + y) for (x, y) in base]

    def rotate(self, delta=1) -> None:
        self.rot = (self.rot + int(delta)) % len(self.rotations)

    def clone(self) -> "Piece":
        p = Piece(self.kind, self.rot, self.col, self.row)
        p.interval = self.interval
        return p


class Bag:
    """7-bag 随机器，避免长时间不出某个形状。"""

    def __init__(self, pool=None, rng: random.Random | None = None):
        pool = [str(k) for k in (pool or ALL_KINDS) if is_known(k)]
        self.pool = pool or list(ALL_KINDS)
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
