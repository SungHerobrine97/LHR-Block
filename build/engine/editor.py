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
               "lock_count": "承受方块数", "clear_lines": "消除行数",
               "none": "由剧本决定"}

TABS = ["基本", "玩法", "形状", "目标/失败", "VFX", "事件/剧本"]
TAB_BASIC, TAB_PLAY, TAB_SHAPE, TAB_GOAL, TAB_VFX, TAB_EVENT = range(len(TABS))
TAB_LABELS = ["基本", "玩法", "形状", "目标", "VFX", "剧本"]
GRID_N = 6

HELP_LINES = [
    "Ctrl+S 保存 · Ctrl+E 试演 · Tab 切换左侧标签页 · Esc 返回菜单",
    "中间舞台：左键用当前画笔绘制地形，右键擦除，Shift+点击设置出生列",
    "左侧「剧本」页管理事件与脚本；右侧常驻显示当前事件的触发属性",
    "F1 打开 / 关闭本帮助 · 文件菜单可保存、载入、导入、导出与返回",
]


class EditorScene:
    """编辑器场景（实现 Scene 接口，供 App 调度）。"""

    def __init__(self, app, level: L.Level | None = None):
        self.app = app
        self.level = level or L.Level(dict(L.DEFAULTS))
        _a0 = getattr(app, "audio", None)
        if _a0:
            _a0.set_level_dir(L.level_root(self.level))
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
        self.scroll = 0                  # 左侧标签页内容的滚动
        self.prop_scroll = 0             # 右侧事件属性栏的滚动
        self._drag_scroll = None         # 左键拖动滚动条：(区域, 抓取偏移, body, content_h)
        self.help_open = False
        self._built_size = None
        self.left_widgets: list = []
        self.prop_widgets: list = []
        self.meta_widgets: list = []
        self.chrome_widgets: list = []
        self.brush_rects: list = []
        self._labels: list = []
        self._prop_labels: list = []
        self._build()

    # ============================================================ 布局
    def _rects(self, w, h):
        """草图布局：顶部菜单 + 左侧标签页 + 中间游戏画面 + 右侧事件属性。"""
        m = 8
        gap = 10
        top_h = 28
        tab_h = 24
        bottom = h - 34
        left_w = max(190, min(252, int(w * 0.22)))
        right_w = max(206, min(286, int(w * 0.22)))
        left = pygame.Rect(m, top_h + tab_h, left_w,
                           max(120, bottom - top_h - tab_h - m))
        tabs = pygame.Rect(m, top_h, left_w, tab_h)
        right_x = w - m - right_w
        center_x = left.right + gap
        center = pygame.Rect(center_x, top_h,
                             max(180, right_x - gap - center_x),
                             max(120, bottom - top_h - m))
        right = pygame.Rect(right_x, top_h, right_w,
                            max(120, bottom - top_h - m))
        meta = pygame.Rect(left.x + 8, left.y + 6, left.w - 16, 52)
        left_body = pygame.Rect(left.x + 8, meta.bottom + 8,
                                left.w - 16,
                                max(80, left.bottom - 8 - (meta.bottom + 8)))
        right_body = pygame.Rect(right.x + 8, right.y + 30,
                                 right.w - 16,
                                 max(80, right.bottom - 8 - (right.y + 30)))
        pal = pygame.Rect(center.x + 8, center.bottom - 36, center.w - 16, 28)
        stage = pygame.Rect(center.x + 8, center.y + 8,
                            center.w - 16,
                            max(80, pal.y - 8 - (center.y + 8)))
        return {
            "left": left, "tabs": tabs, "left_body": left_body, "meta": meta,
            "canvas": center, "stage": stage, "palette": pal,
            "right": right, "right_body": right_body,
            "menu": pygame.Rect(m, 5, w - 100, 20),
            "test": pygame.Rect(w - 82, 3, 74, 25),
        }

    # ============================================================ 构建
    def _build(self):
        w, h = self.app.screen.get_size()
        if getattr(self, "_built_size", None) and self._built_size != (w, h):
            # 窗口缩放时先把当前控件里的修改写回数据，避免重建后丢失
            self._sync()
        self._built_size = (w, h)
        rt = self._rects(w, h)
        if getattr(self, "focus", None) is not None:
            self.focus = None
            pygame.key.stop_text_input()

        self.inputs: list = []
        self.clicks: list = []
        self._labels = []
        self._prop_labels = []
        self.brush_rects = []

        # 左侧标签页（草图中标签位于左栏上方）
        self.tab_buttons = []
        tw = max(28, rt["tabs"].w // len(TABS))
        for i, name in enumerate(TAB_LABELS):
            self.tab_buttons.append(
                ui.Button(pygame.Rect(rt["tabs"].x + i * tw, rt["tabs"].y,
                                      tw - 2, rt["tabs"].h), name,
                          (lambda i=i: self._set_tab(i)), 11,
                          "primary" if i == self.tab else "ghost"))

        # 左侧页内容
        self.body = rt["left_body"]
        self._build_tab(rt["left_body"])
        # 列表型控件（事件行、形状行、方块池 / VFX 开关）只存在列表里，
        # 不能只靠扫描实例属性，否则它们不会被绘制和命中。
        left_existing = list(self.clicks)
        for group in (getattr(self, "event_rows", []),
                      getattr(self, "shape_rows", []),
                      getattr(self, "pool_toggles", []),
                      getattr(self, "vfx_toggles", [])):
            for wi in group:
                if wi not in left_existing:
                    left_existing.append(wi)
        for wi in self._collect_widgets():
            if wi not in left_existing:
                left_existing.append(wi)

        # 顶栏与关卡信息（在标签内容之后创建，避免被分页重建清掉）
        self._build_chrome(rt)
        chrome = [self.menubar, self.b_test] + self.meta_widgets

        # 右侧事件属性常驻
        self.prop_body = rt["right_body"]
        self._build_event_props(rt["right_body"])
        all_widgets = self._collect_widgets()
        self.left_widgets = [wi for wi in left_existing if wi not in chrome]
        self.prop_widgets = [wi for wi in all_widgets
                             if wi not in left_existing and wi not in chrome]
        self.clicks = (self.left_widgets + self.prop_widgets + chrome
                       + self.tab_buttons)
        self.chrome_widgets = chrome

        self.scroll = max(0, min(self.scroll, self.max_left_scroll()))
        self.prop_scroll = max(0, min(self.prop_scroll, self.max_prop_scroll()))

    def _collect_widgets(self) -> list:
        from .ui import Widget as _W
        return [v for v in vars(self).values() if isinstance(v, _W)]

    def _build_chrome(self, rt):
        self.menubar = ui.MenuBar(rt["menu"], self._menu_defs(), 12)
        self.b_test = ui.Button(rt["test"], "试演", self.test, 12, "primary")
        m = rt["meta"]
        mh = 23
        mw = (m.w - 6) // 2
        r1 = pygame.Rect(m.x, m.y, mw, mh)
        r2 = pygame.Rect(m.x + mw + 6, m.y, mw, mh)
        r3 = pygame.Rect(m.x, m.y + mh + 4, mw, mh)
        r4 = pygame.Rect(m.x + mw + 6, m.y + mh + 4, mw, mh)
        self.in_id = ui.TextInput(r1, self.level.id, "关卡 ID", size=11)
        self.in_title = ui.TextInput(r2, self.level.get("title", ""), "演出标题",
                                     size=11)
        self.in_sub = ui.TextInput(r3, self.level.get("subtitle", ""), "副标题",
                                   size=11)
        self.in_author = ui.TextInput(r4, self.level.get("author", ""), "作者",
                                      size=11)
        self.meta_widgets = [self.in_id, self.in_title, self.in_sub, self.in_author]
        self.inputs += self.meta_widgets

    def _menu_defs(self):
        return [
            ("文件", [
                {"label": "保存", "shortcut": "Ctrl+S", "cb": self.save},
                {"label": "另存为", "cb": self.save_as},
                {"label": "载入下一关", "cb": self.load_dialog},
                "---",
                {"label": "导入演出", "cb": self.import_file},
                {"label": "导出演出", "cb": self.export_file},
                "---",
                {"label": "返回菜单", "shortcut": "Esc", "cb": self.back},
            ]),
            ("编辑", [
                {"label": "上一页", "cb": lambda: self._set_tab(
                    (self.tab - 1) % len(TABS))},
                {"label": "下一页", "shortcut": "Tab", "cb": lambda: self._set_tab(
                    (self.tab + 1) % len(TABS))},
                "---",
                {"label": "新增剧本事件", "cb": self._new_event},
                {"label": "复制当前事件", "cb": self._dup_event},
                {"label": "删除当前事件", "cb": self._del_event},
            ]),
            ("帮助", [
                {"label": "快捷键说明", "shortcut": "F1",
                 "cb": self._toggle_help},
                {"label": "关于编辑器", "cb": lambda: self._flash(
                    f"虚质方块二创编辑器 v{S.APP_VERSION}")},
            ]),
        ]

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
        # 先断开焦点引用：它可能正指向下面要删掉的控件
        if getattr(self, "focus", None) is not None:
            self.focus = None
            pygame.key.stop_text_input()
        # 清掉上一个分页遗留的控件，避免叠加绘制
        from .ui import Widget as _W
        for name, val in list(vars(self).items()):
            if isinstance(val, _W):
                delattr(self, name)
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
            self._label(cx, y, "画笔在画布底部；左键绘制，右键擦除", 11, S.DIM2)
            y += 18
            self._label(cx, y, "Shift+点击舞台设置出生列", 11, S.PURPLE)

        elif self.tab == 1:    # 玩法
            self._label(cx, y, "方块"); y += 16
            self.c_hover = ui.Choice(row(28), "瞄准方式",
                                     ["follow", "manual", "random"],
                                     ["follow", "manual", "random"].index(
                                         blocks.get("hover", "follow")),
                                     None, HOVER_LABELS)
            self.t_rot = ui.Toggle(row(26), "允许随机旋转",
                                   bool(blocks.get("allow_rotation", True)))
            self.t_prot = ui.Toggle(row(26), "玩家可旋转（X）",
                                    bool(blocks.get("player_rotate", True)))
            self.t_quick = ui.Toggle(row(26), "玩家可催落（↓/S）",
                                     bool(blocks.get("quick_drop", True)))
            self.t_line = ui.Toggle(row(26), "填满一行即消行",
                                    bool(blocks.get("line_clear", False)))
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
            _audio = self._audio()
            bgm_pool = _audio.list_bgm() if _audio else list(BGM_LABELS)
            bgm_names = [""] + bgm_pool
            bgm_labels = ["（无）"] + [
                f"{BGM_LABELS.get(n, n)} · {n}" for n in bgm_pool]
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
            self.b_impaudio = ui.Button(pygame.Rect(cx, y, cw, 24),
                                        "导入音频到本关卡（复制进关卡目录）",
                                        self._import_audio, 11)
            y += 28

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
            self._label(cx, y, f"格子 {GRID_N}×{GRID_N} · drop {cur.get('id', '')}",
                        11, S.DIM2)
            y += 16
            grid_h = min(180, max(120, cw // 3))
            self.grid = ui.GridEditor(pygame.Rect(cx, y, cw, grid_h), GRID_N, GRID_N,
                                      cur.get("cells"), self._write_shape_cells)
            self.grid.locked = not cur.get("custom", False)
            y += grid_h + 6
            y += 4
            self._label(cx, y, "提示：自动生成 4 个朝向，可入池或 drop 投放",
                        11, S.DIM2)
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
            self.st_gclear = ui.Stepper(row(26), "消除行数", int(goal.get("clear", 6)),
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
            self._label(cx, y, "勾选后才计入失败判定", 11, S.DIM2)

        elif self.tab == TAB_VFX:    # VFX
            self._label(cx, y, "点击开关 VFX（剧本可用 vfx 指令切换）", 11)
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
                               RENDER_NAME.get(name, name), name in enabled)
                tg.vfx_name = name
                self.vfx_toggles.append(tg)
                bx += tw + 6
            y += 34
            self._label(cx, y, "启用后演出开始即生效", 11, S.DIM2)

        else:                  # 剧本：事件列表 + 脚本编辑（属性在右侧常驻）
            evs = self.level.ensure_events_list()
            self._label(cx, y, f"剧本事件（{len(evs)} 条）")
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
                self._label(cx, y, "还没有事件：点「＋新增」添加一条，触发属性在右侧设置。",
                            11, S.DIM2)
                y += 24
            else:
                self._label(cx, y, "事件脚本", 12, S.PURPLE)
                y += 18
                avail = body.bottom - y - 8
                self.ta = ui.TextArea(pygame.Rect(cx, y, cw, max(90, avail)),
                                      str(ev.get("script", "")), size=12)
                self.inputs.append(self.ta)
                y += max(90, avail) + 4

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

        # 内容总高（用于左侧滚动）
        self.left_content_h = max(0, y - body.y)
        self.scroll = max(0, min(self.scroll, self.max_left_scroll()))

    def _build_event_props(self, body):
        """右侧常驻：当前剧本事件的触发属性与指令插入助手。"""
        self._prop_labels = []
        prop_names = ("c_etrig", "st_eparam", "c_eparam", "in_eparam",
                      "t_eonce", "c_mode", "c_dkind", "st_dcol", "b_drop",
                      "c_snd", "b_sndtest", "b_sndsfx", "b_sndbgm",
                      "c_story", "b_story")
        for name in prop_names:
            old = getattr(self, name, None)
            if old is not None:
                if old in self.inputs:
                    self.inputs.remove(old)
                delattr(self, name)

        d = self.level.data
        cx = body.x + 2
        cw = body.w - 4
        y = body.y + 2

        def row(hgt=26, gap=5):
            nonlocal y
            r = pygame.Rect(cx, y, cw, hgt)
            y += hgt + gap
            return r

        evs = self.level.ensure_events_list()
        ev = evs[self.cur_event_i] if 0 <= self.cur_event_i < len(evs) else None
        if ev is None:
            self._prop_label(cx, y, "尚未选择事件", 12, S.DIM)
            y += 20
            self._prop_label(cx, y, "在左侧「剧本」页新增或选择一条事件后，",
                             11, S.DIM2)
            y += 16
            self._prop_label(cx, y, "这里会显示它的触发时机与参数。", 11, S.DIM2)
            y += 20
        else:
            summary = L.trigger_label(ev.get("trigger"), ev.get("param"))
            for line in S.wrap(summary, S.font(11, True), cw)[:2]:
                self._prop_label(cx, y, line, 11, S.PURPLE, True)
                y += 15
            y += 4
            trig = str(ev.get("trigger") or "on_lock")
            idx = L.TRIGGER_KEYS.index(trig) if trig in L.TRIGGER_KEYS else 0
            self.c_etrig = ui.Choice(row(26), "触发时机", L.TRIGGER_KEYS, idx,
                                     self._change_trigger,
                                     [L.trigger_name(t) for t in L.TRIGGER_KEYS])
            kind = L.TRIGGER_KINDS.get(trig)
            if kind == "int":
                hi = (max(0, d["stage"]["height"] - 1)
                      if trig in ("on_row", "on_height") else 600)
                self.st_eparam = ui.Stepper(row(26), "参数", int(ev.get("param") or 0),
                                            0, hi, 1, self._change_param, "{:g}")
            elif kind == "float":
                self.st_eparam = ui.Stepper(row(26), "秒数",
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
                                              "按键名（如 x / space）", size=11)
                self.inputs.append(self.in_eparam)
            self.t_eonce = ui.Toggle(row(24), "只触发一次",
                                     bool(ev.get("once", True)), self._change_once)
            self.c_mode = ui.Choice(row(26), "演出方式", list(L.MODES),
                                    0 if str(ev.get("mode")) == "ambient" else 1,
                                    None, ["自动", "确认"])
            y += 6

        self._prop_label(cx, y, "插入指令到当前脚本", 12, S.ACCENT, True)
        y += 20
        kinds = list(ALL_KINDS) + [str(s["id"]) for s in self.level.shapes_list()]
        self.c_dkind = ui.Choice(row(26), "形状", kinds, 0, None)
        self.st_dcol = ui.Stepper(row(26), "投放列", 0, 0,
                                  max(0, d["stage"]["width"] - 1), 1, None, "{:g}")
        self.b_drop = ui.Button(pygame.Rect(cx, y, cw, 24),
                                "插入 drop", self._ins_drop, 11, "primary")
        y += 30

        _audio = self._audio()
        level_files = _audio.list_files() if _audio else []
        sfx_names = Audio.list_sfx() + level_files
        sfx_labels = [f"{SFX_LABELS.get(n, n)} · {n}" for n in Audio.list_sfx()] \
            + [f"文件 · {n}" for n in level_files]
        self.c_snd = ui.Choice(row(26), "音效", sfx_names, 0, None, sfx_labels)
        bw = (cw - 8) // 3
        self.b_sndtest = ui.Button(pygame.Rect(cx, y, bw, 24),
                                   "试听", self._test_sfx, 11)
        self.b_sndsfx = ui.Button(pygame.Rect(cx + bw + 4, y, bw, 24),
                                  "插 sfx", self._ins_sfx, 11)
        self.b_sndbgm = ui.Button(pygame.Rect(cx + (bw + 4) * 2, y, bw, 24),
                                  "插 bgm", self._ins_bgm, 11)
        y += 30

        stories = L.list_stories()
        if stories:
            names = [os.path.splitext(s)[0] for s in stories]
            self.c_story = ui.Choice(row(26), "剧情", stories, 0, None, names)
            self.b_story = ui.Button(pygame.Rect(cx, y, cw, 24),
                                     "载入剧情文件", self._load_story, 11)
            y += 30

        self.prop_content_h = max(0, y - body.y)
        self.prop_scroll = max(0, min(self.prop_scroll, self.max_prop_scroll()))

    # -------------------------------------------------- 滚动
    def max_left_scroll(self) -> int:
        return max(0, getattr(self, "left_content_h", 0) - self.body.h)

    def max_prop_scroll(self) -> int:
        return max(0, getattr(self, "prop_content_h", 0) - self.prop_body.h)

    def _body_widgets(self) -> list:
        """左侧分页中随纵向滚动的控件。"""
        return [wi for wi in self.left_widgets
                if getattr(wi, "rect", None) is not None]

    def _prop_widgets(self) -> list:
        """右侧事件属性栏中随纵向滚动的控件。"""
        return [wi for wi in self.prop_widgets
                if getattr(wi, "rect", None) is not None]

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

    def _prop_label(self, x, y, s, size=12, color=S.DIM2, bold=False):
        self._prop_labels.append(
            ui.Label(pygame.Rect(x, y, 10, 10), s, size, color, bold))

    def _toggle_help(self):
        self.help_open = not self.help_open

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
        self._sync()
        self.cur_event_i = int(i)
        self._build()

    def _new_event(self):
        self._sync()
        evs = self._events()
        evs.append({"trigger": "on_lock", "param": None, "script": "",
                    "mode": "ambient", "once": True})
        self.cur_event_i = len(evs) - 1
        self.tab = TAB_EVENT
        self.scroll = 0
        self._build()
        self._flash(f"已新增第 {len(evs)} 条事件")

    def _dup_event(self):
        self._sync()
        evs = self._events()
        if not (0 <= self.cur_event_i < len(evs)):
            self._flash("没有可复制的事件")
            return
        evs.append(copy.deepcopy(evs[self.cur_event_i]))
        self.cur_event_i = len(evs) - 1
        self.tab = TAB_EVENT
        self._build()
        self._flash("已复制当前事件")

    def _del_event(self):
        self._sync()
        evs = self._events()
        if not (0 <= self.cur_event_i < len(evs)):
            self._flash("没有可删除的事件")
            return
        evs.pop(self.cur_event_i)
        self.cur_event_i = max(0, min(self.cur_event_i, len(evs) - 1))
        self.tab = TAB_EVENT
        self._build()
        self._flash("已删除该事件")

    def _change_trigger(self, value):
        self._sync()
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

    def _val(self, name, default=None):
        """安全读取某个控件的值：控件可能属于别的分页（尚未创建）。"""
        w = getattr(self, name, None)
        if w is None:
            return default
        return getattr(w, "value", default)

    def _resize_stage(self, _=None):
        w = int(self._val("sw", self.stage.w))
        h = int(self._val("sh", self.stage.h))
        w = max(4, min(30, w))
        h = max(6, min(40, h))
        if (w, h) == (self.stage.w, self.stage.h):
            return
        self.stage.resize(w, h)
        self.level.data["stage"]["width"] = w
        self.level.data["stage"]["height"] = h
        self.spawn_col = max(0, min(w - 1, self.spawn_col))
        # 出生列步进器只在「玩法」页存在，这里必须容错
        if hasattr(self, "st_spawn"):
            self.st_spawn.value = self.spawn_col
        self.message = f"舞台已调整为 {w} × {h}"
        self.message_life = 2.0

    # -------------------------------------------------- 音频
    def _audio(self):
        return getattr(self.app, "audio", None)

    def _level_audio_dir(self) -> str:
        d = L.level_root(self.level)
        os.makedirs(d, exist_ok=True)
        return d

    def _import_audio(self):
        """从系统对话框挑一个音频文件，复制进当前关卡的目录。"""
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
            path = filedialog.askopenfilename(
                title="导入音频到关卡目录",
                filetypes=[("音频文件", "*.ogg *.wav *.mp3"),
                           ("所有文件", "*.*")])
            try:
                root.destroy()
            except Exception:      # noqa: BLE001
                pass
        except Exception:          # noqa: BLE001
            path = ""
        if not path:
            self._flash("未选择文件；也可手动把音频放进关卡目录")
            return
        stem = Audio.import_audio(path, self._level_audio_dir())
        if not stem:
            self._flash("不支持的音频格式（支持 .ogg/.wav/.mp3）")
            return
        audio = self._audio()
        if audio:
            audio.set_level_dir(L.level_root(self.level))
        self._build()
        self._flash(f"已导入音频：{stem}（保存在关卡目录）")

    def _bundle_level_audio(self):
        """把本关引用的音频文件复制进关卡目录，让关卡自包含。"""
        audio = self._audio()
        if not audio:
            return
        dest = self._level_audio_dir()
        saved = 0
        # 开演音乐
        cfg = self.level.data.get("audio") or {}
        names = set()
        bgm = str(cfg.get("bgm", "") or "").strip()
        if bgm and bgm.lower() not in ("off", "stop", "none", "0", "停"):
            names.add(bgm)
        # 剧本里的 sfx / bgm 指令
        for ev in self.level.events_list():
            script = str(ev.get("script", "") or "")
            for chunk in script.replace("\\", ";").split(";"):
                parts = chunk.strip().split()
                if len(parts) >= 2 and parts[0].lower() in ("sfx", "bgm"):
                    nm = parts[1].strip()
                    if nm and nm.lower() not in ("off", "stop", "none", "0", "停"):
                        names.add(nm)
        for name in names:
            if audio.save_audio_to_level(name, dest):
                saved += 1
        return saved

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

    def _ensure_script_editor(self):
        """右侧助手插入指令时，确保左侧「剧本」页的脚本框已经打开。"""
        ta = getattr(self, "ta", None)
        if ta is not None:
            return ta
        self._sync()
        self.tab = TAB_EVENT
        self.scroll = 0
        self._build()
        return getattr(self, "ta", None)

    def _insert_cmd(self, cmd: str, ta=None) -> None:
        ta = ta if ta is not None else self._ensure_script_editor()
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
            value = name.value
            self._insert_cmd("sfx " + value)

    def _ins_bgm(self):
        name = getattr(self, "c_snd", None)
        if name:
            value = name.value
            self._insert_cmd("bgm " + value)

    def _ins_drop(self):
        kind = getattr(self, "c_dkind", None)
        col = getattr(self, "st_dcol", None)
        if kind is None or col is None:
            return
        k, c = kind.value, int(col.value)
        self._insert_cmd(f"drop {k} {c}")

    def _load_story(self):
        story = getattr(self, "c_story", None)
        if story is None:
            return
        path = story.value
        text = L.load_story(os.path.splitext(path)[0])
        ta = self._ensure_script_editor()
        if ta is None:
            return
        cur = ta.get().strip()
        ta.set((cur + "\n" if cur else "") + text.strip())
        self.focus = ta
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

        if self.tab == TAB_BASIC:
            d["fail"]["text"] = str(self._val("in_fail", "") or "").strip() or "败北"
            texts = {}
            for key in ("crush", "buried", "stuck", "overflow"):
                v = getattr(self, "in_ft_" + key, None)
                if v is not None and v.value.strip():
                    texts[key] = v.value.strip()
            d["fail"]["texts"] = texts

        elif self.tab == TAB_PLAY:
            b = d["blocks"]
            b["hover"] = self._val("c_hover", b.get("hover", "follow"))
            b["allow_rotation"] = bool(self._val("t_rot", True))
            b["player_rotate"] = bool(self._val("t_prot", True))
            b["quick_drop"] = bool(self._val("t_quick", True))
            b["line_clear"] = bool(self._val("t_line", False))
            b["preview"] = bool(self._val("t_prev", True))
            b["concurrent"] = max(1, min(8, int(self._val("st_conc", 1))))
            b["spawn_gap"] = max(0.05, min(5.0, float(self._val("st_gap", 0.35))))
            lo = float(self._val("st_aimlo", 2.0))
            hi = float(self._val("st_aimhi", 9.9))
            b["aim_time"] = [min(lo, hi), max(lo, hi)]
            b["fall_interval"] = float(self._val("st_fall", 0.3))
            b["fall_interval_min"] = min(float(self._val("st_fallmin", 0.1)),
                                         b["fall_interval"])
            b["ramp"] = float(self._val("st_ramp", 0.985))
            pool = [tg.kind_tag for tg in getattr(self, "pool_toggles", []) if tg.value]
            if pool:
                b["pool"] = pool
            p = d["player"]
            p["move_speed"] = float(self._val("st_move", p.get("move_speed", 6.4)))
            p["jump_height"] = float(self._val("st_jump", p.get("jump_height", 2.6)))
            p["gravity"] = float(self._val("st_grav", p.get("gravity", 34.0)))
            p["climb"] = int(self._val("st_climb", p.get("climb", 1)))
            p["spawn_col"] = int(self.spawn_col)
            if b["hover"] != "manual":
                p["spawn_col"] = None if p["spawn_col"] == d["stage"]["width"] // 2 \
                    else p["spawn_col"]
            cur = (d.get("audio") or {})
            d["audio"] = {"bgm": self._val("c_bgm", cur.get("bgm", "")),
                          "volume": int(self._val("st_vol", cur.get("volume", 100)))}

        elif self.tab == TAB_SHAPE:
            if hasattr(self, "in_shname"):
                self._write_shape_name(self.in_shname.value)
            if hasattr(self, "c_shcolor"):
                self._write_shape_color(self.c_shcolor.value)

        elif self.tab == TAB_GOAL:
            d["goal"]["type"] = self._val("c_goal", d["goal"].get("type", "reach_row"))
            d["goal"]["row"] = int(self._val("st_grow", d["goal"].get("row", 0)))
            d["goal"]["seconds"] = int(self._val("st_gsec", d["goal"].get("seconds", 60)))
            d["goal"]["count"] = int(self._val("st_gcnt", d["goal"].get("count", 20)))
            d["goal"]["clear"] = int(self._val("st_gclear", d["goal"].get("clear", 6)))
            f = d["fail"]
            f["crush"] = bool(self._val("t_crush", f.get("crush", True)))
            f["buried"] = bool(self._val("t_buried", f.get("buried", True)))
            f["stuck"] = bool(self._val("t_stuck", f.get("stuck", False)))
            f["overflow"] = bool(self._val("t_over", f.get("overflow", False)))

        elif self.tab == TAB_VFX:
            d["vfx"] = [tg.vfx_name for tg in self.vfx_toggles if tg.value]

        else:                                   # 事件 / 剧本
            self._sync_event()

    # ============================================================ 存档操作
    def save(self):
        self._sync()
        path = L.save_level(self.level)
        self.level.path = path
        self._bundle_level_audio()
        audio = self._audio()
        if audio:
            audio.set_level_dir(L.level_root(self.level))
        self.app.save.mark_seen(self.level.id)
        self.app.save.save()
        if hasattr(self.app, "menu") and self.app.menu:
            self.app.menu.reload()
        self._flash(f"已保存到关卡目录：content/levels/{os.path.basename(os.path.dirname(path))}")

    def save_as(self):
        self._sync()
        base = L.safe_name(self.level.id) or "level"
        n = 1
        d = L.level_dir_for(base)
        while os.path.isdir(d):
            n += 1
            d = L.level_dir_for(f"{base}_{n}")
        self.level.data["id"] = self.level.id + f"_{n}" if n > 1 else self.level.id
        self.level.path = None
        path = L.save_level(self.level)
        self._bundle_level_audio()
        audio = self._audio()
        if audio:
            audio.set_level_dir(L.level_root(self.level))
        if hasattr(self.app, "menu") and self.app.menu:
            self.app.menu.reload()
        self._flash(f"已另存为关卡目录：{os.path.basename(os.path.dirname(path))}")

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
        self.prop_scroll = 0
        _a0 = getattr(self.app, "audio", None)
        if _a0:
            _a0.set_level_dir(L.level_root(lv))
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
        """统一兜底：任何控件异常都不应让整个程序退出。"""
        try:
            self._handle(ev)
        except Exception as exc:      # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._flash(f"操作出错（已忽略）：{type(exc).__name__}: {exc}")

    def _handle(self, ev):
        w, h = self.app.screen.get_size()
        rt = self._rects(w, h)

        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button in (2, 4, 5):      # 中键与旧式滚轮按键（4/5）一律不响应
                return
            if self.help_open:
                self.help_open = False
                return
            if ev.button == 1 and self._start_scroll_drag(ev.pos):
                return
            if self.menubar.handle_click(ev.pos):
                return
            if ev.button == 3:
                if rt["stage"].collidepoint(ev.pos):
                    self.painting = True
                    self.paint_button = 3
                    self._paint(ev.pos, rt["stage"])
                else:
                    self.brush = CH_EMPTY
                    self._flash("已切换为擦除：在舞台拖动即可清除地形")
                return
            # 中央画布底部的画笔条
            for r, ch in self.brush_rects:
                if r.collidepoint(ev.pos):
                    self.brush = ch
                    return
            handled = False
            # 固定位置的控件（试演、关卡信息、左侧标签）
            chrome = [self.b_test] + self.meta_widgets + self.tab_buttons
            for wi in chrome:
                if hasattr(wi, "handle_click") and wi.handle_click(ev.pos):
                    handled = True
                    break
            # 左侧分页内容：跟随左侧滚动
            if not handled:
                local = (ev.pos[0], ev.pos[1] + self.scroll)
                for wi in self._body_widgets():
                    if hasattr(wi, "handle_click") and wi.handle_click(local):
                        handled = True
                        if isinstance(wi, (ui.Toggle, ui.Choice, ui.Stepper)):
                            self._after_widget(wi)
                        break
            # 右侧事件属性：跟随右侧滚动
            if not handled:
                local = (ev.pos[0], ev.pos[1] + self.prop_scroll)
                for wi in self._prop_widgets():
                    if hasattr(wi, "handle_click") and wi.handle_click(local):
                        handled = True
                        if isinstance(wi, (ui.Toggle, ui.Choice, ui.Stepper)):
                            self._after_widget(wi)
                        break
            if handled:
                self._set_focus_widget(ev.pos)
                return
            # 舞台地形绘制
            if rt["stage"].collidepoint(ev.pos):
                mods = pygame.key.get_mods()
                if mods & pygame.KMOD_SHIFT:
                    self._set_spawn_cell(ev.pos, rt["stage"])
                    return
                self.painting = True
                self.paint_button = ev.button
                self._paint(ev.pos, rt["stage"])
            self._set_focus_widget(ev.pos)
            return

        if ev.type == pygame.MOUSEBUTTONUP:
            if self._drag_scroll:
                self._drag_scroll = None
                return
            if ev.button in (2, 4, 5):
                return
            self.painting = False
            return

        if ev.type == pygame.MOUSEWHEEL:
            # pygame 2 的滚轮事件不带 pos，用实时鼠标位置判定；滚轮绝不触发任何点击/绘制
            mouse = pygame.mouse.get_pos()
            ta = getattr(self, "ta", None)
            if (self.tab == TAB_EVENT and ta is not None
                    and (ta.rect.collidepoint(mouse) or self.focus is ta)):
                ta.scroll_by(-ev.y * 2)
            return

        if ev.type == pygame.MOUSEMOTION:
            if self._drag_scroll:
                self._move_scroll_drag(ev.pos[1])
                return
            self.hover_cell = self._cell_at(ev.pos, rt["stage"])
            if self.painting and rt["stage"].collidepoint(ev.pos):
                self._paint(ev.pos, rt["stage"])
            return

        if ev.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            if self.help_open:
                if ev.key in (pygame.K_ESCAPE, pygame.K_F1):
                    self.help_open = False
                return
            if ev.key == pygame.K_ESCAPE and self.menubar.open is not None:
                self.menubar.close()
                return
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
                self._toggle_help()
                return
        # 文本输入
        if getattr(self, "focus", None) is not None:
            self.focus.handle(ev)

    def _set_focus_widget(self, pos):
        new = None
        prop_set = set(self.prop_widgets)
        for wi in self.inputs:
            if wi in self.meta_widgets:
                r = wi.rect
            elif wi in prop_set:
                r = wi.rect.move(0, -self.prop_scroll)
            else:
                r = wi.rect.move(0, -self.scroll)
            if r.collidepoint(pos):
                new = wi
        old = getattr(self, "focus", None)
        if new is not old:
            if old is not None:
                old.focus = False
            self.focus = new
            if new is not None:
                new.focus = True
                pygame.key.start_text_input()
            else:
                pygame.key.stop_text_input()

    def _after_widget(self, wi):
        if wi is getattr(self, "sw", None) or wi is getattr(self, "sh", None):
            self._resize_stage()

    def update(self, dt):
        self.t += dt
        self.scroll = max(0, min(self.max_left_scroll(), self.scroll))
        self.prop_scroll = max(0, min(self.max_prop_scroll(), self.prop_scroll))
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

        # 左栏：标签页组 + 关卡信息 + 当前页内容
        S.panel(surf, rt["left"], S.PANEL, S.LINE, 10)
        for b in self.tab_buttons:
            b.draw(surf, mouse)
        for wi in self.meta_widgets:
            wi.draw(surf, mouse)
        self._draw_scrolled(surf, self.body, self._labels, self._body_widgets(),
                            self.scroll, mouse)
        self._draw_scrollbar(surf, self.body, self.scroll,
                             getattr(self, "left_content_h", 0))

        # 中央：游戏画面（地形预览）
        canvas = rt["canvas"]
        S.panel(surf, canvas, S.BG2, S.LINE, 10)
        stage = rt["stage"]
        view, cell = self._view(stage)
        fake = self._fake_core()
        R.draw_stage_bg(surf, fake, view, cell, self.t)
        R.draw_stage_blocks(surf, fake, view, cell, self.t)

        # 出生点标记
        sr = self.stage.h - 1
        for r in range(self.stage.h):
            if self.stage.grid[r][self.spawn_col] != 0:
                sr = max(0, r - 1)
                break
        mark = pygame.Rect(view.x + self.spawn_col * cell + 2,
                           view.y + sr * cell + 2, cell - 4, cell - 4)
        S.round_rect(surf, mark, S.GOOD, 4, 2)
        S.draw_text(surf, "出生", (mark.centerx, mark.centery),
                    max(9, int(cell * 0.34)), (10, 20, 14), True, anchor="center")

        if self.hover_cell and stage.collidepoint(mouse):
            c, r = self.hover_cell
            hr = pygame.Rect(view.x + c * cell, view.y + r * cell, cell, cell)
            pygame.draw.rect(surf, S.ACCENT, hr, 2, border_radius=3)
        self._draw_palette(surf, rt["palette"], mouse)

        # 右栏：常驻事件属性
        right = rt["right"]
        S.panel(surf, right, S.PANEL, S.LINE, 10)
        S.draw_text(surf, "事件属性", (right.x + 10, right.y + 8),
                    13, S.ACCENT, True)
        if 0 <= self.cur_event_i < len(self._events()):
            S.draw_text(surf, f"#{self.cur_event_i + 1}", (right.right - 10, right.y + 8),
                        11, S.DIM2, anchor="midright")
        self._draw_scrolled(surf, self.prop_body, self._prop_labels,
                            self._prop_widgets(), self.prop_scroll, mouse)
        self._draw_scrollbar(surf, self.prop_body, self.prop_scroll,
                             getattr(self, "prop_content_h", 0))

        # 顶部：菜单与试演（最后绘制，确保下拉层在最上层）
        self.b_test.draw(surf, mouse)
        self.menubar.draw(surf, mouse)

        if self.message_life > 0 and self.message:
            img = S.font(12, True).render(self.message, True, S.GOOD)
            tw = img.get_width() + 20
            bg = pygame.Rect(canvas.centerx - tw // 2, canvas.y + 10, tw, 24)
            S.round_rect(surf, bg, S.PANEL2, 8)
            S.round_rect(surf, bg, S.GOOD, 8, 1)
            surf.blit(img, (bg.x + 10, bg.centery - img.get_height() // 2))

        ui.draw_hint_bar(surf, pygame.Rect(8, h - 26, w - 16, 20), [
            ("Ctrl+S", "保存"), ("Ctrl+E", "试演"), ("Tab", "切换分页"),
            ("右键", "擦除"), ("Shift+点击", "出生列"), ("Esc", "返回"),
            ("F1", "帮助"),
        ], 10)

        if self.help_open:
            self._draw_help(surf, w, h)

    def _draw_scrolled(self, surf, body, labels, widgets, dy, mouse):
        old_clip = surf.get_clip()
        surf.set_clip(body)
        local_mouse = (mouse[0], mouse[1] + dy)
        for lbl in labels:
            saved = self._shift(lbl, dy)
            lbl.draw(surf, local_mouse)
            self._unshift(lbl, saved)
        for wi in widgets:
            saved = self._shift(wi, dy)
            wi.draw(surf, local_mouse)
            self._unshift(wi, saved)
        surf.set_clip(old_clip)

    def _draw_palette(self, surf, pal, mouse):
        S.panel(surf, pal, S.PANEL2, S.LINE, 7)
        self.brush_rects = []
        n = max(1, len(PALETTE))
        bw = max(30, min(54, (pal.w - 16) // n - 4))
        x = pal.x + 6
        for label, ch, color in PALETTE:
            r = pygame.Rect(x, pal.y + 5, bw, pal.h - 10)
            self.brush_rects.append((r, ch))
            sel = self.brush == ch
            S.round_rect(surf, r, S.blend(S.PANEL3, 1.35 if sel else 1.0), 5)
            S.round_rect(surf, r, S.ACCENT if sel else S.LINE, 5, 1)
            if color is not None:
                sw = pygame.Rect(r.x + 5, r.centery - 5, 10, 10)
                S.round_rect(surf, sw, color, 3)
                tx = r.x + 18
            else:
                tx = r.x + 6
            if bw >= 40:
                S.draw_text(surf, label, (tx, r.centery), 10,
                            S.TEXT if sel else S.DIM, sel, anchor="midleft")
            elif r.collidepoint(mouse):
                S.draw_text(surf, label, (r.centerx, r.centery), 10,
                            S.TEXT, True, anchor="center")
            x += bw + 4
        if x + 66 < pal.right:
            S.draw_text(surf, "右键擦除", (x + 4, pal.centery), 10, S.DIM2,
                        anchor="midleft")

    def _draw_help(self, surf, w, h):
        bw, bh = min(620, w - 40), 178
        rect = pygame.Rect(w // 2 - bw // 2, h // 2 - bh // 2, bw, bh)
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        ov.fill((6, 8, 14, 150))
        surf.blit(ov, (0, 0))
        S.panel(surf, rect, S.PANEL, S.ACCENT, 12)
        S.draw_text(surf, "快捷键与布局说明", (rect.x + 18, rect.y + 16),
                    18, S.TEXT, True)
        y = rect.y + 54
        for line in HELP_LINES:
            S.draw_text(surf, line, (rect.x + 18, y), 12, S.DIM)
            y += 24
        S.draw_text(surf, "点击任意处或按 F1 / Esc 关闭",
                    (rect.centerx, rect.bottom - 18), 11, S.DIM2, anchor="midbottom")

    def _start_scroll_drag(self, pos) -> bool:
        """左键点在滚动条上时开始拖动，返回是否命中。"""
        panels = (
            ("left", getattr(self, "body", None), self.scroll, "left_content_h"),
            ("right", getattr(self, "prop_body", None), self.prop_scroll,
             "prop_content_h"),
        )
        for which, body, cur, key in panels:
            if body is None:
                continue
            content_h = getattr(self, key, 0)
            geom = self._scrollbar_geom(body, cur, content_h)
            if geom and geom[0].collidepoint(pos):
                self._drag_scroll = (which, pos[1] - geom[1].y, body, content_h)
                return True
        return False

    def _move_scroll_drag(self, y) -> None:
        which, grab, body, content_h = self._drag_scroll
        cur = self.scroll if which == "left" else self.prop_scroll
        geom = self._scrollbar_geom(body, cur, content_h)
        if not geom:
            return
        _hit, thumb, track, mx = geom
        span = max(1, track.h - thumb.h)
        frac = max(0.0, min(1.0, (y - grab - track.y) / span))
        val = max(0, min(mx, int(frac * mx + 0.5)))
        if which == "left":
            self.scroll = val
        else:
            self.prop_scroll = val

    def _scrollbar_geom(self, body, scroll, content_h):
        """返回 (命中区, 滑块, 轨道, 最大滚动量)；无内容溢出时返回 None。"""
        mx = max(0, content_h - body.h)
        if mx <= 0:
            return None
        track = pygame.Rect(body.right - 5, body.y + 2, 4, body.h - 4)
        k = body.h / (body.h + mx)
        th = max(24, int(track.h * k))
        ty = track.y + int((track.h - th) * (scroll / mx))
        thumb = pygame.Rect(track.x, ty, track.w, th)
        hit = pygame.Rect(track.x - 5, track.y - 2, track.w + 10, track.h + 4)
        return hit, thumb, track, mx

    def _draw_scrollbar(self, surf, body, scroll, content_h) -> None:
        geom = self._scrollbar_geom(body, scroll, content_h)
        if geom is None:
            return
        _hit, thumb, track, _mx = geom
        S.round_rect(surf, track, S.PANEL3, 2)
        S.round_rect(surf, thumb, S.ACCENT, 2)

    def _fake_core(self):
        """给 render 用的轻量替身，仅含 level / stage 字段。"""

        class _C:
            pass

        c = _C()
        c.level = self.level
        c.stage = self.stage
        return c
