"""场景：标题菜单 / 演出（游戏）/ 共用 HUD。"""
from __future__ import annotations

import copy
import math

import pygame

from . import level as L
from . import render as R
from . import settings as S
from . import ui
from .core import Core
from .pieces import SHAPE_DEFS
from .vfx import ALL_VFX, RENDER_NAME

WIN_W, WIN_H = 1120, 720


def layout_game(w: int, h: int) -> dict:
    m = 16
    left_w, right_w = 250, 252
    top = 66
    dialogue_h = 92
    hint_h = 24
    left = pygame.Rect(m, top, left_w, h - top - hint_h - m)
    right = pygame.Rect(w - m - right_w, top, right_w, h - top - hint_h - m)
    sx = left.right + 12
    sw = max(180, right.x - 12 - sx)
    bottom_limit = h - m - dialogue_h - hint_h - 8
    stage_area = pygame.Rect(sx, top, sw, max(120, bottom_limit - top))
    dialogue = pygame.Rect(m, h - m - dialogue_h - hint_h - 6,
                           w - m * 2, dialogue_h)
    hint = pygame.Rect(m, h - hint_h - m + 2, w - m * 2, hint_h)
    return {"left": left, "right": right, "stage_area": stage_area,
            "dialogue": dialogue, "hint": hint, "topbar": pygame.Rect(m, 12, w - m * 2, 34)}


class Scene:
    def __init__(self, app):
        self.app = app

    def enter(self):
        pass

    def exit(self):
        pass

    def handle(self, ev):
        pass

    def update(self, dt):
        pass

    def draw(self, surf):
        pass


# ================================================================ 菜单
class MenuScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.levels: list = []
        self.presets: list = []
        self.rows: list = []
        self.buttons: list = []
        self.index = 0
        self.preset_idx = 0
        self.preset_names = ["（无）"]
        self.scroll = 0
        self.t = 0.0
        self.reload()

    def reload(self):
        S.ensure_dirs()
        self.levels = L.list_levels()
        if not self.levels:
            self.levels = [L.Level(default_level_data(), None)]
        self.presets = L.list_presets()
        self.preset_names = ["（无）"] + [p.get("name", p.get("id"))
                                          for p in self.presets]
        self.index = max(0, min(self.index, len(self.levels) - 1))
        self._build()

    def _build(self):
        self.rows = []
        w, h = self.app.screen.get_size()
        lay = layout_game(w, h)
        left = lay["left"]
        y = left.y + 16
        rowh = 54
        for i, lv in enumerate(self.levels):
            rect = pygame.Rect(left.x, y, left.w - 8, rowh)
            lvdata = self.app.save.level(lv.id)
            tag = "已通关" if lvdata.get("cleared") else ""
            self.rows.append(ui.ListRow(
                rect, lv.title, f"{lv.width}×{lv.height} · {lv.summary()}",
                (lambda i=i: self._pick(i)), i == self.index, tag))
            y += rowh + 6

        # 右侧按钮
        r = lay["right"]
        self.buttons = []
        bw = r.w - 8
        bx = r.x
        self.b_start = ui.Button(pygame.Rect(bx, r.bottom - 212, bw, 42),
                                 "开始演出", self.start, 16, "primary")
        self.b_edit = ui.Button(pygame.Rect(bx, r.bottom - 164, bw, 36),
                                "打开编辑器", self.open_editor, 14)
        self.st_vol = ui.Stepper(pygame.Rect(bx, r.bottom - 126, bw, 26), "音量",
                                 int(self.app.save.data["options"].get("volume", 80)),
                                 0, 100, 10, self._set_volume, "{:g}")
        self.b_preset = ui.Choice(pygame.Rect(bx, r.bottom - 92, bw, 26),
                                  "特色玩法", list(range(len(self.preset_names))),
                                  self.preset_idx, self._choose_preset,
                                  self.preset_names)
        self.b_wipe = ui.Button(pygame.Rect(bx, r.bottom - 60, bw, 24),
                                "删除存档", self.wipe, 12, "danger")
        half = (bw - 6) // 2
        self.b_import = ui.Button(pygame.Rect(bx, r.bottom - 32, half, 22),
                                  "导入演出", self.import_level_file, 11, "ghost")
        self.b_refresh = ui.Button(pygame.Rect(bx + half + 6, r.bottom - 32, half, 22),
                                   "刷新内容", self.reload, 11, "ghost")
        self.buttons = [self.b_start, self.b_edit, self.st_vol, self.b_preset,
                        self.b_wipe, self.b_refresh, self.b_import]

    def import_level_file(self):
        """从外部 JSON 导入演出文件（会安装到 content/levels）。"""
        from .editor import EditorScene
        path = EditorScene._file_dialog(False)
        if not path:
            self.app.toast("未选择文件（也可放到 build/import 目录）", S.DIM)
            return
        names = L.import_level_file(path)
        if not names:
            self.app.toast("导入失败：不是有效的演出 JSON", S.BAD)
            return
        self.reload()
        self.app.toast(f"已导入 {len(names)} 份演出", S.GOOD)

    def _set_volume(self, v: int) -> None:
        v = max(0, min(100, int(v)))
        self.app.save.data["options"]["volume"] = v
        audio = getattr(self.app, "audio", None)
        if audio:
            audio.set_volume(v / 100.0)
            audio.play("ui")

    def _pick(self, i):
        self.index = i
        self._build()

    def _choose_preset(self, v):
        self.preset_idx = v

    def start(self):
        lv = self.levels[self.index]
        data = copy.deepcopy(lv.data)
        nlv = L.Level(data, lv.path)
        if self.preset_idx > 0:
            L.apply_preset(nlv, self.presets[self.preset_idx - 1])
        self.app.goto(PlayScene(self.app, nlv))

    def open_editor(self):
        lv = self.levels[self.index]
        from .editor import EditorScene
        self.app.goto(EditorScene(self.app, L.Level(copy.deepcopy(lv.data), lv.path)))

    def wipe(self):
        self.app.save.wipe()
        self.reload()
        self.app.toast("存档已删除", S.BAD)

    def handle(self, ev):
        mouse = pygame.mouse.get_pos()
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for row in self.rows:
                if row.handle_click(ev.pos):
                    return
            for b in self.buttons:
                if b.handle_click(ev.pos):
                    return
        elif ev.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - ev.y * 30)
        elif ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_DOWN, pygame.K_s):
                self.index = (self.index + 1) % len(self.levels)
                self._build()
            elif ev.key in (pygame.K_UP, pygame.K_w):
                self.index = (self.index - 1) % len(self.levels)
                self._build()
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.start()
            elif ev.key == pygame.K_F2:
                self.open_editor()
        # 列表点击后立即重建选中态
        for i, row in enumerate(self.rows):
            if row.rect.collidepoint(mouse) and pygame.mouse.get_pressed()[0]:
                pass

    def update(self, dt):
        self.t += dt

    def draw(self, surf):
        w, h = surf.get_size()
        surf.fill(S.BG)
        lay = layout_game(w, h)
        mouse = pygame.mouse.get_pos()

        # 顶部标题
        title = S.font(30, True).render("登塔者", True, S.TEXT)
        surf.blit(title, (lay["topbar"].x, lay["topbar"].y - 2))
        sub = S.font(14).render("Climb Tower · 在坠落的方块之间，抵达舞台顶端", True, S.DIM)
        surf.blit(sub, (lay["topbar"].x + title.get_width() + 14, lay["topbar"].y + 14))
        sinfo = S.font(12).render(self.app.save.summary(), True, S.DIM2)
        surf.blit(sinfo, (lay["topbar"].right - sinfo.get_width(), lay["topbar"].y + 16))

        # 左侧列表
        left = lay["left"]
        S.panel(surf, pygame.Rect(left.x - 6, left.y - 6,
                                  left.w + 4, left.h + 12), S.PANEL, S.LINE, 10)
        S.draw_text(surf, "演出列表", (left.x + 4, left.y - 2), 13, S.DIM, True)
        for row in self.rows:
            row.draw(surf, mouse)

        # 右侧详情
        r = lay["right"]
        lv = self.levels[self.index]
        S.panel(surf, pygame.Rect(r.x - 8, r.y - 6, r.w + 8, r.h + 12), S.PANEL, S.LINE, 10)
        y = r.y + 4
        S.draw_text(surf, lv.title, (r.x, y), 20, S.TEXT, True)
        y += 30
        if lv.get("subtitle"):
            S.draw_text(surf, lv.get("subtitle"), (r.x, y), 13, S.DIM)
            y += 20
        S.draw_text(surf, f"作者：{lv.get('author') or '—'}", (r.x, y), 12, S.DIM2)
        y += 26

        info = [
            ("舞台", f"{lv.width} × {lv.height}"),
            ("目标", lv.summary()),
            ("方块下落间隔", f"{float(lv['blocks'].get('fall_interval', 0.3)):.2f}s"),
            ("倒计时", f"{float(lv['blocks'].get('aim_time', [2, 9.9])[0]):.1f}"
                       f" ~ {float(lv['blocks'].get('aim_time', [2, 9.9])[1]):.1f}s"),
        ]
        hover_mode = {"follow": "跟随小人", "manual": "玩家控制", "random": "随机"}
        info.append(("瞄准方式", hover_mode.get(lv["blocks"].get("hover"), "跟随小人")))
        info.append(("跳跃高度", f"{float(lv['player'].get('jump_height', 2.15)):.2f} 格"))
        for k, v in info:
            S.draw_text(surf, k, (r.x, y), 12, S.DIM2)
            img = S.font(12, True).render(str(v), True, S.TEXT)
            surf.blit(img, (r.right - img.get_width(), y))
            y += 18
        y += 6

        vfxs = lv.get("vfx") or []
        S.draw_text(surf, "VFX", (r.x, y), 12, S.DIM2)
        y += 16
        if vfxs:
            x = r.x
            for name in vfxs:
                label = RENDER_NAME.get(name, name)
                tw = S.font(11).size(label)[0] + 12
                if x + tw > r.right:
                    x = r.x
                    y += 20
                S.round_rect(surf, pygame.Rect(x, y, tw, 17), S.PANEL3, 5)
                S.draw_text(surf, label, (x + 6, y + 2), 11, S.CYAN)
                x += tw + 5
            y += 24
        else:
            S.draw_text(surf, "（无）", (r.x, y), 11, S.DIM2)
            y += 22

        if lv.get("tags"):
            S.draw_text(surf, "标签：" + " / ".join(lv["tags"]), (r.x, y), 11, S.PURPLE)
            y += 18

        # 计数器insert 记忆
        rec = self.app.save.level(lv.id)
        best = rec.get("best_row")
        if best is not None:
            S.draw_text(surf, f"最高抵达第 {best} 行 · 挑战 {rec.get('attempts', 0)} 次",
                        (r.x, y), 12, S.GOLD)
        else:
            S.draw_text(surf, "尚未挑战", (r.x, y), 12, S.DIM2)

        for b in self.buttons:
            b.draw(surf, mouse)

        ui.draw_hint_bar(surf, lay["hint"], [
            ("↑↓", "选择演出"), ("Enter", "开始"), ("F2", "编辑器"),
            ("音量", "右侧步进器调节，0 = 静音"), ("Esc", "退出"),
        ])


# ================================================================ 演出
class PlayScene(Scene):
    def __init__(self, app, level: L.Level, preview=False):
        super().__init__(app)
        self.level = level
        self.core = Core(level, None if preview else app.save,
                         getattr(app, "audio", None))
        self.core.on_quit = lambda: setattr(app, "running", False)
        self.preview = preview
        self.t = 0.0
        self.paused = False
        self.result_time = 0.0
        self.flash_line = 0.0
        self.buttons = []
        self._prev_jump = False
        self._last_lock = 0
        self._res_sound = False
        self._hold_advance = 0.0
        self._block_wait = 0.0
        self.focus_lost = False
        self._build_buttons()

    # -------------------------------------------------- 输入映射
    def _read_input(self):
        k = pygame.key.get_pressed()
        manual = self.level["blocks"].get("hover") == "manual"
        arrow_l = bool(k[pygame.K_LEFT])
        arrow_r = bool(k[pygame.K_RIGHT])
        ad_l = bool(k[pygame.K_a])
        ad_r = bool(k[pygame.K_d])
        if manual:
            left, right = ad_l, ad_r
            pleft, pright = arrow_l, arrow_r
        else:
            left, right = arrow_l or ad_l, arrow_r or ad_r
            pleft = pright = False
        return {
            "left": left, "right": right, "jump": bool(k[pygame.K_SPACE])
            or bool(k[pygame.K_UP]) or bool(k[pygame.K_w]),
            "pleft": pleft, "pright": pright,
            "rotate": bool(k[pygame.K_x]) or bool(k[pygame.K_z]),
            "advance": False,
        }

    def _build_buttons(self):
        self.buttons = []

    def enter(self):
        pygame.key.stop_text_input()
        if not (self.level.get("audio") or {}).get("bgm"):
            audio = getattr(self.app, "audio", None)
            if audio:
                audio.stop_bgm()

    def exit(self):
        audio = getattr(self.app, "audio", None)
        if audio and not self.preview:
            audio.stop_bgm()

    def handle(self, ev):
        if ev.type == pygame.ACTIVEEVENT:
            # 窗口失焦（点到别处 / 最小化）自动暂停，回来继续
            if ev.state & (pygame.APPINPUTFOCUS | pygame.APPACTIVE):
                self.focus_lost = (ev.gain == 0)
            return
        if ev.type == getattr(pygame, "WINDOWFOCUSLOST", -1):
            self.focus_lost = True
            return
        if ev.type == getattr(pygame, "WINDOWFOCUSGAINED", -1):
            self.focus_lost = False
            return
        if ev.type == pygame.KEYDOWN:
            # 上报按键，供剧本的 on_key 触发时机使用
            try:
                self.core.notify_key(pygame.key.name(ev.key))
            except Exception:      # noqa: BLE001
                pass
            if ev.key == pygame.K_ESCAPE:
                self.app.goto(self.app.editor_scene or MenuScene(self.app))
                return
            if ev.key == pygame.K_r:
                self.restart()
                return
            if ev.key == pygame.K_p:
                self.paused = not self.paused
                return
            if ev.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.core.result:
                    if self.core.result["kind"] == "win":
                        self.app.goto(MenuScene(self.app))
                    else:
                        self.restart()
                else:
                    self.core.runner.advance()
                return
            # 对白等待确认时：方向键等也算「继续」，避免看起来像没响应输入
            if self.core.runner.active and self.core.blocking and ev.key in (
                    pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN,
                    pygame.K_a, pygame.K_d, pygame.K_w):
                self.core.runner.advance()
                return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.core.result:
                for b in self.buttons:
                    if b.handle_click(ev.pos):
                        return
                self.restart()
                return
            if self.core.runner.active and self.core.blocking:
                self.core.runner.advance()
                return

    def restart(self):
        self.core = Core(self.level, None if self.preview else self.app.save)
        self.core.on_quit = lambda: setattr(self.app, "running", False)
        self.paused = False
        self.result_time = 0.0
        self.buttons = []
        self._prev_jump = False
        self._last_lock = 0
        self._res_sound = False

    def update(self, dt):
        self.t += dt
        if self.core.request_quit:
            self.app.running = False
            return
        if self.paused or self.focus_lost:
            return
        if self.core.result:
            self.result_time += dt
            return

        inp = self._read_input()
        # 阻塞对白：按住任意操作键连续推进，并设兜底超时，绝不会卡住
        if self.core.runner.active and self.core.blocking:
            self._block_wait += dt
            held = any(inp.get(k) for k in ("left", "right", "jump",
                                            "pleft", "pright", "rotate"))
            if held:
                self._hold_advance += dt
                if self._hold_advance >= 0.22:
                    self._hold_advance = 0.0
                    self.core.runner.advance()
            else:
                self._hold_advance = 0.0
            if self._block_wait >= 5.0:      # 兜底：一行最多等 5 秒，绝不会永久卡住
                self._block_wait = 0.0
                self.core.runner.advance()
        else:
            self._block_wait = 0.0
            self._hold_advance = 0.0

        self.core.update(dt, inp)

    # -------------------------------------------------- 绘制
    def draw(self, surf):
        w, h = surf.get_size()
        lay = layout_game(w, h)
        surf.fill(S.BG)
        core = self.core
        view, cell = R.make_view(lay["stage_area"], core.stage.w, core.stage.h)

        ctx = {"stage_rect": view.inflate(10, 10), "cell": cell, "t": self.t}

        surf.fill(S.BG)
        R.draw_stage_bg(surf, core, view, cell, self.t)
        R.draw_ghost(surf, core, view, cell, self.t)
        R.draw_stage_blocks(surf, core, view, cell, self.t)
        R.draw_piece(surf, core, view, cell, self.t)
        R.draw_aim_meter(surf, core, view, cell, self.t)
        if not (core.result and core.result["kind"] == "lose"
                and core.result["reason"] == "crush"):
            R.draw_actor(surf, core, view, cell, self.t)
        elif core.result["reason"] == "crush":
            R.draw_actor(surf, core, view, cell, self.t)
        core.vfx.draw(surf, ctx)

        if core.runner.active and core.blocking:
            self._draw_pause_badge(surf, view)

        self._draw_left(surf, lay["left"], core)
        self._draw_right(surf, lay["right"], core, view, cell)
        self._draw_dialogue(surf, lay["dialogue"], core)
        if self.focus_lost:
            self._draw_focus_lost(surf, w, h)
        if self.paused:
            self._draw_pause(surf, w, h)
        if core.result:
            self._draw_result(surf, w, h, core)

        hint = [("← →", "移动"), ("空格", "跳跃"), ("X", "旋转方块"),
                ("R", "重来"), ("Esc", "返回")]
        if self.level["blocks"].get("hover") == "manual":
            hint = [("← →", "移动方块"), ("A D", "移动小人"), ("空格", "跳跃"),
                    ("X", "旋转方块"), ("R", "重来"), ("Esc", "返回")]
        inp = self._read_input()
        active = set()
        manual = self.level["blocks"].get("hover") == "manual"
        if manual:
            if inp.get("pleft") or inp.get("pright"):
                active.add("← →")
            if inp.get("left") or inp.get("right"):
                active.add("A D")
        elif inp.get("left") or inp.get("right"):
            active.add("← →")
        if inp.get("jump"):
            active.add("空格")
        if inp.get("rotate") and self.core.can_rotate:
            active.add("X")
        if self.core.runner.active and self.core.blocking:
            hint = [("空格 / 点击 / 方向键", "继续对白（演出已暂停）"),
                    ("R", "重来"), ("Esc", "返回")]
            if active:
                active.add("空格 / 点击 / 方向键")
        ui.draw_hint_bar(surf, lay["hint"], hint, active=active)

    # -------------------------------------------------- 面板
    def _draw_left(self, surf, rect, core):
        S.panel(surf, pygame.Rect(rect.x - 6, rect.y - 6, rect.w + 4, rect.h + 12),
                S.PANEL, S.LINE, 10)
        x = rect.x
        y = rect.y + 2
        S.draw_text(surf, core.level.title, (x, y), 19, S.TEXT, True)
        y += 28
        if core.level.get("subtitle"):
            S.draw_text(surf, core.level.get("subtitle"), (x, y), 12, S.DIM)
            y += 20
        y += 6
        S.draw_text(surf, "目标", (x, y), 12, S.DIM2)
        y += 18
        S.draw_text(surf, core.level.summary(), (x, y), 14, S.GOLD, True)
        y += 26

        g = core.level["goal"]
        prog = 0.0
        if g.get("type", "reach_row") == "reach_row":
            total = core.stage.h - 1 - core.goal_row_value()
            done = core.stage.h - 1 - core.best_row
            prog = max(0.0, min(1.0, done / max(1, total)))
            S.draw_text(surf, f"当前第 {core.actor.top_row} 行 · 最高第 {core.best_row} 行",
                        (x, y), 12, S.TEXT)
        elif g.get("type") == "survive":
            prog = min(1.0, core.elapsed / max(1, float(g.get("seconds", 60))))
            S.draw_text(surf, f"{core.elapsed:.1f} / {float(g.get('seconds', 60)):.0f} 秒",
                        (x, y), 12, S.TEXT)
        elif g.get("type") == "lock_count":
            prog = min(1.0, core.lock_count / max(1, int(g.get("count", 20))))
            S.draw_text(surf, f"已承受 {core.lock_count} / {int(g.get('count', 20))} 块",
                        (x, y), 12, S.TEXT)
        else:
            S.draw_text(surf, "目标由剧本决定", (x, y), 12, S.TEXT)
        y += 18
        S.round_rect(surf, pygame.Rect(x, y, rect.w - 6, 8), S.PANEL3, 4)
        S.round_rect(surf, pygame.Rect(x, y, int((rect.w - 6) * prog), 8),
                     S.mix(S.ACCENT, S.GOLD, prog), 4)
        y += 22

        S.draw_text(surf, "演出规则", (x, y), 12, S.DIM2)
        y += 18
        rules = [
            ("方块", "下落后固定于"),
            ("命中/封困", "立即终止演出"),
            ("失败文本", core.level.data["fail"]["text"]),
        ]
        for k, v in rules:
            S.draw_text(surf, k, (x, y), 12, S.DIM2)
            img = S.font(12).render(str(v), True, S.TEXT)
            surf.blit(img, (x + rect.w - 6 - img.get_width(), y))
            y += 18
        y += 8

        vfxs = sorted(core.vfx.enabled)
        S.draw_text(surf, f"VFX ({len(vfxs)})", (x, y), 12, S.DIM2)
        y += 18
        bx = x
        if vfxs:
            for name in vfxs:
                label = RENDER_NAME.get(name, name)
                tw = S.font(11).size(label)[0] + 12
                if bx + tw > x + rect.w - 6:
                    bx = x
                    y += 20
                S.round_rect(surf, pygame.Rect(bx, y, tw, 17), S.PANEL3, 5)
                S.draw_text(surf, label, (bx + 6, y + 2), 11, S.CYAN)
                bx += tw + 5
        else:
            S.draw_text(surf, "（无）", (x, y), 11, S.DIM2)

    def _draw_right(self, surf, rect, core, view, cell):
        S.panel(surf, pygame.Rect(rect.x - 8, rect.y - 6, rect.w + 8, rect.h + 12),
                S.PANEL, S.LINE, 10)
        x = rect.x
        y = rect.y + 2
        if self.level["blocks"].get("preview", True):
            R.draw_next(surf, core, pygame.Rect(x, y, rect.w - 6, 74))
            y += 82
        rows = [
            ("倒计时", f"{max(0.0, core.aim_t):.1f}s" if core.piece else "—"),
            ("落点速度", f"{core.fall_interval():.2f}s/格"),
            ("已固化", f"{core.lock_count} 块"),
            ("用时", f"{core.elapsed:.1f}s"),
        ]
        if core.concurrent() > 1:
            rows.insert(1, ("在场方块", f"{len(core.pieces)} / {core.concurrent()}"))
        for k, v in rows:
            S.draw_text(surf, k, (x, y), 12, S.DIM2)
            img = S.font(12, True).render(str(v), True, S.TEXT)
            surf.blit(img, (x + rect.w - 6 - img.get_width(), y))
            y += 18

        y += 6
        S.draw_text(surf, "舞台", (x, y), 12, S.DIM2)
        y += 18
        stats = [
            ("尺寸", f"{core.stage.w} × {core.stage.h}"),
            ("堆高", f"第 {core.stage.highest_solid_row()} 行"),
            ("瞄准", {"follow": "跟随小人", "manual": "玩家控制",
                      "random": "随机"}.get(core.level["blocks"].get("hover"), "跟随")),
            ("音乐", (core.audio.bgm_name or "—") if core.audio else "—"),
        ]
        for k, v in stats:
            S.draw_text(surf, k, (x, y), 12, S.DIM2)
            img = S.font(12).render(str(v), True, S.TEXT)
            surf.blit(img, (x + rect.w - 6 - img.get_width(), y))
            y += 18

        y += 8
        # 高度尺
        S.draw_text(surf, "高度标尺", (x, y), 12, S.DIM2)
        y += 16
        bar = pygame.Rect(x, y, rect.w - 6, 110)
        S.round_rect(surf, bar, S.BG2, 6)
        S.round_rect(surf, bar, S.LINE, 6, 1)
        goal_row = core.goal_row_value() if core.level["goal"].get(
            "type") == "reach_row" else None
        for i in range(core.stage.h):
            ry = bar.bottom - (i + 1) * (bar.h / core.stage.h)
            if i == core.actor.top_row:
                pygame.draw.line(surf, S.ACCENT, (bar.x + 2, ry + bar.h / core.stage.h / 2),
                                 (bar.right - 2, ry + bar.h / core.stage.h / 2), 3)
            elif goal_row is not None and i == goal_row:
                pygame.draw.line(surf, S.GOLD, (bar.x + 2, ry), (bar.right - 2, ry), 2)
        # 已占用比例微缩
        for r in range(core.stage.h):
            filled = sum(1 for v in core.stage.grid[r] if v != 0)
            if filled:
                rw = int((bar.w - 8) * filled / core.stage.w)
                ry = bar.bottom - (r + 1) * (bar.h / core.stage.h)
                pygame.draw.rect(surf, S.blend(S.PANEL3, 1.2),
                                 pygame.Rect(bar.x + 4, ry + 1, rw,
                                             max(1, bar.h / core.stage.h - 2)))

    def _draw_dialogue(self, surf, rect, core):
        st = core.runner.current
        if st is None or core.hide_dialogue:
            # 仍然显示 toasts
            self._draw_toasts(surf, rect, core)
            return
        text = st.text
        if not text and not st.speaker:
            self._draw_toasts(surf, rect, core)
            return
        ui.draw_dialogue(surf, rect, st.speaker, text, self.t,
                         core.blocking and not core.runner.waiting)
        self._draw_toasts(surf, rect, core)

    def _draw_toasts(self, surf, rect, core):
        y = rect.y - 26
        for t, life, c in core.toast[-4:]:
            img = S.font(12, True).render(t, True, c)
            tw = img.get_width() + 16
            S.round_rect(surf, pygame.Rect(rect.right - tw, y, tw, 20), S.PANEL2, 6)
            surf.blit(img, (rect.right - tw + 8, y + 3))
            y -= 24

    def _draw_pause_badge(self, surf, view):
        """阻塞对白期间：在舞台上方给出明确的「演出暂停」提示。"""
        ov = pygame.Surface((view.w, view.h), pygame.SRCALPHA)
        ov.fill((10, 13, 20, 70))
        surf.blit(ov, view.topleft)
        label = "演出暂停 · 按空格 / 点击 / 方向键 继续"
        fnt = S.font(13, True)
        tw = fnt.size(label)[0] + 26
        rect = pygame.Rect(view.centerx - tw // 2, view.y - 30, tw, 26)
        S.round_rect(surf, rect, S.PANEL2, 13)
        S.round_rect(surf, rect, S.ACCENT, 13, 1)
        S.draw_text(surf, label, (rect.centerx, rect.centery), 13, S.ACCENT, True,
                    anchor="center")

    def _draw_focus_lost(self, surf, w, h):
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        ov.fill((8, 10, 16, 168))
        surf.blit(ov, (0, 0))
        S.draw_text(surf, "窗口失去焦点，演出已暂停", (w // 2, h // 2 - 26), 26,
                    S.TEXT, True, anchor="center")
        S.draw_text(surf, "点回游戏窗口即可继续", (w // 2, h // 2 + 10), 14, S.DIM,
                    anchor="center")

    def _draw_pause(self, surf, w, h):
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        ov.fill((8, 10, 16, 170))
        surf.blit(ov, (0, 0))
        S.draw_text(surf, "暂停", (w // 2, h // 2 - 30), 34, S.TEXT, True, anchor="center")
        S.draw_text(surf, "P 继续 · R 重来 · Esc 返回", (w // 2, h // 2 + 12),
                    14, S.DIM, anchor="center")

    def _draw_result(self, surf, w, h, core):
        res = core.result
        win = res["kind"] == "win"
        k = min(1.0, self.result_time * 3.0)
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        ov.fill((8, 10, 16, int(150 * k)))
        surf.blit(ov, (0, 0))
        bw, bh = 460, 224
        rect = pygame.Rect(w // 2 - bw // 2, h // 2 - bh // 2, bw, bh)
        S.round_rect(surf, rect, S.PANEL, 14)
        S.round_rect(surf, rect, S.GOOD if win else S.BAD, 14, 2)

        head = "演出成功" if win else "演出终止"
        S.draw_text(surf, head, (rect.centerx, rect.y + 26), 30,
                    S.GOOD if win else S.BAD, True, anchor="midtop")
        S.draw_text(surf, res.get("text", "") or ("登顶成功" if win else "败北"),
                    (rect.centerx, rect.y + 70), 16, S.TEXT, anchor="midtop")
        reason = {"crush": "被下落的方块命中", "buried": "被困在封闭空间",
                  "stuck": "再也无法向上", "overflow": "舞台已被填满",
                  "script": "剧本判定失败"}.get(res.get("reason"), "")
        if reason:
            S.draw_text(surf, reason, (rect.centerx, rect.y + 96), 12, S.DIM2,
                        anchor="midtop")
        S.draw_text(surf, f"第 {core.best_row} 行 · 承受 {core.lock_count} 块 · "
                          f"{core.elapsed:.1f}s",
                    (rect.centerx, rect.y + 122), 13, S.DIM, anchor="midtop")

        if not self.buttons:
            bw2, bh2 = 130, 38
            cx = rect.centerx
            y = rect.bottom - 70
            self.buttons = [
                ui.Button(pygame.Rect(cx - bw2 - 8, y, bw2, bh2),
                          "再演一次", lambda: self.restart(), 15, "primary"),
                ui.Button(pygame.Rect(cx + 8, y, bw2, bh2), "返回菜单",
                          lambda: self.app.goto(MenuScene(self.app)), 15),
            ]
        if self.preview and self.app.editor_scene:
            self.buttons = [
                ui.Button(pygame.Rect(rect.centerx - 138, rect.bottom - 70, 130, 38),
                          "再演一次", lambda: self.restart(), 15, "primary"),
                ui.Button(pygame.Rect(rect.centerx + 8, rect.bottom - 70, 130, 38),
                          "回到编辑器", lambda: self.app.goto(self.app.editor_scene), 15),
            ]
        mouse = pygame.mouse.get_pos()
        for b in self.buttons:
            b.draw(surf, mouse)
        S.draw_text(surf, "空格 / 回车 快速继续", (rect.centerx, rect.bottom - 14),
                    11, S.DIM2, anchor="midbottom")


def default_level_data() -> dict:
    return {
        "id": "default",
        "title": "初次登场",
        "subtitle": "爬到舞台最顶端去",
        "author": "系统",
        "stage": {"width": 10, "height": 20},
        "blocks": {"pool": ["I", "O", "T", "S", "Z", "J", "L"], "allow_rotation": True,
                   "hover": "follow", "aim_time": [2.5, 8.0], "fall_interval": 0.30,
                   "fall_interval_min": 0.12, "ramp": 0.985, "preview": True},
        "player": {"spawn_col": None, "move_speed": 6.4, "jump_height": 2.6,
                   "gravity": 34.0, "climb": 1, "air_control": 1.0},
        "goal": {"type": "reach_row", "row": 0},
        "fail": {"text": "败北", "texts": {}, "crush": True, "buried": True,
                 "stuck": False, "overflow": True},
        "vfx": ["rain"],
        "events": {},
        "terrain": [],
        "tags": ["默认"],
    }
