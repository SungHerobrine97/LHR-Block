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
    """多行文本域，支持中文输入、方向键、Home/End、Ctrl+Backspace。"""

    def __init__(self, rect, value="", size=14, cb=None, line_h=None):
        self.rect = pygame.Rect(rect)
        self.size = size
        self.cb = cb
        self.lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n") or [""]
        self.row = 0
        self.col = 0
        self.focus = False
        self.blink = 0.0
        self.scroll = 0
        self.line_h = line_h or S.font(size).get_height() + 3

    # -------------------------------------------------- 数据
    def get(self) -> str:
        return "\n".join(self.lines)

    def set(self, v: str) -> None:
        self.lines = str(v).replace("\r\n", "\n").replace("\r", "\n").split("\n") or [""]
        self.row = 0
        self.col = 0
        self.scroll = 0

    def update(self, dt):
        self.blink += dt

    def draw(self, surf, mouse, **kw):
        r = self.rect
        hot = r.collidepoint(mouse) or self.focus
        S.round_rect(surf, r, S.blend(S.PANEL2, 1.12 if hot else 1.0), 8)
        S.round_rect(surf, r, S.ACCENT if self.focus else S.LINE, 8, 1)
        fnt = S.font(self.size)
        view = pygame.Rect(r.x + 8, r.y + 6, r.w - 16, r.h - 12)
        old = surf.get_clip()
        surf.set_clip(view)
        # 行号
        vis_rows = int(view.h // self.line_h)
        self.scroll = max(0, min(self.scroll, max(0, len(self.lines) - vis_rows + 1)))
        if self.row < self.scroll:
            self.scroll = self.row
        if self.row >= self.scroll + vis_rows - 1:
            self.scroll = self.row - vis_rows + 2
        gn = S.font(self.size - 2)
        gw = max(gn.size(str(len(self.lines)))[0] + 8, 18)
        x0 = view.x + gw
        for i in range(self.scroll, min(len(self.lines), self.scroll + vis_rows)):
            y = view.y + (i - self.scroll) * self.line_h
            num = gn.render(str(i + 1), True, S.DIM2)
            surf.blit(num, (view.x + gw - num.get_width() - 4, y + 1))
            txt = self.lines[i]
            img = fnt.render(txt, True, S.TEXT)
            if img.get_width() > view.w - gw:
                # 简易横向滚动：尾部对齐光标行
                img = fnt.render(txt, True, S.TEXT)
                x = x0 - max(0, img.get_width() - (view.w - gw) + 10)
            else:
                x = x0
            surf.blit(img, (x, y))
            if self.focus and i == self.row and int(self.blink * 2) % 2 == 0:
                cx = x + fnt.size(txt[:self.col])[0]
                pygame.draw.line(surf, S.ACCENT, (cx, y), (cx, y + self.line_h - 2), 1)
        surf.set_clip(old)

    # -------------------------------------------------- 编辑
    def _clamp_col(self):
        self.row = max(0, min(len(self.lines) - 1, self.row))
        self.col = max(0, min(len(self.lines[self.row]), self.col))

    def handle(self, ev):
        if not self.focus:
            return False
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
                self.row -= 1
                self._clamp_col()
                return True
            if k == pygame.K_DOWN:
                self.row += 1
                self._clamp_col()
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
                self.col = 0
                return True
            if k == pygame.K_END:
                self.col = len(line)
                return True
            if k == pygame.K_PAGEUP:
                self.row = max(0, self.row - 6)
                self._clamp_col()
                return True
            if k == pygame.K_PAGEDOWN:
                self.row = min(len(self.lines) - 1, self.row + 6)
                self._clamp_col()
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
