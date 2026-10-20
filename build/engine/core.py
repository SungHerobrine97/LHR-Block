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
from .audio import resolve_bgm, resolve_sfx
from .pieces import Bag, Piece
from .save import SaveData
from .scriptvm import Runner, Stmt
from .stage import Stage
from .vfx import VFXManager

AIM, FALL, OVER = "aim", "fall", "over"

GOAL_TYPES = ("reach_row", "survive", "lock_count", "none")


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

        self.piece: Optional[Piece] = None
        self.phase = AIM
        self.aim_t = 0.0
        self.aim_total = 1.0
        self.spawn_delay = 0.28
        self.aim_col = float(col)
        self.elapsed = 0.0
        self.lock_count = 0
        self.result: Optional[dict] = None
        self.fired: Set[str] = set()
        self.drop_queue = 0
        self.instant = False
        self.cur_interval = float(
            (self.level["blocks"].get("fall_interval") or 0.30))
        self.best_row = self.actor.top_row
        self.hide_dialogue = False
        self.vfx.set_enabled(self.level.get("vfx") or [])
        self.freeze_timer = 0.0
        self._jump_latch = False
        self._rot_latch = False
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

    def _update_world(self, dt: float, inp: Dict[str, bool]) -> None:
        if self.result:
            return
        self._check_row_events()

        if self.piece is None:
            self.spawn_delay -= dt
            if self.drop_queue > 0:
                self.drop_queue -= 1
                self._spawn(instant=True)
            elif self.spawn_delay <= 0:
                self._spawn()
        else:
            # 旋转（上升沿，按住只转一次）：瞄准与下落中皆可，
            # 一旦锁定进舞台（phase == OVER）就再也不能改变。
            want_rot = bool(inp.get("rotate"))
            if want_rot and not self._rot_latch:
                self._try_rotate(1)
            self._rot_latch = want_rot
            if self.phase == AIM:
                self._update_aim(dt, inp)
            elif self.phase == FALL:
                self._update_fall(dt)

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
    def _spawn(self, instant: bool = False) -> None:
        blk = self.level["blocks"]
        kind = self.bag.next()
        nrot = len(self.__class__._rots(kind))
        rot = self.rng.randrange(nrot) if blk.get("allow_rotation", True) else 0
        p = Piece(kind, rot)
        pw = p.width
        col = max(0, min(self.stage.w - pw, self.actor.col - (pw - 1) // 2))
        p.col = col
        p.row = -p.height
        p.interval = self.fall_interval()
        self.piece = p
        self.aim_col = float(col)

        lo, hi = self._aim_range()
        self.aim_total = self.rng.uniform(lo, hi)
        self.aim_t = self.aim_total
        self.phase = AIM
        self.instant = instant

        self._place_at_spawn()
        if self.piece is None:
            return
        self._fire_event("on_spawn")

    def _place_at_spawn(self) -> None:
        """首选列放不下时，向两侧寻找最近的可容纳位置；无处可落则按 overflow 设定处理。"""
        p = self.piece
        if p is None:
            return
        if self.stage.fits(p, None, p.row):
            return
        found = None
        for d in range(1, self.stage.w):
            for cand in (p.col - d, p.col + d):
                if 0 <= cand <= self.stage.w - p.width and \
                        self.stage.fits(p, cand, p.row):
                    found = cand
                    break
            if found is not None:
                break
        if found is not None:
            p.col = found
            self.aim_col = float(found)
            return
        # 舞台已被塞满
        if self.level["fail"].get("overflow", False):
            self._fail("overflow")
        else:
            self.piece = None
            self.spawn_delay = 0.9

    @staticmethod
    def _rots(kind):
        from .pieces import ROTATIONS
        return ROTATIONS[kind]

    # ================================================== 旋转
    @property
    def can_rotate(self) -> bool:
        """当前方块是否还允许旋转（锁定固化后为 False）。"""
        return (self.result is None and self.piece is not None
                and self.phase != OVER
                and bool(self.level["blocks"].get("player_rotate", True)))

    def _try_rotate(self, delta: int = 1) -> bool:
        """旋转当前方块：底边对齐 + 踢墙（左右 / 上移）找合法落位。

        找不到合法位置就放弃本次旋转，方块保持原样。
        """
        p = self.piece
        if p is None or self.phase == OVER or self.result:
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
                if self.stage.fits(p, col, row, nrot):
                    p.rot = nrot
                    p.col = col
                    p.row = row
                    wmax = max(0, self.stage.w - p.width)
                    self.aim_col = float(max(0, min(wmax, col)))
                    self.rotations += 1
                    if self.audio:
                        self.audio.rotate()
                    # 旋转后若正好罩住小人，等同于被砸中
                    if self.phase == FALL:
                        self._collide_piece_actor()
                    return True
        if self.audio:
            self.audio.play("buzz", 0.35)
        return False

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

    def _update_aim(self, dt: float, inp: Dict[str, bool]) -> None:
        # 剧本指令 drop 要求的「立即下落」：直接跳过倒计时
        if self.instant:
            self._begin_fall()
            return
        blk = self.level["blocks"]
        mode = blk.get("hover", "follow")
        p = self.piece
        wmax = self.stage.w - p.width
        if mode == "manual":
            self._repeat = getattr(self, "_repeat", 0.0)
            self._repeat -= dt
            if self._repeat <= 0:
                step = 0
                if inp.get("pleft"):
                    step = -1
                elif inp.get("pright"):
                    step = 1
                if step and not inp.get("left") and not inp.get("right"):
                    pass
                if step:
                    self.aim_col = max(0, min(wmax, self.aim_col + step))
                    self._repeat = 0.10
        elif mode == "random":
            pass  # 生成时已随机
        else:  # follow —— 跟随玩家选择的下落位置
            target = self.actor.col - (p.width - 1) // 2
            target = max(0, min(wmax, target))
            self.aim_col += (target - self.aim_col) * min(1.0, dt * 9.0)
        p.col = int(round(max(0, min(wmax, self.aim_col))))

        self.aim_t -= dt
        if self.aim_t <= 0:
            self._begin_fall()

    def _begin_fall(self) -> None:
        p = self.piece
        if p is None:
            return
        self._fire_event("on_aim_end")
        self.phase = FALL
        p.fall_t = 0.0
        p.interval = self.fall_interval()
        if self.instant:
            self._instant_lock()

    def _update_fall(self, dt: float) -> None:
        p = self.piece
        if p is None:
            return
        if self.instant:
            self._instant_lock()
            return
        p.interval = self.fall_interval()
        p.fall_t += dt
        guard = 0
        while p.fall_t >= p.interval and guard < 40:
            p.fall_t -= p.interval
            guard += 1
            if not self._step_down():
                break
            if self.result:
                return

    def _step_down(self) -> bool:
        p = self.piece
        nrow = p.row + 1
        if self.stage.fits(p, None, nrow):
            p.row = nrow
            self._collide_piece_actor()
            return True
        self._lock()
        return False

    def _instant_lock(self) -> None:
        p = self.piece
        if p is None:
            return
        target = self.stage.drop_row(p, p.row)
        while p.row < target:
            p.row += 1
            if self._overlaps_actor():
                self._fail("crush")
                return
        self._lock()

    def _blocked_at_spawn(self) -> bool:
        p = self.piece
        if p is None:
            return False
        return not self.stage.fits(p, None, p.row)

    def _lock(self) -> None:
        p = self.piece
        if p is None:
            return
        placed = self.stage.lock(p)
        if not placed:
            # 方块整体上不去也下不来（舞台顶端已被填满）
            self.piece = None
            self.spawn_delay = 0.5
            if self.level["fail"].get("overflow", False):
                self._fail("overflow")
            return
        # 锁定瞬间小人若在方块内部，等同于被命中
        if self.level["fail"].get("crush", True) and \
                set(placed) & set(self.actor.tiles()):
            self._fail("crush")
            return
        self.piece = None
        self.phase = OVER
        self.lock_count += 1
        self.spawn_delay = 0.22
        self.instant = False
        self.vfx.trigger("shake", 3.4)
        self.vfx.trigger("flash", 0.18)
        if self.audio:
            self.audio.lock()

        blk = self.level["blocks"]
        ramp = float(blk.get("ramp", 0.985))
        lo = float(blk.get("fall_interval_min", 0.10))
        self.cur_interval = max(lo, self.cur_interval * ramp)

        self._fire_event("on_lock")
        self._check_lose()
        if not self.result:
            self._check_win()

    # ================================================== 判定
    def _overlaps_actor(self) -> bool:
        p = self.piece
        if p is None:
            return False
        pc = set(c for c, r in p.cells() if r >= 0)
        return bool(pc & set(self.actor.tiles()))

    def _collide_piece_actor(self) -> None:
        if self.result or self.piece is None or self.phase != FALL:
            return
        if not self.level["fail"].get("crush", True):
            return
        if self._overlaps_actor():
            self._fail("crush")

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
        self.piece = None
        self.vfx.trigger("shake", 9.0)
        self.vfx.trigger("flash", 0.35)
        if self.audio:
            self.audio.lose()
        if self.save:
            self.save.record_height(self.level.id, self.best_row)
        self._fire_event("on_lose")

    # ================================================== 事件 / 剧本
    def _check_row_events(self) -> None:
        for key, val in self.level.get("events", {}).items():
            if not key.startswith("on_row"):
                continue
            _, _, arg = key.partition(":")
            try:
                row = int(arg)
            except ValueError:
                continue
            if key in self.fired:
                continue
            if self.actor.top_row <= row:
                self.fired.add(key)
                self.run_event(key, val)

    def _fire_event(self, name: str) -> None:
        val = self.level.event(name)
        if val is None:
            return
        if name == "on_lock" and isinstance(val, dict) and val.get("repeat") is False:
            if name in self.fired:
                return
            self.fired.add(name)
        self.run_event(name, val)

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
        try:
            n = max(1, int(float((arg or "1").strip())))
        except ValueError:
            n = 1
        self.drop_queue += n
        if self.piece is not None and self.phase == AIM:
            self.aim_t = 0.0
            self.instant = True
        elif self.piece is None:
            self.spawn_delay = 0.0

    def _cmd_lose(self, arg: str) -> None:
        text = (arg or "").strip()
        if not text:
            text = self.level.fail_text("script") or self.level.data["fail"]["text"]
        self.result = {"kind": "lose", "reason": "script", "text": text}
        self.piece = None
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


S_ACCENT = (96, 178, 255)
S_BAD = (255, 104, 118)
S_WARN = (255, 198, 92)
S_DIM = (148, 158, 183)
