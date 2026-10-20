"""内置编辑器：自定义舞台、玩法规则、形状、目标/失败条件、VFX、事件与剧本。"""
from __future__ import annotations

import copy
import json
import os

import pygame

from . import level as L
from . import render as R
from . import settings as S
from . import ui
from .audio import Audio, BGM_LABELS, SFX_LABELS, resolve_bgm, resolve_sfx
from .pieces import ALL_KINDS, Piece, color_of, register_shape, rotations_of, \
    unregister_shape
from .stage import CH_EMPTY, CH_WALL, Stage
from .vfx import ALL_VFX, RENDER_NAME

PALETTE = [("空", CH_EMPTY, None), ("墙", CH_WALL, S.WALL_COLOR)] + \
          [(k, str(i + 1), S.BLOCK_COLORS[i + 1]) for i, k in enumerate(ALL_KINDS)]

HOVER_LABELS = {"follow": "跟随小人", "manual": "玩家控制", "random": "随机落点"}
GOAL_LABELS = {"reach_row": "抵达顶层行", "survive": "坚持时间",
               "lock_count": "承受方块数", "none": "由剧本决定"}

TABS = ["基本", "玩法", "形状", "目标/失败", "VFX", "事件/剧本"]
TAB_BASIC, TAB_PLAY, TAB_SHAPE, TAB_GOAL, TAB_VFX, TAB_EVENT = range(len(TABS))
GRID_N = 6


class EditorScene:
    """编辑器场景（实现 Scene 接口，供 App 调度）。"""

    def __init__(self, app, level: L.Level | None = None):
        self.app = app
        self.level = level or L.Level(dict(L.DEFAULTS))
        self.stage = Stage(self.level.width, self.level.height)
        rows = self.level.get("terrain") or []
        if rows:
            self.stage.load_rows(rows)
        self.tab = 0
        self.brush = CH_EMPTY
        self.spawn_col = self.level["player"].get("spawn_col")
        if self.spawn_col is None:
            self.spawn_col = self.stage.w // 2
        self.focus = None
        self.t = 0.0
        self.hover_cell = None
        self.painting = False
        self.paint_button = 1
        self.row_n = max(0, self.level.goal_row + 1)
        self.message = ""
        self.message_life = 0.0
        self.event_rows = []
        self.cur_event_i = 0          # 当前编辑的事件序号
        self.cur_shape = 0            # 当前编辑的形状序号（内置在前）
        self.level.ensure_events_list()
        L.register_level_shapes(self.level)
        self.scroll = 0
        self._labels: list = []
        self._build()

    # ============================================================ 布局
    def _rects(self, w, h):
        right_w = 420
        top_y = 26
        top = pygame.Rect(16, top_y, w - 32, 32)
        canvas = pygame.Rect(16, 118, w - right_w - 40, h - 118 - 40)
        pal = pygame.Rect(16, 66, w - right_w - 40, 40)
        right = pygame.Rect(w - right_w - 8, 66, right_w, h - 82)
        return {"canvas": canvas, "palette": pal, "right": right, "top": top}

    # ============================================================ 构建
    def _build(self):
        w, h = self.app.screen.get_size()
        rt = self._rects(w, h)
        self.inputs: list = []
        self.clicks: list = []

        # 右侧标签页
        r = rt["right"]
        tabs = TABS
        self.tab_buttons = []
        tw = (r.w - 8) // len(tabs)
        for i, name in enumerate(tabs):
            self.tab_buttons.append(
                ui.Button(pygame.Rect(r.x + i * tw, r.y, tw - 4, 28), name,
                          (lambda i=i: self._set_tab(i)), 13,
                          "primary" if i == self.tab else "ghost"))
        self.clicks += self.tab_buttons

        body = pygame.Rect(r.x, r.y + 36, r.w - 8, r.h - 36)
        self.body = body
        self._build_tab(body)

        # 顶栏：输入框按比例分配剩余宽度，按钮组固定在右侧，任何窗口宽度都不重叠
        top = rt["top"]
        gap = 6
        btn_sizes = [70, 76, 56, 56, 56, 58, 60]   # 保存/另存为/载入/导入/导出/试演/返回
        need = sum(btn_sizes) + gap * (len(btn_sizes) - 1)
        if top.width - need < 300:                 # 窄窗口：整体等比缩小按钮
            k = max(0.68, (top.width - 300) / max(1, need))
            btn_sizes = [max(40, int(s * k)) for s in btn_sizes]
        btn_total = sum(btn_sizes) + gap * (len(btn_sizes) - 1)
        avail = max(260, top.width - btn_total - 14)
        total = max(220, avail - 3 * gap)      # 预留 3 个间隙，避免与按钮组相撞
        ratios = (0.21, 0.30, 0.31, 0.18)
        widths = [int(total * r) for r in ratios]
        widths[-1] = total - sum(widths[:-1])  # 保证总和恰好等于可用宽度
        x = top.x
        rects = []
        for wd in widths:
            rects.append(pygame.Rect(x, top.y, wd, 30))
            x += wd + gap
        self.in_id = ui.TextInput(rects[0], self.level.id, "关卡 ID", size=13)
        self.in_title = ui.TextInput(rects[1], self.level.get("title", ""), "演出标题",
                                    size=13)
        self.in_sub = ui.TextInput(rects[2], self.level.get("subtitle", ""), "副标题",
                                   size=13)
        self.in_author = ui.TextInput(rects[3], self.level.get("author", ""), "作者",
                                     size=13)
        self.inputs += [self.in_id, self.in_title, self.in_sub, self.in_author]

        bx = top.right - btn_total
        self.b_save = ui.Button(pygame.Rect(bx, top.y, btn_sizes[0], 30),
                                "保存", self.save, 13, "primary")
        bx += btn_sizes[0] + gap
        self.b_saveas = ui.Button(pygame.Rect(bx, top.y, btn_sizes[1], 30),
                                  "另存为", self.save_as, 13)
        bx += btn_sizes[1] + gap
        self.b_load = ui.Button(pygame.Rect(bx, top.y, btn_sizes[2], 30),
                                "载入", self.load_dialog, 12)
        bx += btn_sizes[2] + gap
        self.b_import = ui.Button(pygame.Rect(bx, top.y, btn_sizes[3], 30),
                                  "导入", self.import_file, 12)
        bx += btn_sizes[3] + gap
        self.b_export = ui.Button(pygame.Rect(bx, top.y, btn_sizes[4], 30),
                                  "导出", self.export_file, 12)
        bx += btn_sizes[4] + gap
        self.b_test = ui.Button(pygame.Rect(bx, top.y, btn_sizes[5], 30),
                                "试演", self.test, 13, "primary")
        bx += btn_sizes[5] + gap
        self.b_back = ui.Button(pygame.Rect(bx, top.y, btn_sizes[6], 30),
                                "返回", self.back, 13, "ghost")
        self.clicks += [self.b_save, self.b_saveas, self.b_load, self.b_import,
                        self.b_export, self.b_test, self.b_back]
        self._top_widgets = [self.in_id, self.in_title, self.in_sub, self.in_author,
                             self.b_save, self.b_saveas, self.b_load, self.b_import,
                             self.b_export, self.b_test, self.b_back]

    def _set_tab(self, i):
        if self.tab == i:
            return
        self._sync()
        self.tab = i
        self.scroll = 0
        self._build()
        self.tab = i

    def _build_tab(self, body):
        self._labels = []
        # 清掉上一个分页遗留的控件，避免叠加绘制
        from .ui import Widget as _W
        for name, val in list(vars(self).items()):
            if isinstance(val, _W):
                delattr(self, name)
        if self.focus is not None:
            self.focus = None
            pygame.key.stop_text_input()
        self.pool_toggles = []
        self.vfx_toggles = []
        self.event_rows = []
        self.shape_rows = []
        d = self.level.data
        blocks = d["blocks"]
        player = d["player"]
        goal = d["goal"]
        fail = d["fail"]
        cx = body.x + 4
        cw = body.w - 8
        y = body.y + 4

        def row(hgt=26, gap=4):
            nonlocal y
            r = pygame.Rect(cx, y, cw, hgt)
            y += hgt + gap
            return r

        if self.tab == 0:      # 基本
            self._label(cx, y, "舞台尺寸"); y += 16
            self.sw = ui.Stepper(row(28), "宽（格）", d["stage"]["width"], 4, 30, 1,
                                 self._resize_stage, "{:g}")
            self.sh = ui.Stepper(row(28), "高（格）", d["stage"]["height"], 6, 40, 1,
                                 self._resize_stage, "{:g}")
            y += 6
            self._label(cx, y, "失败文本（未定义时显示“败北”）"); y += 16
            self.in_fail = ui.TextInput(row(28), fail.get("text", "败北"), size=13)
            self.inputs.append(self.in_fail)
            y += 8
            for key, lab in (("crush", "被方块命中时"), ("buried", "被封困时"),
                             ("stuck", "无法上行时"), ("overflow", "舞台填满时")):
                self._label(cx, y, lab, 11, S.DIM2); y += 15
                ti = ui.TextInput((cx, y, cw, 24), (fail.get("texts") or {}).get(key, ""),
                                  "沿用上方失败文本", size=12)
                self.inputs.append(ti)
                setattr(self, "in_ft_" + key, ti)
                y += 30
            y += 4
            self._label(cx, y, "画笔：先在左侧调色板选色，再在舞台上拖动绘制地形；"
                               "右键 / 退格擦除。", 11, S.DIM2)
            y += 18
            self._label(cx, y, "提示：按住 Shift 点击舞台可设置小人出生列。", 11, S.PURPLE)

        elif self.tab == 1:    # 玩法
            self._label(cx, y, "方块"); y += 16
            self.c_hover = ui.Choice(row(28), "瞄准方式",
                                     ["follow", "manual", "random"],
                                     ["follow", "manual", "random"].index(
                                         blocks.get("hover", "follow")),
                                     None, HOVER_LABELS)
            self.t_rot = ui.Toggle(row(26), "允许随机旋转",
                                   bool(blocks.get("allow_rotation", True)))
            self.t_prot = ui.Toggle(row(26), "玩家可旋转方块（X 键）",
                                    bool(blocks.get("player_rotate", True)))
            self.t_prev = ui.Toggle(row(26), "显示下一块预览",
                                    bool(blocks.get("preview", True)))
            self.st_conc = ui.Stepper(row(26), "同时在场的方块数",
                                      int(blocks.get("concurrent", 1) or 1),
                                      1, 6, 1, None, "{:g}")
            self.st_gap = ui.Stepper(row(26), "多块生成间隔（秒）",
                                     float(blocks.get("spawn_gap", 0.35) or 0.35),
                                     0.05, 3.0, 0.05, None, "{:.2f}")
            self.st_aimlo = ui.Stepper(row(26), "倒计时下限（秒）",
                                       float(blocks.get("aim_time", [2, 9.9])[0]),
                                       0.5, 9.9, 0.5, None, "{:.1f}")
            self.st_aimhi = ui.Stepper(row(26), "倒计时上限（<10 秒）",
                                       float(blocks.get("aim_time", [2, 9.9])[1]),
                                       1.0, 9.9, 0.5, None, "{:.1f}")
            self.st_fall = ui.Stepper(row(26), "下落间隔（秒/格）",
                                      float(blocks.get("fall_interval", 0.3)),
                                      0.05, 2.0, 0.05, None, "{:.2f}")
            self.st_fallmin = ui.Stepper(row(26), "最短下落间隔",
                                         float(blocks.get("fall_interval_min", 0.1)),
                                         0.02, 1.0, 0.02, None, "{:.2f}")
            self.st_ramp = ui.Stepper(row(26), "固化后加速系数",
                                      float(blocks.get("ramp", 0.985)),
                                      0.9, 1.0, 0.005, None, "{:.3f}")
            y += 8
            self._label(cx, y, "方块池（至少保留一种，含自定义形状）"); y += 16
            pool = set(blocks.get("pool") or [])
            self.pool_toggles = []
            bx = cx
            kinds = list(ALL_KINDS) + [str(s["id"]) for s in self.level.shapes_list()]
            for k in kinds:
                tw = max(58, min(140, len(str(k)) * 10 + 30))
                if bx + tw > cx + cw:
                    bx = cx
                    y += 26
                tg = ui.Toggle(pygame.Rect(bx, y, tw, 22), str(k), str(k) in pool)
                tg.kind_tag = str(k)
                self.pool_toggles.append(tg)
                bx += tw + 6
            y += 30
            self._label(cx, y, "小人"); y += 16
            self.st_move = ui.Stepper(row(26), "移动速度（格/秒）",
                                      float(player.get("move_speed", 6.2)),
                                      1.0, 20.0, 0.2, None, "{:.1f}")
            self.st_jump = ui.Stepper(row(26), "跳跃高度（格）",
                                      float(player.get("jump_height", 2.15)),
                                      1.0, 5.0, 0.05, None, "{:.2f}")
            self.st_grav = ui.Stepper(row(26), "重力", float(player.get("gravity", 34.0)),
                                      5.0, 80.0, 1.0, None, "{:g}")
            self.st_climb = ui.Stepper(row(26), "可自动攀爬（格）",
                                       int(player.get("climb", 1)), 0, 3, 1, None, "{:g}")
            self.st_spawn = ui.Stepper(row(26), "出生列（0 起）", int(self.spawn_col),
                                       0, max(0, d["stage"]["width"] - 1), 1,
                                       self._set_spawn, "{:g}")
            y += 8
            self._label(cx, y, "音频（开演后自动循环播放）"); y += 16
            bgm_names = [""] + Audio.list_bgm()
            bgm_labels = ["（无）"] + [
                f"{BGM_LABELS.get(n, n)} · {n}" for n in Audio.list_bgm()]
            cur_bgm = (d.get("audio") or {}).get("bgm", "") or ""
            self.c_bgm = ui.Choice(row(28), "开演音乐", bgm_names,
                                   bgm_names.index(cur_bgm) if cur_bgm in bgm_names else 0,
                                   self._apply_bgm, bgm_labels)
            self.st_vol = ui.Stepper(pygame.Rect(cx, y, cw - 240, 26), "音量",
                                     int((d.get("audio") or {}).get("volume", 100)),
                                     0, 100, 5, self._set_vol, "{:g}")
            self.b_bgtest = ui.Button(pygame.Rect(cx + cw - 234, y, 112, 26), "试听",
                                      self._test_bgm, 12)
            self.b_bgstop = ui.Button(pygame.Rect(cx + cw - 116, y, 112, 26), "停止",
                                      self._stop_bgm, 12)
            y += 30

        elif self.tab == TAB_SHAPE:    # 形状
            self._label(cx, y, "形状（内置 7 种只读，自定义可编辑）"); y += 16
            items = self._shape_items()
            self.shape_rows = []
            for i, (sid, name, sub, custom) in enumerate(items):
                rect = pygame.Rect(cx, y, cw, 24)
                rr = ui.ListRow(rect, name, sub, (lambda k=i: self._pick_shape(k)),
                                i == self.cur_shape, "自定义" if custom else "内置")
                self.shape_rows.append(rr)
                self.clicks.append(rr)
                y += 26
            y += 4
            self.b_shnew = ui.Button(pygame.Rect(cx, y, 62, 26), "＋新建",
                                     self._new_shape, 12, "primary")
            self.b_shdup = ui.Button(pygame.Rect(cx + 68, y, 54, 26), "复制",
                                     self._dup_shape, 12)
            self.b_shdel = ui.Button(pygame.Rect(cx + 128, y, 54, 26), "删除",
                                     self._del_shape, 12, "danger")
            y += 32
            cur = self._cur_shape_info()
            self.in_shname = ui.TextInput(pygame.Rect(cx, y, cw, 26),
                                          str(cur.get("name") or ""), "形状名称",
                                          size=13, cb=self._write_shape_name)
            self.inputs.append(self.in_shname)
            y += 32
            self.c_shcolor = ui.ColorChoice(pygame.Rect(cx, y, cw, 26), "颜色",
                                            S.SHAPE_COLOR_IDS,
                                            S.SHAPE_COLOR_IDS.index(cur["color"])
                                            if cur["color"] in S.SHAPE_COLOR_IDS else 0,
                                            self._write_shape_color,
                                            S.SHAPE_COLOR_NAMES)
            y += 32
            self._label(cx, y, f"格子：点击切换（{GRID_N}×{GRID_N}，"
                               f"剧本可用 drop {cur.get('id', '')} 调用）", 11, S.DIM2)
            y += 16
            grid_h = min(180, max(120, cw // 3))
            self.grid = ui.GridEditor(pygame.Rect(cx, y, cw, grid_h), GRID_N, GRID_N,
                                      cur.get("cells"), self._write_shape_cells)
            self.grid.locked = not cur.get("custom", False)
            y += grid_h + 6
            y += 4
            self._label(cx, y, "提示：形状会自动生成 4 个朝向；在「玩法」页把它勾进方块池，"
                               "或用 drop 指令直接投放。", 11, S.DIM2)
            y += 30

        elif self.tab == TAB_GOAL:    # 目标 / 失败
            self._label(cx, y, "胜利条件"); y += 16
            keys = list(GOAL_LABELS.keys())
            self.c_goal = ui.Choice(row(28), "类型", keys,
                                    keys.index(goal.get("type", "reach_row")),
                                    None, [GOAL_LABELS[k] for k in keys])
            self.st_grow = ui.Stepper(row(26), "目标行（0 = 舞台顶部）",
                                      int(goal.get("row", 0)), 0,
                                      max(0, d["stage"]["height"] - 1), 1, None, "{:g}")
            self.st_gsec = ui.Stepper(row(26), "坚持秒数", int(goal.get("seconds", 60)),
                                      5, 600, 5, None, "{:g}")
            self.st_gcnt = ui.Stepper(row(26), "承受方块数", int(goal.get("count", 20)),
                                      1, 200, 1, None, "{:g}")
            y += 10
            self._label(cx, y, "失败条件（命中即立即终止演出）"); y += 16
            self.t_crush = ui.Toggle(row(26), "被下落的方块命中",
                                     bool(fail.get("crush", True)),
                                     hint="PRD 默认开启")
            self.t_buried = ui.Toggle(row(26), "被困在封闭空间内",
                                      bool(fail.get("buried", True)),
                                      hint="墙壁/边界算")
            self.t_stuck = ui.Toggle(row(26), "再也爬不上去",
                                     bool(fail.get("stuck", False)))
            self.t_over = ui.Toggle(row(26), "舞台被填满",
                                    bool(fail.get("overflow", True)))
            y += 8
            self._label(cx, y, "说明：勾选后才会计入失败判定；取消勾选则该情形不再终止演出。",
                        11, S.DIM2)

        elif self.tab == TAB_VFX:    # VFX
            self._label(cx, y, "点击开关视觉特效（可在剧本中用 vfx 指令动态开关）")
            y += 20
            enabled = set(d.get("vfx") or [])
            self.vfx_toggles = []
            bx = cx
            for name in ALL_VFX:
                tw = (cw - 12) // 2
                if bx + tw > cx + cw:
                    bx = cx
                    y += 30
                tg = ui.Toggle(pygame.Rect(bx, y, tw, 24),
                               f"{RENDER_NAME.get(name, name)} · {name}",
                               name in enabled)
                tg.vfx_name = name
                self.vfx_toggles.append(tg)
                bx += tw + 6
            y += 34
            self._label(cx, y, "已启用的 VFX 会写入关卡，演出一开始即生效。", 11, S.DIM2)

        else:                  # 事件 / 剧本（可无限增加，触发时机可自定义）
            evs = self.level.ensure_events_list()
            self._label(cx, y, f"事件列表（{len(evs)} 条 · 可无限增加）")
            y += 16
            self.event_rows = []
            for i, ev in enumerate(evs):
                lab = L.trigger_label(ev.get("trigger"), ev.get("param"))
                have = bool(str(ev.get("script", "")).strip())
                rr = ui.ListRow(pygame.Rect(cx, y, cw, 26), f"{i + 1}. {lab}",
                                "已编写" if have else "空",
                                (lambda k=i: self._pick_event(k)),
                                i == self.cur_event_i, "●" if have else "")
                self.event_rows.append(rr)
                self.clicks.append(rr)
                y += 28
            self.b_evnew = ui.Button(pygame.Rect(cx, y, 66, 26), "＋新增",
                                     self._new_event, 12, "primary")
            self.b_evdup = ui.Button(pygame.Rect(cx + 72, y, 54, 26), "复制",
                                     self._dup_event, 12)
            self.b_evdel = ui.Button(pygame.Rect(cx + 132, y, 54, 26), "删除",
                                     self._del_event, 12, "danger")
            y += 32
            ev = evs[self.cur_event_i] if 0 <= self.cur_event_i < len(evs) else None
            if ev is None:
                self._label(cx, y, "还没有事件：点「＋新增」添加一条，"
                                   "再选触发时机并写剧本。", 12, S.DIM2)
                y += 24
            else:
                trig = str(ev.get("trigger") or "on_lock")
                idx = L.TRIGGER_KEYS.index(trig) if trig in L.TRIGGER_KEYS else 0
                self.c_etrig = ui.Choice(row(26), "触发时机", L.TRIGGER_KEYS, idx,
                                         self._change_trigger,
                                         [L.trigger_name(t) for t in L.TRIGGER_KEYS])
                kind = L.TRIGGER_KINDS.get(trig)
                if kind == "int":
                    unit = "秒" if trig == "on_time" else ""
                    self.st_eparam = ui.Stepper(
                        row(26), f"参数{f'（{unit}）' if unit else ''}",
                        int(ev.get("param") or 0), 0,
                        max(0, d["stage"]["height"] - 1) if trig in ("on_row", "on_height")
                        else 600, 1, self._change_param, "{:g}")
                elif kind == "float":
                    self.st_eparam = ui.Stepper(row(26), "参数（秒）",
                                                float(ev.get("param") or 0),
                                                0, 600, 0.5, self._change_param, "{:.1f}")
                elif kind == "shape":
                    kinds = list(ALL_KINDS) + [str(s["id"])
                                               for s in self.level.shapes_list()]
                    cur = str(ev.get("param") or kinds[0])
                    if cur not in kinds:
                        kinds.append(cur)
                    self.c_eparam = ui.Choice(row(26), "形状", kinds,
                                              kinds.index(cur), self._change_param)
                elif kind == "key":
                    self.in_eparam = ui.TextInput(row(26),
                                                  str(ev.get("param") or "space"),
                                                  "按键名（如 x / space）", size=13)
                    self.inputs.append(self.in_eparam)
                self.t_eonce = ui.Toggle(row(24), "只触发一次",
                                         bool(ev.get("once", True)),
                                         self._change_once)
                self.c_mode = ui.Choice(row(26), "演出方式", list(L.MODES),
                                        0 if str(ev.get("mode")) == "ambient" else 1,
                                        None, [L.MODE_LABELS[m] for m in L.MODES])
                avail = body.bottom - y - 104
                self.ta = ui.TextArea(pygame.Rect(cx, y, cw, max(80, avail)),
                                      str(ev.get("script", "")), size=13)
                self.inputs.append(self.ta)
                y += max(80, avail) + 4

            # 投放方块助手：把 drop <形状> <列> 插进当前剧本行
            kinds = list(ALL_KINDS) + [str(s["id"]) for s in self.level.shapes_list()]
            self.c_dkind = ui.Choice(pygame.Rect(cx, body.bottom - 94, 96, 26),
                                     "形状", kinds, 0, None)
            self.st_dcol = ui.Stepper(pygame.Rect(cx + 102, body.bottom - 94, 90, 26),
                                      "列", 0, 0, max(0, d["stage"]["width"] - 1), 1,
                                      None, "{:g}")
            self.b_drop = ui.Button(pygame.Rect(cx + 198, body.bottom - 94, 76, 26),
                                    "插 drop", self._ins_drop, 12)
            self.clicks += [self.c_dkind, self.st_dcol, self.b_drop]

            # 音效 / 音乐插入助手
            sfx_names = Audio.list_sfx() + Audio.list_files()
            sfx_labels = [f"{SFX_LABELS.get(n, n)} · {n}" for n in Audio.list_sfx()] \
                + [f"文件 · {n}" for n in Audio.list_files()]
            self.c_snd = ui.Choice(pygame.Rect(cx, body.bottom - 62, cw - 200, 26),
                                   "音效", sfx_names, 0, None, sfx_labels)
            self.b_sndtest = ui.Button(pygame.Rect(cx + cw - 194, body.bottom - 62, 58, 26),
                                       "试听", self._test_sfx, 12)
            self.b_sndsfx = ui.Button(pygame.Rect(cx + cw - 132, body.bottom - 62, 62, 26),
                                      "插 sfx", self._ins_sfx, 12)
            self.b_sndbgm = ui.Button(pygame.Rect(cx + cw - 66, body.bottom - 62, 62, 26),
                                      "插 bgm", self._ins_bgm, 12)
            self.clicks += [self.c_snd, self.b_sndtest, self.b_sndsfx, self.b_sndbgm]

            stories = L.list_stories()
            if stories:
                names = [os.path.splitext(s)[0] for s in stories]
                self.c_story = ui.Choice(pygame.Rect(cx, body.bottom - 30, cw - 96, 26),
                                         "插入剧情文件", stories, 0, None, names)
                self.b_story = ui.Button(pygame.Rect(body.right - 92, body.bottom - 30,
                                                     88, 26), "载入", self._load_story, 12)
                self.clicks += [self.c_story, self.b_story]

        # 收集可点击控件
        for obj in list(vars(self).values()):
            if hasattr(obj, "handle_click") and hasattr(obj, "draw") \
                    and obj not in self.clicks and not isinstance(obj, (list, tuple)):
                if isinstance(obj, (ui.Button, ui.Toggle, ui.Choice, ui.Stepper,
                                    ui.ListRow, ui.GridEditor, ui.ColorChoice)):
                    self.clicks.append(obj)
        for tg in getattr(self, "pool_toggles", []) + getattr(self, "vfx_toggles", []) \
                + getattr(self, "shape_rows", []):
            if tg not in self.clicks:
                self.clicks.append(tg)

        # 内容总高（用于滚动）
        self.content_h = max(0, y - body.y)
        self.scroll = max(0, min(self.scroll, self.max_scroll()))

    # -------------------------------------------------- 滚动
    def max_scroll(self) -> int:
        return max(0, self.content_h - self.body.h)

    def _top_set(self) -> set:
        return set(getattr(self, "_top_widgets", []))

    def _body_widgets(self) -> list:
        """属于右侧面板、随滚动平移的控件（不含顶栏与分页按钮）。"""
        top = self._top_set()
        out = [w for w in self.clicks
               if w not in top and w not in self.tab_buttons
               and getattr(w, "rect", None) is not None]
        out += [w for w in self.inputs if w not in top
                and getattr(w, "rect", None) is not None]
        return out

    @staticmethod
    def _shift(wi, dy: int):
        """临时平移控件矩形用于绘制 / 命中检测，返回待还原的快照。"""
        if not dy:
            return None
        saved = [wi.rect]
        wi.rect = wi.rect.move(0, -dy)
        if hasattr(wi, "minus"):
            saved += [wi.minus, wi.plus]
            wi.minus = wi.minus.move(0, -dy)
            wi.plus = wi.plus.move(0, -dy)
        return saved

    @staticmethod
    def _unshift(wi, saved) -> None:
        if not saved:
            return
        wi.rect = saved[0]
        if len(saved) > 2:
            wi.minus = saved[1]
            wi.plus = saved[2]

    def _label(self, x, y, s, size=12, color=S.DIM2):
        self._labels.append(ui.Label(pygame.Rect(x, y, 10, 10), s, size, color))

    # ============================================================ 形状
    def _shapes(self) -> list:
        return self.level.data.setdefault("shapes", [])

    def _shape_items(self):
        """[(id, 列表标题, 副标题, 是否自定义)]：内置 7 种在前，自定义在后。"""
        out = []
        for k in ALL_KINDS:
            out.append((k, k, f"{len(rotations_of(k)[0])} 格 · 内置", False))
        for sh in self._shapes():
            n = L.normalize_shape(sh)
            if not n:
                continue
            out.append((n["id"], f"{n['name']}（{n['id']}）",
                        f"{len(n['cells'])} 格 · 色 {n['color']}", True))
        return out

    def _cur_shape(self):
        items = self._shape_items()
        if not items:
            return None
        self.cur_shape = max(0, min(len(items) - 1, self.cur_shape))
        return items[self.cur_shape]

    def _cur_shape_info(self) -> dict:
        info = {"id": "", "name": "", "color": 1, "cells": [], "custom": False}
        cur = self._cur_shape()
        if not cur:
            return info
        sid, _name, _sub, custom = cur
        info["id"] = sid
        info["custom"] = custom
        if custom:
            for sh in self._shapes():
                n = L.normalize_shape(sh)
                if n and n["id"] == sid:
                    info["name"] = n["name"]
                    info["color"] = n["color"]
                    info["cells"] = [tuple(c) for c in n["cells"]]
                    break
        else:
            info["name"] = sid
            info["color"] = color_of(sid)
            info["cells"] = rotations_of(sid)[0]
        return info

    def _uniq_shape_id(self) -> str:
        have = {str(s.get("id")) for s in self._shapes()} | set(ALL_KINDS)
        n = 1
        while f"sh{n}" in have:
            n += 1
        return f"sh{n}"

    def _patch_shape(self, sid, cells=None, name=None, color=None) -> bool:
        for sh in self._shapes():
            if str(sh.get("id")) != sid:
                continue
            if cells is not None:
                cells = [(int(x), int(y)) for x, y in cells] or [(0, 0)]
                sh["cells"] = [[x, y] for x, y in cells]
            if name is not None:
                sh["name"] = str(name)
            if color is not None:
                sh["color"] = int(color)
            n = L.normalize_shape(sh)
            if n:
                register_shape(n["id"], [tuple(c) for c in n["cells"]],
                               n["color"], n["name"])
            return True
        return False

    def _write_shape_cells(self, cells):
        cur = self._cur_shape()
        if cur and cur[3]:
            self._patch_shape(cur[0], cells=cells)

    def _write_shape_name(self, value):
        cur = self._cur_shape()
        if cur and cur[3]:
            self._patch_shape(cur[0], name=value)

    def _write_shape_color(self, value):
        cur = self._cur_shape()
        if cur and cur[3]:
            self._patch_shape(cur[0], color=value)

    def _pick_shape(self, i):
        self._sync()
        self.cur_shape = i
        self._build()

    def _new_shape(self):
        sid = self._uniq_shape_id()
        self._shapes().append({"id": sid, "name": "新形状", "color": 8,
                               "cells": [[0, 0], [1, 0]]})
        register_shape(sid, [(0, 0), (1, 0)], 8, "新形状")
        self.cur_shape = len(self._shape_items()) - 1
        self._build()
        self._flash(f"已新建形状 {sid}")

    def _dup_shape(self):
        info = self._cur_shape_info()
        if not info["id"]:
            return
        sid = self._uniq_shape_id()
        cells = info["cells"] or [(0, 0)]
        name = f"{info['name'] or info['id']} 副本"
        self._shapes().append({"id": sid, "name": name, "color": info["color"],
                               "cells": [[int(x), int(y)] for x, y in cells]})
        register_shape(sid, cells, info["color"], name)
        self.cur_shape = len(self._shape_items()) - 1
        self._build()
        self._flash(f"已复制为 {sid}")

    def _del_shape(self):
        cur = self._cur_shape()
        if not cur:
            return
        sid, _n, _s, custom = cur
        if not custom:
            self._flash("内置形状不可删除，可先「复制」再改")
            return
        self._shapes()[:] = [s for s in self._shapes() if str(s.get("id")) != sid]
        unregister_shape(sid)
        self.cur_shape = max(0, min(self.cur_shape, len(self._shape_items()) - 1))
        self._build()
        self._flash(f"已删除形状 {sid}")

    # ============================================================ 事件
    def _events(self) -> list:
        return self.level.ensure_events_list()

    def _pick_event(self, i):
        self._sync_event()
        self.cur_event_i = int(i)
        self._build()

    def _new_event(self):
        self._sync_event()
        evs = self._events()
        evs.append({"trigger": "on_lock", "param": None, "script": "",
                    "mode": "ambient", "once": True})
        self.cur_event_i = len(evs) - 1
        self._build()
        self._flash(f"已新增第 {len(evs)} 条事件")

    def _dup_event(self):
        self._sync_event()
        evs = self._events()
        if not (0 <= self.cur_event_i < len(evs)):
            return
        evs.append(copy.deepcopy(evs[self.cur_event_i]))
        self.cur_event_i = len(evs) - 1
        self._build()
        self._flash("已复制当前事件")

    def _del_event(self):
        evs = self._events()
        if not (0 <= self.cur_event_i < len(evs)):
            return
        evs.pop(self.cur_event_i)
        self.cur_event_i = max(0, min(self.cur_event_i, len(evs) - 1))
        self._build()
        self._flash("已删除该事件")

    def _change_trigger(self, value):
        self._sync_event()
        evs = self._events()
        if not (0 <= self.cur_event_i < len(evs)):
            return
        ev = evs[self.cur_event_i]
        ev["trigger"] = value
        kind = L.TRIGGER_KINDS.get(value)
        if kind == "int":
            ev["param"] = 0 if value in ("on_row", "on_height") else 1
        elif kind == "float":
            ev["param"] = 5.0
        elif kind == "shape":
            ev["param"] = "O"
        elif kind == "key":
            ev["param"] = "space"
        else:
            ev["param"] = None
        self._build()

    def _change_param(self, value):
        evs = self._events()
        if 0 <= self.cur_event_i < len(evs):
            evs[self.cur_event_i]["param"] = value

    def _change_once(self, value):
        evs = self._events()
        if 0 <= self.cur_event_i < len(evs):
            evs[self.cur_event_i]["once"] = bool(value)

    def _sync_event(self):
        evs = self._events()
        if not (0 <= self.cur_event_i < len(evs)):
            return
        ev = evs[self.cur_event_i]
        if hasattr(self, "c_etrig"):
            ev["trigger"] = self.c_etrig.value
        if hasattr(self, "st_eparam"):
            ev["param"] = self.st_eparam.value
        if hasattr(self, "c_eparam"):
            ev["param"] = self.c_eparam.value
        if hasattr(self, "in_eparam"):
            ev["param"] = (self.in_eparam.value.strip() or "space").lower()
        if hasattr(self, "t_eonce"):
            ev["once"] = bool(self.t_eonce.value)
        if hasattr(self, "c_mode"):
            ev["mode"] = self.c_mode.value
        if hasattr(self, "ta"):
            ev["script"] = self.ta.get()

    def _set_spawn(self, v):
        self.spawn_col = int(v)

    def _resize_stage(self, _=None):
        w = int(self.sw.value)
        h = int(self.sh.value)
        if (w, h) == (self.stage.w, self.stage.h):
            return
        self.stage.resize(w, h)
        self.level.data["stage"]["width"] = w
        self.level.data["stage"]["height"] = h
        self.spawn_col = max(0, min(w - 1, self.spawn_col))
        self.st_spawn.value = self.spawn_col
        self.message = f"舞台已调整为 {w} × {h}"
        self.message_life = 2.0

    # -------------------------------------------------- 音频
    def _audio(self):
        return getattr(self.app, "audio", None)

    def _apply_bgm(self, value):
        audio = self._audio()
        if audio and value:
            audio.bgm(resolve_bgm(value))
        elif audio:
            audio.stop_bgm()

    def _set_vol(self, value):
        audio = self._audio()
        if audio:
            audio.set_volume(max(0.0, min(1.0, float(value) / 100.0)))

    def _test_bgm(self):
        audio = self._audio()
        name = getattr(self, "c_bgm", None)
        name = name.value if name else ""
        if not audio:
            self._flash("音频不可用")
            return
        if not name:
            audio.stop_bgm()
            self._flash("已停止")
            return
        audio.bgm(resolve_bgm(name))
        self._flash("正在试听：" + name)

    def _stop_bgm(self):
        audio = self._audio()
        if audio:
            audio.stop_bgm()
            self._flash("已停止")

    def _test_sfx(self):
        audio = self._audio()
        name = getattr(self, "c_snd", None)
        name = name.value if name else ""
        if not audio:
            self._flash("音频不可用")
            return
        audio.play(resolve_sfx(name))
        self._flash("播放：" + name)

    def _insert_cmd(self, cmd: str) -> None:
        ta = getattr(self, "ta", None)
        if ta is None:
            return
        line = ta.lines[ta.row].rstrip()
        line = (line + "; " + cmd) if "\\" in line else (line + " \\ " + cmd)
        ta.lines[ta.row] = line
        ta.col = len(line)
        ta.focus = True
        self.focus = ta
        pygame.key.start_text_input()
        self._flash("已插入：" + cmd)

    def _ins_sfx(self):
        name = getattr(self, "c_snd", None)
        if name:
            self._insert_cmd("sfx " + name.value)

    def _ins_bgm(self):
        name = getattr(self, "c_snd", None)
        if name:
            self._insert_cmd("bgm " + name.value)

    def _ins_drop(self):
        kind = getattr(self, "c_dkind", None)
        col = getattr(self, "st_dcol", None)
        if kind is None or col is None:
            return
        self._insert_cmd(f"drop {kind.value} {int(col.value)}")

    def _load_story(self):
        path = self.c_story.value
        text = L.load_story(os.path.splitext(path)[0])
        cur = self.ta.get().strip()
        self.ta.set((cur + "\n" if cur else "") + text.strip())
        self.focus = self.ta
        self.message = f"已载入 {path}"
        self.message_life = 2.0

    def _sync(self):
        d = self.level.data
        d["id"] = self.in_id.value.strip() or "untitled"
        d["title"] = self.in_title.value.strip() or "未命名演出"
        d["subtitle"] = self.in_sub.value.strip()
        d["author"] = self.in_author.value.strip()
        d["stage"]["width"] = self.stage.w
        d["stage"]["height"] = self.stage.h
        d["terrain"] = self.stage.to_rows()

        if self.tab == 0:
            d["fail"]["text"] = self.in_fail.value.strip() or "败北"
            texts = {}
            for key in ("crush", "buried", "stuck", "overflow"):
                v = getattr(self, "in_ft_" + key, None)
                if v is not None and v.value.strip():
                    texts[key] = v.value.strip()
            d["fail"]["texts"] = texts

        elif self.tab == 1:
            b = d["blocks"]
            b["hover"] = self.c_hover.value
            b["allow_rotation"] = self.t_rot.value
            b["player_rotate"] = self.t_prot.value \
                if hasattr(self, "t_prot") else bool(b.get("player_rotate", True))
            b["preview"] = self.t_prev.value
            b["concurrent"] = int(getattr(self, "st_conc").value) \
                if hasattr(self, "st_conc") else int(b.get("concurrent", 1))
            b["spawn_gap"] = float(getattr(self, "st_gap").value) \
                if hasattr(self, "st_gap") else float(b.get("spawn_gap", 0.35))
            b["aim_time"] = [min(self.st_aimlo.value, self.st_aimhi.value),
                             max(self.st_aimlo.value, self.st_aimhi.value)]
            b["fall_interval"] = self.st_fall.value
            b["fall_interval_min"] = min(self.st_fallmin.value, self.st_fall.value)
            b["ramp"] = self.st_ramp.value
            pool = [tg.kind_tag for tg in self.pool_toggles if tg.value]
            b["pool"] = pool or ["O", "I"]
            p = d["player"]
            p["move_speed"] = self.st_move.value
            p["jump_height"] = self.st_jump.value
            p["gravity"] = self.st_grav.value
            p["climb"] = int(self.st_climb.value)
            p["spawn_col"] = int(self.spawn_col)
            if b["hover"] != "manual":
                p["spawn_col"] = None if p["spawn_col"] == d["stage"]["width"] // 2 \
                    else p["spawn_col"]
            cur = (d.get("audio") or {})
            d["audio"] = {"bgm": getattr(self, "c_bgm", None).value
                          if hasattr(self, "c_bgm") else cur.get("bgm", ""),
                          "volume": int(getattr(self, "st_vol").value)
                          if hasattr(self, "st_vol") else int(cur.get("volume", 100))}

        elif self.tab == TAB_SHAPE:
            if hasattr(self, "in_shname"):
                self._write_shape_name(self.in_shname.value)
            if hasattr(self, "c_shcolor"):
                self._write_shape_color(self.c_shcolor.value)

        elif self.tab == TAB_GOAL:
            d["goal"]["type"] = self.c_goal.value
            d["goal"]["row"] = int(self.st_grow.value)
            d["goal"]["seconds"] = int(self.st_gsec.value)
            d["goal"]["count"] = int(self.st_gcnt.value)
            f = d["fail"]
            f["crush"] = self.t_crush.value
            f["buried"] = self.t_buried.value
            f["stuck"] = self.t_stuck.value
            f["overflow"] = self.t_over.value

        elif self.tab == TAB_VFX:
            d["vfx"] = [tg.vfx_name for tg in self.vfx_toggles if tg.value]

        else:                                   # 事件 / 剧本
            self._sync_event()

    # ============================================================ 存档操作
    def save(self):
        self._sync()
        path = L.save_level(self.level, None if not self.level.path
                            else os.path.basename(self.level.path))
        self.level.path = path
        L.save_level(self.level)
        self.app.save.mark_seen(self.level.id)
        self.app.save.save()
        self._flash(f"已保存到 content/levels/{os.path.basename(path)}")

    def save_as(self):
        self._sync()
        base = L.safe_name(self.level.id) or "level"
        n = 1
        fn = base + ".json"
        while os.path.exists(os.path.join(S.LEVELS_DIR, fn)):
            n += 1
            fn = f"{base}_{n}.json"
        self.level.data["id"] = self.level.id + f"_{n}" if n > 1 else self.level.id
        self.level.path = None
        path = L.save_level(self.level, fn)
        if hasattr(self.app, "menu") and self.app.menu:
            self.app.menu.reload()
        self._flash(f"已另存为 {fn}")

    def load_dialog(self):
        """载入：循环切换到 content/levels 里的下一份演出。"""
        levels = L.list_levels()
        idx = 0
        for i, lv in enumerate(levels):
            if self.level.path and lv.path == self.level.path:
                idx = i
        nxt = levels[(idx + 1) % len(levels)] if levels else None
        if nxt:
            self._load_level_obj(L.Level(copy.deepcopy(nxt.data), nxt.path))
            self._flash(f"已载入 {self.level.title}")

    def _load_level_obj(self, lv: L.Level) -> None:
        lv.ensure_events_list()
        L.register_level_shapes(lv)
        self.level = lv
        self.stage = Stage(self.level.width, self.level.height)
        rows = self.level.get("terrain") or []
        if rows:
            self.stage.load_rows(rows)
        self.spawn_col = self.level["player"].get("spawn_col")
        if self.spawn_col is None:
            self.spawn_col = self.stage.w // 2
        self.row_n = max(0, self.level.goal_row + 1)
        self.cur_shape = 0
        self.cur_event_i = 0
        self.scroll = 0
        self._build()

    # -------------------------------------------------- 导入 / 导出
    @staticmethod
    def _file_dialog(save: bool = False, default_name: str = "") -> str:
        """用系统文件对话框选路径；不可用时返回空串（调用方走降级方案）。"""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:      # noqa: BLE001
                pass
            root.update()
            kw = {"initialdir": S.LEVELS_DIR,
                  "filetypes": [("演出文件", "*.json"), ("所有文件", "*.*")]}
            if save:
                path = filedialog.asksaveasfilename(
                    title="导出演出", initialfile=default_name,
                    defaultextension=".json", **kw)
            else:
                path = filedialog.askopenfilename(title="导入演出", **kw)
            try:
                root.destroy()
            except Exception:      # noqa: BLE001
                pass
            return str(path or "")
        except Exception:          # noqa: BLE001
            return ""

    @staticmethod
    def _exchange_dir(name: str) -> str:
        d = os.path.join(S.ROOT, name)
        os.makedirs(d, exist_ok=True)
        return d

    def import_file(self):
        self._sync()
        path = self._file_dialog(False)
        if not path:
            self._flash("未选择文件，改为从 import 目录读取")
            path = self._latest_in_dir(self._exchange_dir("import"))
        if not path:
            self._flash("没有可导入的文件（把 .json 放进 build/import 即可）")
            return
        lv = L.import_level(path)
        if lv is None:
            self._flash("导入失败：不是有效的演出 JSON")
            return
        self._load_level_obj(lv)
        self._flash(f"已导入 {lv.title}")

    def export_file(self):
        self._sync()
        name = L.safe_name(self.level.id) + ".json"
        path = self._file_dialog(True, name)
        if not path:
            path = os.path.join(self._exchange_dir("export"), name)
            self._flash("未选择路径，已导出到 build/export")
        if not path.lower().endswith(".json"):
            path += ".json"
        ok = L.export_level(self.level, path)
        self._flash("已导出：" + path if ok else "导出失败")

    @staticmethod
    def _latest_in_dir(d: str) -> str:
        try:
            fs = [os.path.join(d, f) for f in os.listdir(d)
                  if f.lower().endswith(".json")]
            if not fs:
                return ""
            return max(fs, key=os.path.getmtime)
        except OSError:
            return ""

    def test(self):
        self._sync()
        from .scenes import PlayScene
        data = copy.deepcopy(self.level.data)
        data["terrain"] = self.stage.to_rows()
        lv = L.Level(data)
        self.app.editor_scene = self
        self.app.goto(PlayScene(self.app, lv, preview=True))

    def back(self):
        from .scenes import MenuScene
        self.app.goto(MenuScene(self.app))

    def _flash(self, msg):
        self.message = msg
        self.message_life = 2.6

    # ============================================================ 事件
    def enter(self):
        self.app.editor_scene = self
        pygame.key.stop_text_input()

    def handle(self, ev):
        mouse = pygame.mouse.get_pos()
        w, h = self.app.screen.get_size()
        rt = self._rects(w, h)

        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == 3:
                self.brush = CH_EMPTY
                return
            handled = False
            # 顶栏与分页按钮：绝对坐标
            for wi in list(self._top_widgets) + list(self.tab_buttons):
                if hasattr(wi, "handle_click") and wi.handle_click(ev.pos):
                    handled = True
                    break
            # 面板内容：跟随滚动平移
            if not handled:
                local = (ev.pos[0], ev.pos[1] + self.scroll)
                for wi in self._body_widgets():
                    if hasattr(wi, "handle_click") and wi.handle_click(local):
                        handled = True
                        if isinstance(wi, (ui.Toggle, ui.Choice, ui.Stepper)):
                            self._after_widget(wi)
                        break
            if handled:
                self._set_focus_widget(ev.pos)
                return
            # 画布绘制
            if rt["canvas"].collidepoint(ev.pos):
                mods = pygame.key.get_mods()
                if mods & pygame.KMOD_SHIFT:
                    self._set_spawn_cell(ev.pos, rt["canvas"])
                    return
                self.painting = True
                self.paint_button = ev.button
                self._paint(ev.pos, rt["canvas"])
                self._set_focus_widget(ev.pos)
                return
            self._set_focus_widget(ev.pos)
            return

        if ev.type == pygame.MOUSEBUTTONUP:
            self.painting = False
            return

        if ev.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, min(self.max_scroll(), self.scroll - ev.y * 34))
            return

        if ev.type == pygame.MOUSEMOTION:
            self.hover_cell = self._cell_at(ev.pos, rt["canvas"])
            if self.painting and rt["canvas"].collidepoint(ev.pos):
                self._paint(ev.pos, rt["canvas"])
            return

        if ev.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            if mods & pygame.KMOD_CTRL:
                if ev.key == pygame.K_s:
                    self.save()
                    return
                if ev.key == pygame.K_e:
                    self.test()
                    return
            if ev.key == pygame.K_ESCAPE:
                self.back()
                return
            if ev.key == pygame.K_TAB:
                self._set_tab((self.tab + 1) % len(TABS))
                return
            if ev.key == pygame.K_F1:
                self.focus = None
                pygame.key.stop_text_input()
                return
        # 文本输入
        if self.focus is not None:
            self.focus.handle(ev)

    def _set_focus_widget(self, pos):
        new = None
        top = self._top_set()
        for wi in self.inputs:
            r = wi.rect if wi in top else wi.rect.move(0, -self.scroll)
            if r.collidepoint(pos):
                new = wi
        if new is not self.focus:
            if self.focus is not None:
                self.focus.focus = False
            self.focus = new
            if new is not None:
                new.focus = True
                pygame.key.start_text_input()
            else:
                pygame.key.stop_text_input()

    def _after_widget(self, wi):
        if wi is getattr(self, "sw", None) or wi is getattr(self, "sh", None):
            self._resize_stage()
        if wi is getattr(self, "c_goal", None):
            pass

    def update(self, dt):
        self.t += dt
        self.scroll = max(0, min(self.max_scroll(), self.scroll))
        if self.message_life > 0:
            self.message_life -= dt

    # ============================================================ 画布
    def _cell_at(self, pos, canvas):
        pad = 14
        area = canvas.inflate(-pad * 2, -pad * 2)
        total_rows = self.stage.h + R.TOP_ROWS
        cell = min(area.w // max(self.stage.w, 1), area.h // max(total_rows, 1))
        cell = max(8, min(cell, 40))
        w = cell * self.stage.w
        hh = cell * self.stage.h
        x = area.x + (area.w - w) // 2
        y = area.y + (area.h - hh - cell * R.TOP_ROWS) // 2 + cell * R.TOP_ROWS
        c = (pos[0] - x) // cell
        r = (pos[1] - y) // cell
        if 0 <= c < self.stage.w and 0 <= r < self.stage.h:
            return int(c), int(r)
        return None

    def _view(self, canvas):
        pad = 14
        area = canvas.inflate(-pad * 2, -pad * 2)
        return R.make_view(area, self.stage.w, self.stage.h, max_cell=40)

    def _set_spawn_cell(self, pos, canvas):
        cell_pos = self._cell_at(pos, canvas)
        if not cell_pos:
            return
        self.spawn_col = cell_pos[0]
        if hasattr(self, "st_spawn"):
            self.st_spawn.value = self.spawn_col
        self._flash(f"出生列设为 {self.spawn_col}")

    def _paint(self, pos, canvas):
        cell_pos = self._cell_at(pos, canvas)
        if not cell_pos:
            return
        c, r = cell_pos
        if self.paint_button == 3:
            self.stage.grid[r][c] = 0
        else:
            ch = self.brush
            if ch == CH_EMPTY:
                self.stage.grid[r][c] = 0
            elif ch == CH_WALL:
                self.stage.grid[r][c] = -1
            else:
                self.stage.grid[r][c] = int(ch)

    # ============================================================ 绘制
    def draw(self, surf):
        w, h = surf.get_size()
        rt = self._rects(w, h)
        mouse = pygame.mouse.get_pos()
        surf.fill(S.BG)

        # 顶部
        for wi in (self.in_id, self.in_title, self.in_sub, self.in_author):
            wi.draw(surf, mouse)
        for b in (self.b_save, self.b_saveas, self.b_load, self.b_import,
                  self.b_export, self.b_test, self.b_back):
            b.draw(surf, mouse)
        S.draw_text(surf, "演出编辑器", (rt["top"].x - 2, 6), 13, S.DIM2, True)

        # 调色板
        pal = rt["palette"]
        S.panel(surf, pal, S.PANEL, S.LINE, 8)
        x = pal.x + 8
        for label, ch, color in PALETTE:
            img = S.font(12).render(label, True, S.TEXT)
            bwid = max(46, img.get_width() + 26)
            r = pygame.Rect(x, pal.y + 6, bwid, pal.h - 12)
            sel = (self.brush == ch)
            S.round_rect(surf, r, S.blend(S.PANEL2, 1.3 if sel else 1.0), 6)
            S.round_rect(surf, r, S.ACCENT if sel else S.LINE, 6, 1)
            if color is not None:
                sw = pygame.Rect(r.x + 6, r.centery - 6, 12, 12)
                S.round_rect(surf, sw, color, 3)
            surf.blit(img, (r.x + 22, r.centery - img.get_height() // 2))
            if r.collidepoint(mouse) and pygame.mouse.get_pressed()[0]:
                self.brush = ch
            x += bwid + 6
            if x + bwid > pal.right:
                break
        S.draw_text(surf, "右键 = 擦除", (x + 8, pal.centery), 11, S.DIM2, anchor="midleft")

        # 画布
        canvas = rt["canvas"]
        S.panel(surf, canvas, S.BG2, S.LINE, 10)
        view, cell = self._view(canvas)
        fake = self._fake_core()
        R.draw_stage_bg(surf, fake, view, cell, self.t)
        R.draw_stage_blocks(surf, fake, view, cell, self.t)

        # 出生点标记
        sr = self.stage.h - 1
        for r in range(self.stage.h):
            if self.stage.grid[r][self.spawn_col] != 0:
                sr = max(0, r - 1)
                break
        mark = pygame.Rect(view.x + self.spawn_col * cell + 2, view.y + sr * cell + 2,
                           cell - 4, cell - 4)
        S.round_rect(surf, mark, S.GOOD, 4, 2)
        S.draw_text(surf, "出生", (mark.centerx, mark.centery), max(9, int(cell * 0.34)),
                    (10, 20, 14), True, anchor="center")

        # 悬停格
        if self.hover_cell and canvas.collidepoint(mouse):
            c, r = self.hover_cell
            hr = pygame.Rect(view.x + c * cell, view.y + r * cell, cell, cell)
            pygame.draw.rect(surf, S.ACCENT, hr, 2, border_radius=3)

        # 右侧
        r = rt["right"]
        S.panel(surf, r, S.PANEL, S.LINE, 10)
        for b in self.tab_buttons:
            b.draw(surf, mouse)

        # 面板内容（可滚动，超出部分裁剪）
        dy = self.scroll
        old_clip = surf.get_clip()
        surf.set_clip(self.body)
        local_mouse = (mouse[0], mouse[1] + dy)
        for lbl in self._labels:
            saved = self._shift(lbl, dy)
            lbl.draw(surf, local_mouse)
            self._unshift(lbl, saved)
        for wi in self._body_widgets():
            saved = self._shift(wi, dy)
            wi.draw(surf, local_mouse)
            self._unshift(wi, saved)
        surf.set_clip(old_clip)
        self._draw_scrollbar(surf)

        if self.message_life > 0 and self.message:
            img = S.font(13, True).render(self.message, True, S.GOOD)
            tw = img.get_width() + 20
            bg = pygame.Rect(canvas.centerx - tw // 2, canvas.bottom + 6, tw, 26)
            S.round_rect(surf, bg, S.PANEL2, 8)
            S.round_rect(surf, bg, S.GOOD, 8, 1)
            surf.blit(img, (bg.x + 10, bg.centery - img.get_height() // 2))

        ui.draw_hint_bar(surf, pygame.Rect(16, h - 30, max(200, r.x - 40), 22), [
            ("Ctrl+S", "保存"), ("Ctrl+E", "试演"), ("Tab", "切换分页"),
            ("右键", "擦除"), ("Shift+点击", "出生列"), ("Esc", "返回"),
        ], 11)

    def _draw_scrollbar(self, surf) -> None:
        mx = self.max_scroll()
        if mx <= 0:
            return
        body = self.body
        track = pygame.Rect(body.right - 5, body.y + 2, 4, body.h - 4)
        S.round_rect(surf, track, S.PANEL3, 2)
        k = body.h / (body.h + mx)
        th = max(24, int(track.h * k))
        ty = track.y + int((track.h - th) * (self.scroll / mx))
        S.round_rect(surf, pygame.Rect(track.x, ty, track.w, th), S.ACCENT, 2)

    def _fake_core(self):
        """给 render 用的轻量替身，仅含 level / stage 字段。"""

        class _C:
            pass

        c = _C()
        c.level = self.level
        c.stage = self.stage
        return c
