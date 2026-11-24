"""通用控件：按钮、单行输入、多行文本域、开关、数值、选项。

文本输入依赖 pygame 的 TEXTINPUT 事件，配合 key.start_text_input() 可输入中文。
"""
from __future__ import annotations

import pygame

from . import settings as S


class Widget:
    rect: pygame.Rect

    def handle(self, ev) -> bool:
        return False

    def update(self, dt: float) -> None:
        pass


# ---------------------------------------------------------------- 按钮
class Button(Widget):
    def __init__(self, rect, label, cb=None, size=15, kind="normal", enabled=True):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.cb = cb
        self.size = size
        self.kind = kind
        self.enabled = enabled
        self.hot = False

    def palettes(self):
        if self.kind == "primary":
            return (S.ACCENT, S.ACCENT2)
        if self.kind == "danger":
            return (S.BAD, S.blend(S.BAD, 0.6))
        if self.kind == "ghost":
            return (S.PANEL2, S.PANEL3)
        return (S.PANEL2, S.PANEL3)

    def draw(self, surf, mouse, active=True):
        r = self.rect
        hot = self.rect.collidepoint(mouse) and self.enabled
        a, b = self.palettes()
        fill = S.blend(a, 1.25) if hot else a
        if not self.enabled:
            fill = S.blend(S.PANEL, 0.85)
        S.round_rect(surf, r, fill, 8)
        S.round_rect(surf, r, b if not hot else S.blend(b, 1.4), 8, 1)
        col = S.TEXT if self.enabled else S.DIM2
        if self.kind == "primary":
            col = (12, 18, 30) if hot else (16, 24, 40)
        elif self.kind == "danger":
            col = (255, 235, 238)
        S.draw_text(surf, self.label, (r.centerx, r.centery), self.size, col,
                    self.kind == "primary", anchor="center")

    def handle_click(self, pos):
        if self.enabled and self.rect.collidepoint(pos):
            if self.cb:
                self.cb()
            return True
        return False


# ---------------------------------------------------------------- 菜单栏
class MenuBar(Widget):
    """简易下拉菜单栏：菜单项形如 {"label": "保存", "shortcut": "Ctrl+S", "cb": fn}。

    用 "---" 作为分隔项。点击空白处会关闭菜单并把点击交给其他控件。
    """

    def __init__(self, rect, menus, size=12):
        self.rect = pygame.Rect(rect)
        self.menus = menus
        self.size = size
        self.open = None

    def close(self) -> None:
        self.open = None

    def _headers(self) -> list:
        out = []
        x = self.rect.x
        fnt = S.font(self.size, True)
        for label, _items in self.menus:
            w = fnt.size(str(label))[0] + 16
            out.append((label, pygame.Rect(x, self.rect.y, w, self.rect.h)))
            x += w + 2
        return out

    def _item_height(self, item) -> int:
        return 8 if isinstance(item, str) and item == "---" else 24

    def _popup_rect(self, index: int) -> pygame.Rect:
        header = self._headers()[index][1]
        items = self.menus[index][1]
        fnt = S.font(12)
        sfnt = S.font(11)
        width = 112
        for item in items:
            if not isinstance(item, dict):
                continue
            need = fnt.size(str(item.get("label", "")))[0]
            if item.get("shortcut"):
                need += sfnt.size(str(item["shortcut"]))[0] + 22
            width = max(width, need + 26)
        height = 8 + sum(self._item_height(it) for it in items)
        return pygame.Rect(header.x, header.bottom + 2, width, height)

    def _item_rects(self, index: int) -> list:
        popup = self._popup_rect(index)
        out = []
        y = popup.y + 4
        for item in self.menus[index][1]:
            hh = self._item_height(item)
            if not (isinstance(item, str) and item == "---"):
                out.append((item, pygame.Rect(popup.x + 4, y, popup.w - 8, hh)))
            y += hh
        return out

    def handle_click(self, pos) -> bool:
        for i, (_label, rect) in enumerate(self._headers()):
            if rect.collidepoint(pos):
                self.open = None if self.open == i else i
                return True
        if self.open is not None:
            popup = self._popup_rect(self.open)
            if popup.collidepoint(pos):
                for item, rect in self._item_rects(self.open):
                    if rect.collidepoint(pos):
                        if item.get("enabled", True) and item.get("cb"):
                            cb = item["cb"]
                            self.open = None
                            cb()
                        return True
                return True
            self.open = None
        return False

    def draw(self, surf, mouse, **kw):
        for i, (label, rect) in enumerate(self._headers()):
            hot = rect.collidepoint(mouse) or self.open == i
            if hot:
                S.round_rect(surf, rect, S.PANEL2, 5)
            S.draw_text(surf, label, (rect.centerx, rect.centery), self.size,
                        S.ACCENT if hot else S.DIM, True, anchor="center")
        if self.open is None:
            return
        popup = self._popup_rect(self.open)
        S.panel(surf, popup, S.PANEL, S.LINE, 7)
        fnt = S.font(12)
        sfnt = S.font(11)
        for item, rect in self._item_rects(self.open):
            if not item.get("enabled", True):
                S.draw_text(surf, item.get("label", ""), (rect.x + 8, rect.centery),
                            12, S.DIM2, anchor="midleft")
                continue
            if rect.collidepoint(mouse):
                S.round_rect(surf, rect, S.PANEL3, 5)
            S.draw_text(surf, item.get("label", ""), (rect.x + 8, rect.centery),
                        12, S.TEXT, anchor="midleft")
            if item.get("shortcut"):
                S.draw_text(surf, item["shortcut"], (rect.right - 8, rect.centery),
                            11, S.DIM2, anchor="midright")


# ---------------------------------------------------------------- 文本
class TextInput(Widget):
    def __init__(self, rect, value="", placeholder="", numeric=False, size=15, cb=None):
        self.rect = pygame.Rect(rect)
        self.value = str(value)
        self.placeholder = placeholder
        self.numeric = numeric
        self.size = size
        self.cb = cb
        self.focus = False
        self.caret = len(self.value)
        self.blink = 0.0

    def set(self, v):
        self.value = str(v)
        self.caret = min(self.caret, len(self.value))

    def update(self, dt):
        self.blink += dt

    def draw(self, surf, mouse, **kw):
        r = self.rect
        hot = r.collidepoint(mouse) or self.focus
        S.round_rect(surf, r, S.blend(S.PANEL2, 1.15 if hot else 1.0), 6)
        S.round_rect(surf, r, S.ACCENT if self.focus else S.LINE, 6, 1)
        fnt = S.font(self.size)
        clip = pygame.Rect(r.x + 6, r.y, r.w - 12, r.h)
        old = surf.get_clip()
        surf.set_clip(clip)
        if self.value:
            img = fnt.render(self.value, True, S.TEXT)
        else:
            img = fnt.render(self.placeholder, True, S.DIM2)
        tx = r.x + 6
        if img.get_width() > clip.w:
            tx = clip.right - img.get_width()
        surf.blit(img, (tx, r.y + (r.h - img.get_height()) // 2))
        if self.focus and int(self.blink * 2) % 2 == 0:
            cx = tx + fnt.size(self.value[:self.caret])[0]
            pygame.draw.line(surf, S.ACCENT, (cx, r.y + 5), (cx, r.bottom - 5), 1)
        surf.set_clip(old)

    def handle(self, ev):
        if not self.focus:
            return False
        if ev.type == pygame.TEXTINPUT:
            ch = ev.text
            if self.numeric and not (ch.isdigit() or ch in ".-"):
                return True
            self.value = self.value[:self.caret] + ch + self.value[self.caret:]
            self.caret += len(ch)
            return True
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                if self.caret > 0:
                    self.value = self.value[:self.caret - 1] + self.value[self.caret:]
                    self.caret -= 1
                return True
            if ev.key == pygame.K_DELETE:
                self.value = self.value[:self.caret] + self.value[self.caret + 1:]
                return True
            if ev.key == pygame.K_LEFT:
                self.caret = max(0, self.caret - 1)
                return True
            if ev.key == pygame.K_RIGHT:
                self.caret = min(len(self.value), self.caret + 1)
                return True
            if ev.key == pygame.K_HOME:
                self.caret = 0
                return True
            if ev.key == pygame.K_END:
                self.caret = len(self.value)
                return True
        return False


class TextArea(Widget):
    """多行文本域，支持中文输入、方向键、Home/End、Ctrl+Backspace、超宽自动换行。"""

    def __init__(self, rect, value="", size=14, cb=None, line_h=None, wrap=True):
        self.rect = pygame.Rect(rect)
        self.size = size
        self.cb = cb
        self.wrap = wrap
        self.lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n") or [""]
        self.row = 0
        self.col = 0
        self.focus = False
        self.blink = 0.0
        self.scroll = 0                    # 以视觉行（换行后）为单位
        self.line_h = line_h or S.font(size).get_height() + 3
        self._frags = []                   # [(逻辑行, 起列, 止列, 片段文本), ...]
        self._row_frags = []               # 逻辑行 -> 片段索引列表
        self._wrap_key = None              # (可用宽度, 文本签名)
        self._char_w = {}                  # 单字符宽度缓存
        self._follow_caret = True          # 键盘编辑时自动跟随光标；滚轮滚动时暂停

    # -------------------------------------------------- 数据
    def get(self) -> str:
        return "\n".join(self.lines)

    def set(self, v: str) -> None:
        self.lines = str(v).replace("\r\n", "\n").replace("\r", "\n").split("\n") or [""]
        self.row = 0
        self.col = 0
        self.scroll = 0
        self._wrap_key = None
        self._follow_caret = True

    def update(self, dt):
        self.blink += dt

    def scroll_by(self, delta_lines: int) -> None:
        """供外部滚轮调用：只滚动本文本框内容，不惊动外部面板。"""
        fnt, view = self._nav_ctx()
        total = max(1, len(self._frags))
        vis_rows = max(1, int(view.h // self.line_h))
        limit = max(0, total - vis_rows + 1)
        self.scroll = max(0, min(limit, self.scroll + int(delta_lines)))
        self._follow_caret = False          # 不要把主动滚动拉回光标处

    def draw(self, surf, mouse, **kw):
        r = self.rect
        hot = r.collidepoint(mouse) or self.focus
        S.round_rect(surf, r, S.blend(S.PANEL2, 1.12 if hot else 1.0), 8)
        S.round_rect(surf, r, S.ACCENT if self.focus else S.LINE, 8, 1)
        fnt = S.font(self.size)
        gn, gw, width, view = self._layout()
        self._rebuild_wrap(fnt, width)
        frag_i, caret_x = self._caret(fnt)
        x0 = view.x + gw
        total = max(1, len(self._frags))
        vis_rows = max(1, int(view.h // self.line_h))
        self.scroll = max(0, min(self.scroll, max(0, total - vis_rows + 1)))
        if self._follow_caret:
            if frag_i < self.scroll:
                self.scroll = frag_i
            if frag_i >= self.scroll + vis_rows - 1:
                self.scroll = frag_i - vis_rows + 2
        old = surf.get_clip()
        surf.set_clip(view)
        for fi in range(self.scroll, min(total, self.scroll + vis_rows)):
            row, start, _end, seg = self._frags[fi]
            y = view.y + (fi - self.scroll) * self.line_h
            if start == 0:                      # 只在逻辑行首显示行号
                num = gn.render(str(row + 1), True, S.DIM2)
                surf.blit(num, (view.x + gw - num.get_width() - 4, y + 1))
            surf.blit(fnt.render(seg, True, S.TEXT), (x0, y))
            if self.focus and fi == frag_i and int(self.blink * 2) % 2 == 0:
                cx = x0 + caret_x
                pygame.draw.line(surf, S.ACCENT, (cx, y), (cx, y + self.line_h - 2), 1)
        surf.set_clip(old)

    # -------------------------------------------------- 自动换行辅助
    def _layout(self):
        """返回 (行号字体, 行号宽, 文本可用宽, 文本视图矩形)。"""
        view = pygame.Rect(self.rect.x + 8, self.rect.y + 6,
                           self.rect.w - 16, self.rect.h - 12)
        gn = S.font(self.size - 2)
        gw = max(gn.size(str(len(self.lines)))[0] + 8, 18)
        width = max(10, view.w - gw) if self.wrap else 100000
        return gn, gw, width, view

    def _width_of(self, fnt, ch: str) -> int:
        cw = self._char_w.get(ch)
        if cw is None:
            cw = fnt.size(ch)[0]
            self._char_w[ch] = cw
        return cw

    def _rebuild_wrap(self, fnt, width: int) -> None:
        sig = (width, tuple(self.lines))
        if self._wrap_key == sig:
            return
        self._wrap_key = sig
        frags, row_frags = [], []
        for ri, line in enumerate(self.lines):
            idxs = []
            if not self.wrap:
                frags.append((ri, 0, len(line), line))
                idxs.append(len(frags) - 1)
                row_frags.append(idxs)
                continue
            seg_start, x, space_at = 0, 0, -1
            for ci, ch in enumerate(line):
                cw = self._width_of(fnt, ch)
                if x + cw > width and ci > seg_start:
                    end = space_at if space_at > seg_start else ci
                    frags.append((ri, seg_start, end, line[seg_start:end]))
                    idxs.append(len(frags) - 1)
                    seg_start = end
                    x = sum(self._width_of(fnt, c) for c in line[seg_start:ci + 1])
                    space_at = -1
                else:
                    x += cw
                    if ch in (" ", "\t"):
                        space_at = ci + 1
            frags.append((ri, seg_start, len(line), line[seg_start:]))
            idxs.append(len(frags) - 1)
            row_frags.append(idxs)
        self._frags = frags
        self._row_frags = row_frags

    def _caret(self, fnt):
        """把 (row, col) 映射为 (视觉片段索引, 片段内 x 偏移)。"""
        row = max(0, min(len(self.lines) - 1, self.row))
        col = max(0, min(len(self.lines[row]), self.col))
        idxs = self._row_frags[row] if row < len(self._row_frags) else []
        if not idxs:
            return 0, 0
        fi = idxs[-1]
        for cand in idxs:
            if col < self._frags[cand][2] or cand == idxs[-1]:
                fi = cand
                break
        _r, start, _end, seg = self._frags[fi]
        return fi, fnt.size(seg[:max(0, col - start)])[0]

    def _frag_col(self, fnt, fi: int, xoff: int) -> int:
        """在指定视觉片段中找最接近 x 偏移的字符列（绝对列）。"""
        _r, start, _end, seg = self._frags[fi]
        col, acc = start, 0
        for p, ch in enumerate(seg):
            cw = self._width_of(fnt, ch)
            if acc + cw > xoff:
                break
            acc += cw
            col = start + p + 1
        return col

    def _nav_ctx(self):
        """键盘导航前确保换行数据是最新的，返回 (字体, 视图矩形)。"""
        fnt = S.font(self.size)
        _gn, _gw, width, view = self._layout()
        self._rebuild_wrap(fnt, width)
        return fnt, view

    # -------------------------------------------------- 编辑
    def _clamp_col(self):
        self.row = max(0, min(len(self.lines) - 1, self.row))
        self.col = max(0, min(len(self.lines[self.row]), self.col))

    def handle(self, ev):
        if not self.focus:
            return False
        if ev.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            self._follow_caret = True        # 重新编辑后恢复光标跟随
        mods = pygame.key.get_mods()
        ctrl = bool(mods & pygame.KMOD_CTRL)
        if ev.type == pygame.TEXTINPUT:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.col] + ev.text + line[self.col:]
            self.col += len(ev.text)
            return True
        if ev.type == pygame.KEYDOWN:
            k = ev.key
            line = self.lines[self.row]
            if k == pygame.K_RETURN or k == pygame.K_KP_ENTER:
                rest = line[self.col:]
                self.lines[self.row] = line[:self.col]
                self.lines.insert(self.row + 1, rest)
                self.row += 1
                self.col = 0
                return True
            if k == pygame.K_BACKSPACE:
                if ctrl:
                    self.lines[self.row] = line[:max(0, self.col - 8)]
                    self.col = max(0, self.col - 8)
                elif self.col > 0:
                    self.lines[self.row] = line[:self.col - 1] + line[self.col:]
                    self.col -= 1
                elif self.row > 0:
                    prev = self.lines[self.row - 1]
                    self.col = len(prev)
                    self.lines[self.row - 1] = prev + self.lines.pop(self.row)
                    self.row -= 1
                return True
            if k == pygame.K_DELETE:
                if self.col < len(line):
                    self.lines[self.row] = line[:self.col] + line[self.col + 1:]
                elif self.row < len(self.lines) - 1:
                    self.lines[self.row] = line + self.lines.pop(self.row + 1)
                return True
            if k == pygame.K_UP:
                fnt, _view = self._nav_ctx()
                fi, xoff = self._caret(fnt)
                if fi > 0:
                    fi -= 1
                    self.row = self._frags[fi][0]
                    self.col = self._frag_col(fnt, fi, xoff)
                else:
                    self.row, self.col = 0, 0
                return True
            if k == pygame.K_DOWN:
                fnt, _view = self._nav_ctx()
                fi, xoff = self._caret(fnt)
                if fi < len(self._frags) - 1:
                    fi += 1
                    self.row = self._frags[fi][0]
                    self.col = self._frag_col(fnt, fi, xoff)
                else:
                    self.row = len(self.lines) - 1
                    self.col = len(self.lines[self.row])
                return True
            if k == pygame.K_LEFT:
                if self.col > 0:
                    self.col -= 1
                elif self.row > 0:
                    self.row -= 1
                    self.col = len(self.lines[self.row])
                return True
            if k == pygame.K_RIGHT:
                if self.col < len(line):
                    self.col += 1
                elif self.row < len(self.lines) - 1:
                    self.row += 1
                    self.col = 0
                return True
            if k == pygame.K_HOME:
                if ctrl:
                    self.row, self.col = 0, 0
                else:
                    fnt, _view = self._nav_ctx()
                    fi, _x = self._caret(fnt)
                    self.col = self._frags[fi][1]   # 当前视觉行首
                return True
            if k == pygame.K_END:
                if ctrl:
                    self.row = len(self.lines) - 1
                    self.col = len(self.lines[self.row])
                else:
                    fnt, _view = self._nav_ctx()
                    fi, _x = self._caret(fnt)
                    self.col = self._frags[fi][2]   # 当前视觉行尾
                return True
            if k == pygame.K_PAGEUP:
                fnt, view = self._nav_ctx()
                fi, xoff = self._caret(fnt)
                step = max(1, int(view.h // self.line_h) - 1)
                fi = max(0, fi - step)
                self.row = self._frags[fi][0]
                self.col = self._frag_col(fnt, fi, xoff)
                return True
            if k == pygame.K_PAGEDOWN:
                fnt, view = self._nav_ctx()
                fi, xoff = self._caret(fnt)
                step = max(1, int(view.h // self.line_h) - 1)
                fi = min(len(self._frags) - 1, fi + step)
                self.row = self._frags[fi][0]
                self.col = self._frag_col(fnt, fi, xoff)
                return True
        return False


# ---------------------------------------------------------------- 选择类
class Toggle(Widget):
    def __init__(self, rect, label, value=False, cb=None, hint=""):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.value = bool(value)
        self.cb = cb
        self.hint = hint

    def draw(self, surf, mouse, **kw):
        r = self.rect
        hot = r.collidepoint(mouse)
        S.round_rect(surf, r, S.blend(S.PANEL2, 1.2 if hot else 1.0), 7)
        S.round_rect(surf, r, S.LINE, 7, 1)
        sw_w = 34 if r.w >= 90 else 22
        sw = pygame.Rect(r.right - sw_w - 6, r.centery - 9, sw_w, 18)
        # 标签绘制在开关左侧，空间不足时缩小并居中
        lab_w = sw.x - r.x - 14
        fsize = 13 if lab_w >= 60 else 11
        fnt = S.font(fsize)
        if lab_w > 4:
            clip = pygame.Rect(r.x + 8, r.y, lab_w, r.h)
            old = surf.get_clip()
            surf.set_clip(clip)
            if r.w < 70:
                img = fnt.render(str(self.label), True, S.TEXT)
                surf.blit(img, (r.x + (lab_w + 8 - img.get_width()) // 2,
                                r.centery - img.get_height() // 2))
            else:
                S.draw_text(surf, self.label, (r.x + 10, r.centery), fsize, S.TEXT,
                            anchor="midleft")
            surf.set_clip(old)
        elif r.w >= 16:
            # 极窄（如方块池小开关）：字母直接居中叠在开关上
            img = S.font(11, True).render(str(self.label), True,
                                          (16, 24, 40) if self.value else S.DIM2)
            surf.blit(img, (r.centerx - img.get_width() // 2,
                            r.centery - img.get_height() // 2))
        if self.hint and r.w >= 200:
            hw = S.font(11).size(self.hint)[0]
            S.draw_text(surf, self.hint, (sw.x - 6 - hw, r.centery), 11,
                        S.DIM2, anchor="midleft")
        S.round_rect(surf, sw, S.GOOD if self.value else S.PANEL3, 9)
        k = 1 if self.value else 0
        cx = sw.x + 9 + k * (sw.w - 18)
        pygame.draw.circle(surf, (250, 252, 255), (cx, sw.centery), 7)

    def handle_click(self, pos):
        if self.rect.collidepoint(pos):
            self.value = not self.value
            if self.cb:
                self.cb(self.value)
            return True
        return False


class Choice(Widget):
    """点击循环切换选项。"""

    def __init__(self, rect, label, options, index=0, cb=None, labels=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.options = list(options)
        self.labels = list(labels or self.options)
        self.index = max(0, min(len(self.options) - 1, index))
        self.cb = cb

    @property
    def value(self):
        return self.options[self.index]

    def draw(self, surf, mouse, **kw):
        r = self.rect
        hot = r.collidepoint(mouse)
        S.round_rect(surf, r, S.blend(S.PANEL2, 1.2 if hot else 1.0), 7)
        S.round_rect(surf, r, S.LINE, 7, 1)
        S.draw_text(surf, self.label, (r.x + 10, r.centery), 13, S.TEXT, anchor="midleft")
        txt = str(self.labels[self.index])
        img = S.font(13, True).render(txt, True, S.ACCENT)
        surf.blit(img, (r.right - 10 - img.get_width(), r.centery - img.get_height() // 2))

    def handle_click(self, pos):
        if self.rect.collidepoint(pos):
            self.index = (self.index + 1) % len(self.options)
            if self.cb:
                self.cb(self.options[self.index])
            return True
        return False


class Stepper(Widget):
    """数值步进器。"""

    def __init__(self, rect, label, value=0, lo=0, hi=999, step=1, cb=None, fmt="{:g}"):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.value = value
        self.lo, self.hi, self.step = lo, hi, step
        self.cb = cb
        self.fmt = fmt
        bw = 26
        self.minus = pygame.Rect(rect.right - bw * 2 - 8, rect.centery - 11, bw, 22)
        self.plus = pygame.Rect(rect.right - bw - 4, rect.centery - 11, bw, 22)

    def draw(self, surf, mouse, **kw):
        r = self.rect
        S.round_rect(surf, r, S.PANEL2, 7)
        S.round_rect(surf, r, S.LINE, 7, 1)
        S.draw_text(surf, self.label, (r.x + 10, r.centery), 13, S.TEXT, anchor="midleft")
        img = S.font(13, True).render(self.fmt.format(self.value), True, S.ACCENT)
        surf.blit(img, (self.minus.x - 8 - img.get_width(), r.centery - img.get_height() // 2))
        for rect, ch in ((self.minus, "−"), (self.plus, "+")):
            hot = rect.collidepoint(mouse)
            S.round_rect(surf, rect, S.blend(S.PANEL3, 1.35 if hot else 1.0), 5)
            S.draw_text(surf, ch, (rect.centerx, rect.centery), 14, S.TEXT,
                        anchor="center")

    def _set(self, v):
        nv = max(self.lo, min(self.hi, v))
        if nv != self.value:
            self.value = nv
            if self.cb:
                self.cb(nv)

    def handle_click(self, pos):
        if self.minus.collidepoint(pos):
            self._set(self.value - self.step)
            return True
        if self.plus.collidepoint(pos):
            self._set(self.value + self.step)
            return True
        return False


class Label(Widget):
    def __init__(self, rect, text, size=13, color=S.DIM, bold=False, align="left"):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.size = size
        self.color = color
        self.bold = bold
        self.align = align

    def draw(self, surf, mouse=None, **kw):
        img = S.font(self.size, self.bold).render(str(self.text), True, self.color)
        if self.align == "center":
            p = (self.rect.centerx - img.get_width() // 2, self.rect.y)
        else:
            p = (self.rect.x, self.rect.y)
        surf.blit(img, p)


class GridEditor(Widget):
    """方格勾选器：用于自定义形状的格子编辑。"""

    def __init__(self, rect, cols=5, rows=5, cells=None, cb=None):
        self.rect = pygame.Rect(rect)
        self.cols = max(1, int(cols))
        self.rows = max(1, int(rows))
        self.cells = set((int(x), int(y)) for x, y in (cells or []))
        self.cb = cb
        self.locked = False

    # -------------------------------------------------- 数据
    def get_cells(self) -> list:
        return sorted(self.cells)

    def set_cells(self, cells) -> None:
        self.cells = set((int(x), int(y)) for x, y in (cells or []))
        self.cells = set(c for c in self.cells
                         if 0 <= c[0] < self.cols and 0 <= c[1] < self.rows)

    def _geom(self):
        size = max(8, min(self.rect.w // self.cols, self.rect.h // self.rows))
        w, h = size * self.cols, size * self.rows
        return size, self.rect.x + (self.rect.w - w) // 2, \
            self.rect.y + (self.rect.h - h) // 2

    def _cell_rect(self, c, r, size, ox, oy):
        return pygame.Rect(ox + c * size, oy + r * size, size, size)

    # -------------------------------------------------- 绘制 / 交互
    def draw(self, surf, mouse, color=(94, 196, 244), **kw):
        size, ox, oy = self._geom()
        for r in range(self.rows):
            for c in range(self.cols):
                rc = self._cell_rect(c, r, size, ox, oy)
                on = (c, r) in self.cells
                hot = rc.collidepoint(mouse) and not self.locked
                S.round_rect(surf, rc.inflate(-2, -2),
                             S.blend(S.PANEL2, 1.25 if hot else 1.0), 3)
                if on:
                    inner = rc.inflate(-max(3, size // 5), -max(3, size // 5))
                    S.round_rect(surf, inner, color, max(2, size // 8))
                    S.round_rect(surf, inner, S.blend(color, 1.5), max(2, size // 8), 1)
                else:
                    S.round_rect(surf, rc.inflate(-2, -2), S.LINE, 3, 1)
        if self.locked:
            img = S.font(11).render("内置只读 · 复制后可改", True, S.DIM)
            surf.blit(img, (self.rect.x + 2, self.rect.bottom - img.get_height() - 1))

    def handle_click(self, pos):
        if self.locked:
            return False
        size, ox, oy = self._geom()
        for r in range(self.rows):
            for c in range(self.cols):
                if self._cell_rect(c, r, size, ox, oy).collidepoint(pos):
                    if (c, r) in self.cells:
                        self.cells.discard((c, r))
                    else:
                        self.cells.add((c, r))
                    if self.cb:
                        self.cb(self.get_cells())
                    return True
        return False


class ColorChoice(Widget):
    """色号选择器：点击循环切换，右侧显示色块与色名。"""

    def __init__(self, rect, label, ids, index=0, cb=None, names=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.ids = list(ids)
        self.names = names or {}
        self.index = max(0, min(len(self.ids) - 1, index))
        self.cb = cb

    @property
    def value(self):
        return self.ids[self.index]

    def set_value(self, v):
        if v in self.ids:
            self.index = self.ids.index(v)

    def draw(self, surf, mouse, **kw):
        r = self.rect
        hot = r.collidepoint(mouse)
        S.round_rect(surf, r, S.blend(S.PANEL2, 1.2 if hot else 1.0), 7)
        S.round_rect(surf, r, S.LINE, 7, 1)
        S.draw_text(surf, self.label, (r.x + 10, r.centery), 13, S.TEXT,
                    anchor="midleft")
        cid = self.value
        sw = pygame.Rect(r.right - 58, r.centery - 9, 18, 18)
        S.round_rect(surf, sw, S.BLOCK_COLORS.get(cid, (140, 150, 170)), 4)
        S.round_rect(surf, sw, S.LINE2, 4, 1)
        txt = f"{self.names.get(cid, cid)} · {cid}"
        img = S.font(13, True).render(txt, True, S.ACCENT)
        surf.blit(img, (sw.x - 8 - img.get_width(), r.centery - img.get_height() // 2))

    def handle_click(self, pos):
        if self.rect.collidepoint(pos):
            self.index = (self.index + 1) % len(self.ids)
            if self.cb:
                self.cb(self.value)
            return True
        return False


class ListRow(Widget):
    def __init__(self, rect, title, sub="", cb=None, selected=False, tag=""):
        self.rect = pygame.Rect(rect)
        self.title = title
        self.sub = sub
        self.cb = cb
        self.selected = selected
        self.tag = tag

    def draw(self, surf, mouse, **kw):
        r = self.rect
        hot = r.collidepoint(mouse)
        base = S.PANEL3 if self.selected else S.PANEL
        S.round_rect(surf, r, S.blend(base, 1.25 if hot else 1.0), 8)
        S.round_rect(surf, r, S.ACCENT if self.selected else S.LINE, 8, 1)
        tag = None
        if self.tag:
            tag = S.font(11, True).render(
                self.tag, True, S.GOOD if self.tag == "已通关" else S.DIM2)
        if r.h <= 34:
            # 紧凑行（如编辑器的触发时机列表）：标题靠左居中，副标题与标记靠右居中，
            # 避免文字越过行边界压到下一行
            limit = r.right - 10
            if tag is not None:
                surf.blit(tag, (limit - tag.get_width(),
                                r.centery - tag.get_height() // 2))
                limit -= tag.get_width() + 10
            if self.sub:
                S.draw_text(surf, self.sub, (limit, r.centery), 11, S.DIM,
                            anchor="midright")
            S.draw_text(surf, self.title, (r.x + 12, r.centery), 14, S.TEXT,
                        self.selected, anchor="midleft")
            return
        S.draw_text(surf, self.title, (r.x + 12, r.y + 9), 15, S.TEXT, self.selected)
        if self.sub:
            S.draw_text(surf, self.sub, (r.x + 12, r.y + 28), 12, S.DIM)
        if tag is not None:
            surf.blit(tag, (r.right - 10 - tag.get_width(), r.y + 10))

    def handle_click(self, pos):
        if self.rect.collidepoint(pos):
            if self.cb:
                self.cb()
            return True
        return False


# ---------------------------------------------------------------- 组件
def draw_dialogue(surf, rect, speaker, text, t, done=True):
    """底部对白框。"""
    S.round_rect(surf, rect, (18, 22, 33), 10)
    S.round_rect(surf, rect, S.LINE2, 10, 1)
    x = rect.x + 16
    S.draw_text(surf, text, (x, rect.y + 14), 15, S.TEXT)
    if speaker:
        tag = S.font(13, True).render(speaker, True, (20, 24, 36))
        tw = tag.get_width() + 16
        box = pygame.Rect(rect.x + 12, rect.y - 13, tw, 24)
        S.round_rect(surf, box, S.ACCENT, 7)
        surf.blit(tag, (box.x + 8, box.y + 4))
    # 等待玩家确认：给出明确提示（仅闪烁三角形太不显眼）
    if done:
        label = "空格 / 点击 继续"
        img = S.font(11, True).render(label, True, (14, 20, 32))
        tw, th = img.get_width() + 16, img.get_height() + 8
        box = pygame.Rect(rect.right - 12 - tw, rect.bottom - 12 - th, tw, th)
        if int(t * 2.4) % 2 == 0:
            S.round_rect(surf, box, S.ACCENT, 7)
            surf.blit(img, (box.x + 8, box.y + 4))
        else:
            S.round_rect(surf, box, S.blend(S.ACCENT, 0.72), 7)
            surf.blit(img, (box.x + 8, box.y + 4))


def draw_hint_bar(surf, rect, items, size=12, active=None):
    """底部按键提示。active 里的按键名会被高亮，用来确认输入是否送达。"""
    active = active or set()
    x = rect.x
    for k, v in items:
        hot = k in active
        kimg = S.font(size, True).render(k, True, (14, 20, 32) if hot else S.GOLD)
        vimg = S.font(size).render(v, True, S.DIM)
        if x + kimg.get_width() + vimg.get_width() + 22 > rect.right:
            break
        by = rect.centery - kimg.get_height() // 2
        chip = pygame.Rect(x, by - 3, kimg.get_width() + 8, kimg.get_height() + 6)
        S.round_rect(surf, chip, S.ACCENT if hot else S.PANEL2, 4)
        if hot:
            S.round_rect(surf, chip, S.blend(S.ACCENT, 1.5), 4, 1)
        surf.blit(kimg, (x + 4, by))
        x += kimg.get_width() + 12
        surf.blit(vimg, (x, rect.centery - vimg.get_height() // 2))
        x += vimg.get_width() + 22
