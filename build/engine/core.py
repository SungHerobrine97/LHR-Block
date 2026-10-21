"""游戏逻辑核心：舞台、方块生命周期、胜负判定、事件与剧本钩子。

与渲染完全解耦，游戏场景与编辑器试玩都可直接复用。
"""
from __future__ import annotations

import math
import random
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from . import level as L
from .actor import Actor
from .actor import H as AH
from .actor import W as AW
from .audio import resolve_bgm, resolve_sfx
from .pieces import Bag, Piece, is_known, rotations_of
from .save import SaveData
from .scriptvm import Runner, Stmt, split_args
from .stage import EMPTY, WALL, Stage, touching
from .vfx import VFXManager

AIM, FALL, OVER = "aim", "fall", "over"

GOAL_TYPES = ("reach_row", "survive", "lock_count", "clear_lines", "none")


class Core:
    def __init__(self, level: L.Level, save: SaveData | None = None, audio=None):
        self.level = level
        self.save = save
        self.audio = audio
        self.rng = random.Random()
        self.stage = Stage(level.width, level.height)
        cfg = dict(level["player"])
        self.player_cfg = cfg
        self.actor = Actor(self.stage, 0, level.height - 1, cfg)
        self.vfx = VFXManager(level.get("vfx") or [])
        self.bag = Bag(level["blocks"].get("pool") or None, self.rng)

        # 外部回调
        self.on_quit: Optional[callable] = None
        self.on_saved: Optional[callable] = None

        self.runner = Runner(self._handlers())
        self.blocking = False
        self.toast: List[Tuple[str, float, tuple]] = []
        self.hide_dialogue = False

        self.request_quit = False
        self.reset()
        self._start_bgm()
        # 开演：触发 on_start 剧本（若剧本要求等待玩家确认，演出会先暂停）
        self._fire_event("on_start")

    # ================================================== 音频
    def _start_bgm(self) -> None:
        if not self.audio:
            return
        cfg = self.level.get("audio") or {}
        bgm = (cfg.get("bgm") or "").strip()
        vol = float(cfg.get("volume", 100)) / 100.0
        if bgm:
            self.audio.bgm(resolve_bgm(bgm), vol)

    def stop_audio(self) -> None:
        if self.audio:
            self.audio.stop_bgm()

    # ================================================== 生命周期
    def reset(self) -> None:
        # 关卡自带的自定义形状先注册进形状表，方块池 / drop 指令才能引用
        L.register_level_shapes(self.level)
        self.events: List[dict] = self.level.events_list()
        self.stage.clear()
        terrain = self.level.get("terrain") or []
        if terrain:
            self.stage.load_rows(terrain)
        self.bag = Bag(self.level["blocks"].get("pool") or None, self.rng)
        sc = self.player_cfg.get("spawn_col")
        col = int(sc) if isinstance(sc, (int, float)) else self.stage.w // 2
        col = max(0, min(self.stage.w - 1, col))
        self.actor.reset(col, self.stage.h - 1)
        self.actor.snap_to_free(col, self.stage.h - 1)

        self.pieces: List[Piece] = []      # 舞台里同时存在的方块（可多块）
        self.spawn_delay = 0.28
        self.elapsed = 0.0
        self.lock_count = 0
        self.cleared_lines = 0
        self.result: Optional[dict] = None
        self.fired: Set[str] = set()
        self.drop_queue = 0
        self.forced: List[dict] = []      # 剧本指定的下落方块队列
        self.cur_interval = float(
            (self.level["blocks"].get("fall_interval") or 0.30))
        self.best_row = self.actor.top_row
        self.hide_dialogue = False
        self.vfx.set_enabled(self.level.get("vfx") or [])
        self.freeze_timer = 0.0
        self._jump_latch = False
        self._rot_latch = False
        self._drop_latch = False
        self.rotations = 0
        if self.save:
            self.save.record_attempt(self.level.id)

    # ================================================== 主循环
    def update(self, dt: float, inp: Dict[str, bool]) -> None:
        dt = min(dt, 0.05)
        self.vfx.update(dt)
        self._update_toasts(dt)

        if inp.get("advance") and self.runner.active:
            self.runner.advance()

        paused = self.runner.active and self.blocking
        if not paused and not self.result:
            self.elapsed += dt
            self._update_world(dt, inp)
        self.runner.update(dt)

        st = self.runner.current
        if st is not None:
            self.best_row = min(self.best_row, self.actor.top_row)

    # -------------------------------------------------- 多块视图
    @property
    def aiming(self) -> Optional[Piece]:
        """最近生成、正在瞄准的那块：它跟随玩家、可被旋转，倒计时条也显示它。"""
        for p in reversed(self.pieces):
            if getattr(p, "phase", AIM) == AIM:
                return p
        return None

    @property
    def piece(self) -> Optional[Piece]:
        """主控方块：优先正在瞄准的那块，否则取最新开始下落的那块。"""
        a = self.aiming
        if a is not None:
            return a
        return self.pieces[-1] if self.pieces else None

    @property
    def phase(self) -> str:
        p = self.piece
        return getattr(p, "phase", OVER) if p is not None else OVER

    @property
    def aim_t(self) -> float:
        p = self.aiming
        return float(getattr(p, "aim_t", 0.0)) if p is not None else 0.0

    @aim_t.setter
    def aim_t(self, value: float) -> None:
        p = self.aiming or self.piece
        if p is not None:
            p.aim_t = float(value)

    @property
    def aim_total(self) -> float:
        p = self.aiming
        return float(getattr(p, "aim_total", 1.0)) if p is not None else 1.0

    @property
    def aim_col(self) -> float:
        p = self.aiming
        return float(getattr(p, "aim_col", 0.0)) if p is not None else 0.0

    @aim_col.setter
    def aim_col(self, value: float) -> None:
        p = self.aiming or self.piece
        if p is not None:
            p.aim_col = float(value)

    # -------------------------------------------------- 生成节奏
    def concurrent(self) -> int:
        """舞台里允许同时存在的方块数（1 = 经典的一块一块来）。"""
        try:
            n = int(self.level["blocks"].get("concurrent", 1) or 1)
        except (TypeError, ValueError):
            n = 1
        return max(1, min(8, n))

    def spawn_gap(self) -> float:
        """多块模式下，两块之间的最小生成间隔（秒）。"""
        try:
            v = float(self.level["blocks"].get("spawn_gap", 0.35))
        except (TypeError, ValueError):
            v = 0.35
        return max(0.05, min(5.0, v))

    def _update_world(self, dt: float, inp: Dict[str, bool]) -> None:
        if self.result:
            return
        self._check_triggers()

        # 剧本投放的方块优先补位（不受生成间隔限制）
        guard = 0
        while self.drop_queue > 0 and len(self.pieces) < self.concurrent() \
                and guard < 8:
            guard += 1
            self.drop_queue -= 1
            self._spawn(instant=True)
        # 常规节奏：只要还没到上限，冷却结束就补一块
        self.spawn_delay -= dt
        if len(self.pieces) < self.concurrent() and self.spawn_delay <= 0:
            if self._spawn():
                self.spawn_delay = self.spawn_gap()

        # 旋转（上升沿，按住只转一次）：瞄准与下落中皆可，
        # 一旦锁定进舞台就再也不能改变。
        want_rot = bool(inp.get("rotate"))
        if want_rot and not self._rot_latch:
            self._try_rotate(1)
        self._rot_latch = want_rot

        # 立即下落（上升沿）：无视剩余倒计时，让正在瞄准的那块马上开始落
        want_drop = bool(inp.get("drop"))
        if want_drop and not self._drop_latch:
            self._quick_drop()
        self._drop_latch = want_drop

        for p in list(self.pieces):
            if p not in self.pieces:
                continue
            if getattr(p, "phase", AIM) == AIM:
                self._update_aim(p, dt, inp)
            elif p.phase == FALL:
                self._update_fall(p, dt)
            if self.result:
                return

        # 跳跃音效（上升沿触发）
        jump = bool(inp.get("jump"))
        if jump and not self._jump_latch and self.actor.grounded and self.audio:
            self.audio.jump()
        self._jump_latch = jump

        frozen = False
        self.actor.update(dt, inp.get("left", False), inp.get("right", False),
                          jump, frozen)
        self.best_row = min(self.best_row, self.actor.top_row)
        if self.save:
            self.save.record_height(self.level.id, self.best_row)

        self._collide_piece_actor()
        self._check_lose()
        self._check_win()

    # ================================================== 方块
    def _spawn(self, instant: bool = False) -> bool:
        blk = self.level["blocks"]
        # 剧本指定的方块（drop 指令）优先于随机袋
        forced = self.forced.pop(0) if self.forced else None
        kind = None
        if forced and forced.get("kind") and is_known(forced["kind"]):
            kind = str(forced["kind"])
        if kind is None:
            kind = self.bag.next()
        nrot = len(rotations_of(kind))
        rot = 0
        if forced and forced.get("rot") is not None:
            try:
                rot = int(forced["rot"]) % nrot
            except (TypeError, ValueError):
                rot = 0
        elif blk.get("allow_rotation", True):
            rot = self.rng.randrange(nrot)
        p = Piece(kind, rot)
        pw = p.width
        col = max(0, min(self.stage.w - pw, self.actor.col - (pw - 1) // 2))
        if forced and forced.get("col") is not None:
            fc = forced["col"]
            if isinstance(fc, str):
                low = fc.lower()
                if low in ("player", "me", "center", "self"):
                    col = max(0, min(self.stage.w - pw,
                                     self.actor.col - (pw - 1) // 2))
                elif low in ("random", "rnd", "any"):
                    col = self.rng.randrange(0, max(1, self.stage.w - pw + 1))
            else:
                try:
                    col = max(0, min(self.stage.w - pw, int(fc)))
                except (TypeError, ValueError):
                    pass
        p.col = col
        p.row = -p.height
        p.interval = self.fall_interval()
        p.phase = AIM
        p.instant = bool(instant)
        p.aim_col = float(col)
        lo, hi = self._aim_range()
        p.aim_total = self.rng.uniform(lo, hi)
        p.aim_t = p.aim_total
        p.fall_t = 0.0
        if forced and forced.get("quick"):
            # 剧本要求「无视倒计时」：立刻开始落，但保持正常下落速度
            p.aim_t = 0.0
            p.instant = False
        self.pieces.append(p)

        if not self._place_at_spawn(p):
            return False
        self._trigger_events("on_spawn", kind)
        self._trigger_events("on_piece", kind)
        return True

    def _fits_active(self, p: Piece, col=None, row=None, rot=None) -> bool:
        """既不与地形冲突，也不与其它正在舞台上的方块重叠。"""
        if not self.stage.fits(p, col, row, rot):
            return False
        cells = set(p.cells(col, row, rot))
        for q in self.pieces:
            if q is p:
                continue
            if cells & set(q.cells()):
                return False
        return True

    def _place_at_spawn(self, p: Piece) -> bool:
        """首选列放不下时，向两侧寻找最近的可容纳位置；无处可落则按 overflow 设定处理。"""
        if p is None:
            return False
        if self._fits_active(p, None, p.row):
            return True
        found = None
        for d in range(1, self.stage.w):
            for cand in (p.col - d, p.col + d):
                if 0 <= cand <= self.stage.w - p.width and \
                        self._fits_active(p, cand, p.row):
                    found = cand
                    break
            if found is not None:
                break
        if found is not None:
            p.col = found
            p.aim_col = float(found)
            return True
        # 舞台已被塞满
        if p in self.pieces:
            self.pieces.remove(p)
        if self.level["fail"].get("overflow", False):
            self._fail("overflow")
        else:
            self.spawn_delay = 0.9
        return False

    @staticmethod
    def _rots(kind):
        return rotations_of(kind)

    # ================================================== 旋转
    @property
    def can_rotate(self) -> bool:
        """当前方块是否还允许旋转（锁定固化后为 False）。"""
        return (self.result is None and self.piece is not None
                and self.phase != OVER
                and bool(self.level["blocks"].get("player_rotate", True)))

    def _try_rotate(self, delta: int = 1) -> bool:
        """旋转主控方块：底边对齐 + 踢墙（左右 / 上移）找合法落位。

        找不到合法位置就放弃本次旋转，方块保持原样。
        """
        p = self.piece
        if p is None or self.result:
            return False
        if not self.level["blocks"].get("player_rotate", True):
            return False
        rots = self._rots(p.kind)
        if len(rots) <= 1:
            return False                      # O 形块转不出新形状
        nrot = (p.rot + int(delta)) % len(rots)
        if nrot == p.rot:
            return False
        old_h = p.height
        new_h = max(y for _, y in rots[nrot]) + 1
        base_row = p.row + old_h - new_h       # 保持底边不动，避免方块“跳”
        for dr in (0, -1, 1, -2):
            for dc in (0, -1, 1, -2, 2):
                col, row = p.col + dc, base_row + dr
                if self._fits_active(p, col, row, nrot):
                    p.rot = nrot
                    p.col = col
                    p.row = row
                    wmax = max(0, self.stage.w - p.width)
                    p.aim_col = float(max(0, min(wmax, col)))
                    self.rotations += 1
                    if self.audio:
                        self.audio.rotate()
                    # 旋转后若正好罩住小人，等同于被砸中
                    if p.phase == FALL:
                        self._collide_piece_actor()
                    return True
        if self.audio:
            self.audio.play("buzz", 0.35)
        return False

    # ================================================== 立即下落
    @property
    def can_quick_drop(self) -> bool:
        """当前是否有可以被「立即下落」催下去的方块。"""
        return (self.result is None and self.aiming is not None
                and bool(self.level["blocks"].get("quick_drop", True)))

    def _quick_drop(self) -> bool:
        """玩家主动催落：无视剩余倒计时，让正在瞄准的方块立刻开始下落。

        只跳过倒计时，下落速度不变（仍能看清它砸向哪里）。
        """
        p = self.aiming
        if p is None or self.result:
            return False
        if not bool(self.level["blocks"].get("quick_drop", True)):
            return False
        p.aim_t = 0.0
        self._begin_fall(p)
        if self.audio:
            self.audio.play("whoosh", 0.5)
        return True

    def _aim_range(self) -> Tuple[float, float]:
        lo, hi = (self.level["blocks"].get("aim_time") or [2.0, 9.9])[:2]
        lo = float(lo)
        hi = float(hi)
        if hi <= lo:
            hi = lo
        return max(0.4, lo), min(9.9, hi)

    def fall_interval(self) -> float:
        return max(float(self.level["blocks"].get("fall_interval_min", 0.10)),
                   self.cur_interval)

    def _update_aim(self, p: Piece, dt: float, inp: Dict[str, bool]) -> None:
        # 剧本指令 drop 要求的「立即下落」：直接跳过倒计时
        if p.instant:
            self._begin_fall(p)
            return
        blk = self.level["blocks"]
        mode = blk.get("hover", "follow")
        wmax = self.stage.w - p.width
        if p is not self.aiming:
            # 多块模式下，只有最新那块跟随玩家；先出现的块停在原列继续倒计时
            mode = "hold"
        if mode == "manual":
            self._repeat = getattr(self, "_repeat", 0.0)
            self._repeat -= dt
            if self._repeat <= 0:
                step = 0
                if inp.get("pleft"):
                    step = -1
                elif inp.get("pright"):
                    step = 1
                if step:
                    p.aim_col = max(0, min(wmax, p.aim_col + step))
                    self._repeat = 0.10
        elif mode in ("random", "hold"):
            pass  # 生成时已随机 / 保持在原来的列
        else:  # follow —— 跟随玩家选择的下落位置
            target = self.actor.col - (p.width - 1) // 2
            target = max(0, min(wmax, target))
            p.aim_col += (target - p.aim_col) * min(1.0, dt * 9.0)
        p.col = int(round(max(0, min(wmax, p.aim_col))))

        p.aim_t -= dt
        if p.aim_t <= 0:
            self._begin_fall(p)

    def _begin_fall(self, p: Piece) -> None:
        if p is None:
            return
        self._fire_event("on_aim_end")
        p.phase = FALL
        p.fall_t = 0.0
        p.interval = self.fall_interval()
        if p.instant:
            self._instant_lock(p)

    def _update_fall(self, p: Piece, dt: float) -> None:
        if p is None:
            return
        if p.instant:
            self._instant_lock(p)
            return
        p.interval = self.fall_interval()
        p.fall_t += dt
        guard = 0
        while p.fall_t >= p.interval and guard < 40:
            p.fall_t -= p.interval
            guard += 1
            if not self._step_down(p):
                break
            if self.result:
                return

    def _step_down(self, p: Piece) -> bool:
        nrow = p.row + 1
        if self._fits_active(p, None, nrow):
            p.row = nrow
            self._collide_piece_actor()
            return True
        self._lock(p)
        return False

    def _instant_lock(self, p: Piece) -> None:
        if p is None:
            return
        target = self.stage.drop_row(p, p.row)
        while p.row < target:
            p.row += 1
            if self._overlaps_actor(p):
                self._fail("crush")
                return
        self._lock(p)

    def _blocked_at_spawn(self, p: Piece) -> bool:
        if p is None:
            return False
        return not self.stage.fits(p, None, p.row)

    def _lock(self, p: Piece) -> None:
        if p is None:
            return
        placed = self.stage.lock(p)
        if not placed:
            # 方块整体上不去也下不来（舞台顶端已被填满）
            if p in self.pieces:
                self.pieces.remove(p)
            self.spawn_delay = 0.5
            if self.level["fail"].get("overflow", False):
                self._fail("overflow")
            return
        # 锁定瞬间小人若在方块内部，等同于被命中
        if self.level["fail"].get("crush", True) and \
                set(placed) & set(self.actor.tiles()):
            self._fail("crush")
            return
        if p in self.pieces:
            self.pieces.remove(p)
        p.phase = OVER
        self.lock_count += 1
        self.spawn_delay = 0.22
        self.vfx.trigger("shake", 3.4)
        self.vfx.trigger("flash", 0.18)
        if self.audio:
            self.audio.lock()

        blk = self.level["blocks"]
        ramp = float(blk.get("ramp", 0.985))
        lo = float(blk.get("fall_interval_min", 0.10))
        self.cur_interval = max(lo, self.cur_interval * ramp)

        self._fire_event("on_lock")
        self._clear_lines()         # 填满的行在这里消掉
        self._check_triggers()      # 固化数 / 时间 / 累计消行等条件型事件立刻生效
        self._check_lose()
        if not self.result:
            self._check_win()

    # ================================================== 消行
    @property
    def line_clear_on(self) -> bool:
        return bool(self.level["blocks"].get("line_clear", False))

    def _clear_lines(self) -> int:
        """锁定后检查满行并消除，上方整体下落一格。

        返回本次消除的行数。未开启该玩法时恒为 0。
        """
        if not self.line_clear_on or self.result:
            return 0
        full = self.stage.full_rows()
        if not full:
            return 0
        n = len(full)
        self.stage.clear_rows(full)
        self.cleared_lines += n
        self.vfx.trigger("flash", 0.22)
        self.vfx.trigger("shake", 2.6)
        if self.audio:
            self.audio.play("sparkle", 0.9)
        self._lift_actor_if_stuck()
        self.push_toast(f"消除 {n} 行", S_ACCENT)

        # 瞬时型：本次至少消掉 N 行（不填参数 = 每次消行都触发）
        for ev in self.events:
            if ev.get("trigger") != "on_line_clear":
                continue
            want = ev.get("param")
            if want is not None:
                try:
                    if n < int(want):
                        continue
                except (TypeError, ValueError):
                    continue
            self._run_event(ev)
        return n

    def _lift_actor_if_stuck(self) -> None:
        """消行后地形整体下移，小人可能被埋进实心格——把它顶上去。"""
        a = self.actor
        if not touching(self.stage, a.x, a.y, AW, AH):
            return
        for _ in range(self.stage.h + 2):
            a.y -= 1.0
            if not touching(self.stage, a.x, a.y, AW, AH):
                break
        a.vy = max(0.0, float(getattr(a, "vy", 0.0)))

    # ================================================== 判定
    def _overlaps_actor(self, p: Piece) -> bool:
        if p is None:
            return False
        pc = set(c for c, r in p.cells() if r >= 0)
        return bool(pc & set(self.actor.tiles()))

    def _collide_piece_actor(self) -> None:
        if self.result or not self.pieces:
            return
        if not self.level["fail"].get("crush", True):
            return
        for p in list(self.pieces):
            if getattr(p, "phase", AIM) != FALL:
                continue
            if self._overlaps_actor(p):
                self._fail("crush")
                return

    def _check_win(self) -> None:
        if self.result:
            return
        g = self.level["goal"]
        t = g.get("type", "reach_row")
        hit = False
        if t == "reach_row":
            hit = self.actor.top_row <= self.goal_row_value()
        elif t == "survive":
            hit = self.elapsed >= float(g.get("seconds", 60))
        elif t == "lock_count":
            hit = self.lock_count >= int(g.get("count", 20))
        elif t == "clear_lines":
            hit = self.cleared_lines >= int(g.get("clear", 6))
        elif t == "none":
            hit = False
        if hit:
            self.win()

    def goal_row_value(self) -> int:
        return int(self.level["goal"].get("row", 0))

    def _check_lose(self) -> None:
        if self.result:
            return
        f = self.level["fail"]
        if f.get("buried", True) and self.actor.is_buried():
            self._fail("buried")
            return
        if f.get("stuck", False) and not self._can_go_up():
            self._fail("stuck")

    def _can_go_up(self) -> bool:
        """粗略可达性：玩家是否还能站得更高。"""
        st = self.stage
        climb = int(self.player_cfg.get("climb", 1))
        jump = int(max(1, math.floor(float(self.player_cfg.get("jump_height", 2.15)))))
        start = (self.actor.col, max(0, self.actor.row))
        seen = {start}
        q = deque([start])
        limit = st.w * st.h
        best = 1 << 30
        while q and limit > 0:
            limit -= 1
            c, r = q.popleft()
            best = min(best, r)
            for dc in (-2, -1, 1, 2):
                nc = c + dc
                if nc < 0 or nc >= st.w:
                    continue
                for dr in range(-jump, climb + 1):
                    nr = r + dr
                    if nr < 0 or nr >= st.h:
                        continue
                    if st.is_solid(nc, nr):
                        continue
                    # 需要落脚点
                    if not (st.is_solid(nc, nr + 1) or nr == st.h - 1):
                        continue
                    if (nc, nr) not in seen:
                        seen.add((nc, nr))
                        q.append((nc, nr))
        del best
        target_row = self.actor.row - 1
        return any(r <= target_row for _, r in seen)

    # ================================================== 结果
    def win(self) -> None:
        if self.result:
            return
        self.result = {"kind": "win", "reason": "goal", "text": "登顶成功"}
        if self.audio:
            self.audio.win()
        self._fire_event("on_win")
        if self.save:
            self.save.record_clear(self.level.id, int(self.elapsed * 1000))
            self.save.record_height(self.level.id, self.best_row)

    def _fail(self, reason: str) -> None:
        if self.result:
            return
        if reason == "crush" and not self.level["fail"].get("crush", True):
            return
        if reason == "overflow" and not self.level["fail"].get("overflow", True):
            return
        text = self.level.fail_text(reason)
        self.result = {"kind": "lose", "reason": reason, "text": text}
        self.pieces.clear()
        self.vfx.trigger("shake", 9.0)
        self.vfx.trigger("flash", 0.35)
        if self.audio:
            self.audio.lose()
        if self.save:
            self.save.record_height(self.level.id, self.best_row)
        self._fire_event("on_lose")

    # ================================================== 事件 / 剧本
    def _check_triggers(self) -> None:
        """每帧检查「条件型」触发时机：抵达行 / 最高行 / 演出时间 / 固化块数。"""
        for ev in self.events:
            t = ev.get("trigger")
            p = ev.get("param")
            hit = False
            try:
                if t == "on_row":
                    hit = p is not None and self.actor.top_row <= int(p)
                elif t == "on_height":
                    hit = p is not None and self.best_row <= int(p)
                elif t == "on_time":
                    hit = p is not None and self.elapsed >= float(p)
                elif t == "on_lock_count":
                    hit = p is not None and self.lock_count >= int(p)
                elif t == "on_clear_count":
                    hit = p is not None and self.cleared_lines >= int(p)
                else:
                    continue
            except (TypeError, ValueError):
                continue
            if hit:
                self._run_event(ev)

    def _trigger_events(self, trigger: str, param=None) -> None:
        """触发「瞬时型」时机：开演 / 方块出现 / 开始下落 / 固化 / 胜负 / 按键。"""
        for ev in self.events:
            if ev.get("trigger") != trigger:
                continue
            ep = ev.get("param")
            if param is not None and ep is not None and \
                    str(ep).lower() != str(param).lower():
                continue
            self._run_event(ev)

    def _run_event(self, ev: dict) -> None:
        uid = str(ev.get("id") or "") or \
            f"{ev.get('trigger')}:{ev.get('param')}:{ev.get('_i', 0)}"
        if ev.get("once", True):
            if uid in self.fired:
                return
            self.fired.add(uid)
        val = {"script": ev.get("script", ""),
               "mode": ev.get("mode") or "ambient"}
        if ev.get("story"):
            val["story"] = ev["story"]
        self.run_event(uid, val)

    def _fire_event(self, name: str) -> None:
        """兼容旧接口：按 'on_row:5' 这样的键名触发对应事件。"""
        trigger, param = L.split_trigger(name)
        self._trigger_events(trigger, param)

    def notify_key(self, key: str) -> None:
        """外部（场景）上报一次按键，供 on_key 触发时机使用。"""
        if key:
            self._trigger_events("on_key", str(key).lower())

    def run_event(self, name: str, val) -> None:
        if isinstance(val, str):
            stmts, mode = L.story_statements(val), "ambient"
        elif isinstance(val, dict):
            if "story" in val:
                stmts = L.story_statements(L.load_story(str(val["story"])))
            else:
                stmts = L.story_statements(val.get("script", ""))
            mode = val.get("mode", "blocking" if name == "on_start" else "ambient")
        elif isinstance(val, list):
            stmts = L.story_statements("\n".join(str(x) for x in val))
            mode = "ambient"
        else:
            return
        if not stmts:
            return
        self.play_script(stmts, mode)

    def play_script(self, stmts: List[Stmt], mode="ambient", dwell=1.9) -> None:
        if self.runner.active and not self.blocking:
            self.runner.stop()
        self.blocking = (mode == "blocking")
        self.hide_dialogue = False
        self.runner.load(stmts, dwell=dwell if mode != "blocking" else 0.0)

    # -------------------------------------------------- 指令
    def _handlers(self) -> Dict[str, callable]:
        return {
            "win": lambda a: self.win(),
            "lose": self._cmd_lose,
            "drop": self._cmd_drop,
            "vfx": self._cmd_vfx,
            "clear": self._cmd_clear,
            "reset": self._cmd_reset,
            "quit": self._cmd_quit,
            "wipe": self._cmd_wipe,
            "shake": self._cmd_shake,
            "say": self._cmd_say,
            "sfx": self._cmd_sfx,
            "sound": self._cmd_sfx,
            "se": self._cmd_sfx,
            "bgm": self._cmd_bgm,
            "music": self._cmd_bgm,
            "vol": self._cmd_vol,
            "volume": self._cmd_vol,
            "mute": self._cmd_mute,
            "_unknown": lambda a: None,
        }

    def _cmd_drop(self, arg: str) -> None:
        """drop [块数]
           drop <形状> [列号 | player | random] [朝向] [块数] [slow]

        默认瞬间落到底；带 slow 时只跳过倒计时，按正常速度落下（能看清落点）。
        例：drop 3 / drop T / drop T 4 / drop T player 1 / drop 十字 2 0 3
            drop T 4 slow   —— 第四列一块 T，立刻开始落但慢慢掉
        """
        args = split_args(arg or "")
        slow = False
        rest_args = []
        for a in args:
            if str(a).lower() in ("slow", "fall", "gradual", "缓", "慢"):
                slow = True
            else:
                rest_args.append(a)
        args = rest_args
        kind = None
        col = None
        rot = None
        n = 1
        if not args:
            n = 1
        elif _is_num(args[0]):
            n = max(1, int(float(args[0])))
        else:
            kind = str(args[0])
            rest = args[1:]
            if rest:
                tok = rest[0]
                if _is_num(tok):
                    col = int(float(tok))
                elif str(tok).lower() in ("player", "me", "center", "self"):
                    col = "player"
                elif str(tok).lower() in ("random", "rnd", "any"):
                    col = "random"
                rest = rest[1:]
            if rest and _is_num(rest[0]):
                rot = int(float(rest[0]))
                rest = rest[1:]
            if rest and _is_num(rest[0]):
                n = max(1, int(float(rest[0])))
        if kind is not None and not is_known(kind):
            self.push_toast(f"未知形状：{kind}", S_WARN)
            return
        for _ in range(n):
            self.forced.append({"kind": kind, "col": col, "rot": rot,
                                "quick": slow})
        self.drop_queue += n
        aim = self.aiming
        if kind is not None and aim is not None and \
                len(self.pieces) >= self.concurrent():
            # 指定了形状且场上已满：换掉正在瞄准的那块，视觉上才对得上
            self.pieces.remove(aim)
            aim = None
        if aim is not None:
            aim.aim_t = 0.0
            if slow:
                aim.instant = False
                self._begin_fall(aim)          # 跳过倒计时，正常速度落
            else:
                aim.instant = True
        elif not self.pieces:
            self.spawn_delay = 0.0

    def _cmd_lose(self, arg: str) -> None:
        text = (arg or "").strip()
        if not text:
            text = self.level.fail_text("script") or self.level.data["fail"]["text"]
        self.result = {"kind": "lose", "reason": "script", "text": text}
        self.pieces.clear()
        self.vfx.trigger("shake", 9.0)
        self.vfx.trigger("flash", 0.35)

    def _cmd_vfx(self, arg: str) -> None:
        parts = (arg or "").split()
        if not parts:
            return
        name = parts[0]
        flag = parts[1].lower() if len(parts) > 1 else "on"
        if flag in ("on", "1", "true", "开", "激活"):
            self.vfx.enabled.add(name)
        else:
            self.vfx.enabled.discard(name)

    def _cmd_clear(self, arg: str) -> None:
        self.hide_dialogue = True

    def _cmd_reset(self, arg: str) -> None:
        keep = self.result
        self.reset()
        self.result = keep

    def _cmd_quit(self, arg: str) -> None:
        self.request_quit = True
        if self.on_quit:
            self.on_quit()

    def _cmd_wipe(self, arg: str) -> None:
        if self.save:
            self.save.wipe()
            self.push_toast("存档已删除", S_BAD)
        else:
            self.push_toast("没有可删除的存档", S_DIM)

    # -------------------------------------------------- 音频指令
    def _cmd_sfx(self, arg: str) -> None:
        """sfx <名称> [音量]：播放音效（内置名 / 中文别名 / content/audio 下的文件）。"""
        if not self.audio:
            return
        parts = (arg or "").split()
        if not parts:
            return
        name = resolve_sfx(parts[0])
        vol = 1.0
        if len(parts) > 1:
            try:
                vol = max(0.0, min(2.0, float(parts[1])))
            except ValueError:
                vol = 1.0
        if not self.audio.play(name, vol):
            self.push_toast(f"未知音效：{parts[0]}", S_WARN)

    def _cmd_bgm(self, arg: str) -> None:
        """bgm <名称> [音量] / bgm off：循环播放背景音乐。"""
        if not self.audio:
            return
        parts = (arg or "").split()
        if not parts:
            return
        name = parts[0]
        if name.lower() in ("off", "stop", "none", "0", "停", "停止"):
            self.audio.stop_bgm()
            self.push_toast("音乐已停止", S_DIM)
            return
        vol = 1.0
        if len(parts) > 1:
            try:
                vol = max(0.0, min(2.0, float(parts[1])))
            except ValueError:
                vol = 1.0
        if not self.audio.bgm(resolve_bgm(name), vol):
            self.push_toast(f"未知音乐：{name}", S_WARN)

    def _cmd_vol(self, arg: str) -> None:
        """vol <0-100>：全局音量。"""
        if not self.audio:
            return
        try:
            v = float((arg or "80").strip())
        except ValueError:
            return
        self.audio.set_volume(max(0.0, min(1.0, v / 100.0)))
        self.push_toast(f"音量 {int(v)}%", S_DIM)

    def _cmd_mute(self, arg: str) -> None:
        if not self.audio:
            return
        muted = self.audio.toggle_mute()
        self.push_toast("已静音" if muted else "已恢复音量", S_DIM)

    def _cmd_shake(self, arg: str) -> None:
        try:
            amt = float((arg or "6").strip())
        except ValueError:
            amt = 6.0
        self.vfx.trigger("shake", amt)

    def _cmd_say(self, arg: str) -> None:
        self.push_toast(arg or "", S_ACCENT)

    # -------------------------------------------------- 反馈
    def push_toast(self, text: str, color=(228, 234, 246)) -> None:
        self.toast.append((text, 2.2, color))
        if len(self.toast) > 6:
            self.toast.pop(0)

    def _update_toasts(self, dt: float) -> None:
        out = []
        for t, life, c in self.toast:
            life -= dt
            if life > 0:
                out.append((t, life, c))
        self.toast = out


def _is_num(text) -> bool:
    try:
        float(str(text).strip())
        return True
    except (TypeError, ValueError):
        return False


S_ACCENT = (96, 178, 255)
S_BAD = (255, 104, 118)
S_WARN = (255, 198, 92)
S_DIM = (148, 158, 183)
