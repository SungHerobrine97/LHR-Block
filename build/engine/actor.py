"""玩家小人：重力、行走、跳跃、自动跨台阶。"""
from __future__ import annotations

import math

from . import settings as S
from .stage import Stage, touching

W = 0.78          # 碰撞盒宽（格）
H = 0.94          # 碰撞盒高（格）
EPS = 1e-4


class Actor:
    def __init__(self, stage: Stage, col: int = 0, row: int = 0, cfg=None):
        self.stage = stage
        self.cfg = cfg or {}
        self.x = float(col) + (1 - W) / 2
        self.y = float(row) + (1 - H)
        self.vx = 0.0
        self.vy = 0.0
        self.grounded = False
        self.facing = 1
        self.alive = True
        self.jump_latch = False
        self.highest_row = row
        self.walk_phase = 0.0

    # -------------------------------------------------- 位置
    @property
    def col(self) -> int:
        return math.floor(self.x + W / 2)

    @property
    def row(self) -> int:
        """头顶所在行，用于胜负判定。"""
        return math.floor(self.y + H / 2)

    @property
    def top_row(self) -> int:
        return math.floor(self.y + 1e-3)

    def tiles(self):
        c0 = math.floor(self.x + 1e-6)
        c1 = math.floor(self.x + W - 1e-6)
        r0 = math.floor(self.y + 1e-6)
        r1 = math.floor(self.y + H - 1e-6)
        out = []
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                out.append((c, r))
        return out

    def reset(self, col: int, row: int) -> None:
        self.x = float(col) + (1 - W) / 2
        self.y = float(row) + (1 - H)
        self.vx = self.vy = 0.0
        self.grounded = False
        self.alive = True
        self.highest_row = row

    def snap_to_free(self, col: int, row: int) -> None:
        """把小人放到某格并保证不与实心重叠（向上寻找空位）。"""
        r = row
        for _ in range(self.stage.h + 2):
            x = float(col) + (1 - W) / 2
            y = float(r) + (1 - H)
            if not touching(self.stage, x, y, W, H):
                self.x, self.y = x, y
                self.vx = self.vy = 0.0
                self.highest_row = r
                return
            r -= 1
        self.x = float(col) + (1 - W) / 2
        self.y = float(row) + (1 - H)

    # -------------------------------------------------- 物理
    def update(self, dt: float, left: bool, right: bool, jump: bool,
               frozen: bool = False) -> None:
        cfg = self.cfg
        speed = float(cfg.get("move_speed", 6.2))
        gravity = float(cfg.get("gravity", 34.0))
        jump_h = float(cfg.get("jump_height", 2.15))
        climb = int(cfg.get("climb", 1))
        max_fall = float(cfg.get("max_fall", 24.0))
        air_ctrl = float(cfg.get("air_control", 1.0))

        if frozen:
            left = right = jump = False

        target = 0.0
        if left:
            target -= speed
        if right:
            target += speed
        if left or right:
            self.facing = -1 if left and not right else 1

        accel = speed * (14.0 if self.grounded else 14.0 * air_ctrl)
        self.vx = S.approach(self.vx, target, max(accel, 1.0) * dt)

        dx = self.vx * dt
        if dx:
            self._move_x(dx, climb)

        if jump and self.grounded and not self.jump_latch:
            self.vy = -math.sqrt(2.0 * gravity * jump_h)
            self.grounded = False
        self.jump_latch = jump

        self.vy = min(self.vy + gravity * dt, max_fall)
        self._move_y(self.vy * dt)

        if not self.grounded and self.vy > 0:
            # 站地面上时标记 grounded
            if touching(self.stage, self.x, self.y + 0.04, W, H):
                self.grounded = True

        if abs(self.vx) > 0.2 and self.grounded:
            self.walk_phase += dt * abs(self.vx) * 2.2
        elif self.grounded:
            self.walk_phase = 0.0

        self.highest_row = min(self.highest_row, self.top_row)
        # 防止卡进实心（例如被方块压住）
        if touching(self.stage, self.x, self.y, W, H):
            self._push_out()

    def _move_x(self, dx: float, climb: int) -> None:
        nx = self.x + dx
        if not touching(self.stage, nx, self.y, W, H):
            self.x = nx
            return
        # 自动跨台阶（climb 格以内）
        if climb > 0 and self.vy <= 0.001:
            for k in range(1, climb + 1):
                ny = self.y - k
                if touching(self.stage, nx, ny, W, H):
                    continue
                # 抬上去后要踩得到东西
                if touching(self.stage, nx, ny + 0.08, W, H) or self.grounded:
                    self.x, self.y = nx, ny
                    if self.vy < 0:
                        self.vy = 0.0
                    return
        # 撞墙：贴到墙边
        if dx > 0:
            row = math.floor(self.y + H / 2)
            c = int(math.floor(nx + W))
            self.x = min(self.x, c - W - EPS)
        else:
            c = int(math.floor(nx))
            self.x = max(self.x, c + 1 + EPS)
        self.vx = 0.0

    def _move_y(self, dy: float) -> None:
        ny = self.y + dy
        if dy > 0:
            if touching(self.stage, self.x, ny, W, H):
                row = math.floor(ny + H)
                self.y = row - H
                self.vy = 0.0
                self.grounded = True
            else:
                self.y = ny
                self.grounded = False
        elif dy < 0:
            if touching(self.stage, self.x, ny, W, H):
                row = math.floor(ny)
                self.y = row + 1 + EPS
                self.vy = 0.0
            else:
                self.y = ny
                self.grounded = False

    def _push_out(self) -> None:
        """被埋时向上脱困；脱不了就交给上层判定为「被困」。"""
        for k in range(1, 7):
            if not touching(self.stage, self.x, self.y - k, W, H):
                self.y -= k
                self.vy = 0.0
                return

    def is_buried(self) -> bool:
        """四周（含边界与墙壁）全被堵死。"""
        x, y = self.x, self.y
        return (
            touching(self.stage, x - 0.06, y, W, H)
            and touching(self.stage, x + 0.06, y, W, H)
            and touching(self.stage, x, y - 0.06, W, H)
            and touching(self.stage, x, y + 0.06, W, H)
        )
