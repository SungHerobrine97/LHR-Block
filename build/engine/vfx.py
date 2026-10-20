"""视觉特效（VFX）集合。

每个特效实现 update(dt) / draw(surface, ctx)，由 VFXManager 统一开关与调度。
ctx 提供 {ox, oy, cell, stage_rect, t} 等舞台渲染上下文。
"""
from __future__ import annotations

import math
import random

import pygame

from . import settings as S

ALL_VFX = ("rain", "snow", "embers", "flash", "shake", "pulse",
           "vignette", "scanline", "glitch", "stars", "fog")

RENDER_NAME = {
    "rain": "落雨", "snow": "飘雪", "embers": "火星", "flash": "闪光",
    "shake": "震屏", "pulse": "网格脉冲", "vignette": "暗角",
    "scanline": "扫描线", "glitch": "故障", "stars": "星空", "fog": "浓雾",
}


class Base:
    name = "base"

    def __init__(self):
        self.t = 0.0

    def update(self, dt: float) -> None:
        self.t += dt

    def draw(self, surf: pygame.Surface, ctx: dict) -> None:
        pass


class Rain(Base):
    name = "rain"

    def __init__(self):
        super().__init__()
        self.drops = [(random.random(), random.random(), random.uniform(0.5, 1.3))
                      for _ in range(150)]

    def update(self, dt):
        super().update(dt)
        for i, (x, y, sp) in enumerate(self.drops):
            y += dt * sp * 1.6
            x += dt * 0.05
            if y > 1.05:
                y = -0.05
                x = random.random()
            self.drops[i] = (x % 1.0, y, sp)

    def draw(self, surf, ctx):
        w, h = surf.get_size()
        for x, y, sp in self.drops:
            px, py = int(x * w), int(y * h)
            ln = int(10 + sp * 12)
            pygame.draw.line(surf, (150, 190, 235), (px - 2, py), (px - 2, py + ln), 1)


class Snow(Base):
    name = "snow"

    def __init__(self):
        super().__init__()
        self.flakes = [(random.random(), random.random(), random.uniform(0.4, 1.0),
                        random.uniform(-1, 1)) for _ in range(120)]

    def update(self, dt):
        super().update(dt)
        out = []
        for x, y, sp, sw in self.flakes:
            y += dt * sp * 0.16
            x += math.sin(self.t * sw + y * 6) * dt * 0.03 + dt * 0.01
            if y > 1.05:
                y = -0.05
            out.append((x % 1.0, y, sp, sw))
        self.flakes = out

    def draw(self, surf, ctx):
        w, h = surf.get_size()
        for x, y, sp, _ in self.flakes:
            r = int(1 + sp * 1.6)
            pygame.draw.circle(surf, (215, 228, 250), (int(x * w), int(y * h)), r)


class Embers(Base):
    name = "embers"

    def __init__(self):
        super().__init__()
        self.parts = [(random.random(), random.random(), random.uniform(0.3, 1.0))
                      for _ in range(90)]

    def update(self, dt):
        super().update(dt)
        out = []
        for x, y, sp in self.parts:
            y -= dt * sp * 0.35
            x += math.sin(self.t * 1.5 + y * 9) * dt * 0.04
            if y < -0.05:
                y = 1.05
            out.append((x % 1.0, y, sp))
        self.parts = out

    def draw(self, surf, ctx):
        w, h = surf.get_size()
        for x, y, sp in self.parts:
            a = int(150 * (1.0 - y) + 40)
            col = (255, int(120 + 100 * sp), 60, a)
            px, py = int(x * w), int(y * h)
            pygame.draw.circle(surf, (255, 170, 70), (px, py), max(1, int(sp * 2)))


class Flash(Base):
    name = "flash"

    def __init__(self):
        super().__init__()
        self.strength = 0.0

    def trigger(self, amount=1.0):
        self.strength = max(self.strength, amount)

    def update(self, dt):
        super().update(dt)
        self.strength = max(0.0, self.strength - dt * 2.6)

    def draw(self, surf, ctx):
        if self.strength <= 0.001:
            return
        a = int(min(200, self.strength * 220))
        ov = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        ov.fill((255, 255, 255, a))
        surf.blit(ov, (0, 0))


class Shake(Base):
    name = "shake"

    def __init__(self):
        super().__init__()
        self.amount = 0.0
        self.offset = (0, 0)

    def trigger(self, amount=8.0):
        self.amount = max(self.amount, amount)

    def update(self, dt):
        super().update(dt)
        self.amount = max(0.0, self.amount - dt * 26)
        a = self.amount
        self.offset = (random.uniform(-a, a), random.uniform(-a, a)) if a > 0.2 else (0, 0)

    def draw(self, surf, ctx):
        pass


class Pulse(Base):
    name = "pulse"

    def draw(self, surf, ctx):
        rect = ctx.get("stage_rect")
        if not rect:
            return
        k = 0.5 + 0.5 * math.sin(self.t * 3.0)
        w = int(3 + k * 3)
        c = S.mix(S.ACCENT, S.PURPLE, k)
        pygame.draw.rect(surf, c, rect, w, border_radius=8)


class Vignette(Base):
    name = "vignette"

    def draw(self, surf, ctx):
        w, h = surf.get_size()
        if getattr(self, "_surf", None) is None or self._surf.get_size() != (w, h):
            self._surf = pygame.Surface((w, h), pygame.SRCALPHA)
            steps = 60
            for i in range(steps):
                t = i / steps
                a = int(190 * (t ** 2.2))
                r = pygame.Rect(int(t * w * 0.5), int(t * h * 0.5),
                                max(1, int(w * (1 - t))), max(1, int(h * (1 - t))))
                pygame.draw.ellipse(self._surf, (0, 0, 0, max(0, 60 - i // 4)), r)
            ov = pygame.Surface((w, h), pygame.SRCALPHA)
            cx, cy = w // 2, h // 2
            for i in range(steps, 0, -1):
                t = i / steps
                rad = int(max(w, h) * 0.75 * (1 - t) ** 0.6)
                if rad <= 0:
                    continue
            del ov
        surf.blit(self._surf, (0, 0))


class Scanline(Base):
    name = "scanline"

    def draw(self, surf, ctx):
        w, h = surf.get_size()
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        for y in range(0, h, 3):
            pygame.draw.line(ov, (0, 0, 0, 46), (0, y), (w, y))
        y = int((self.t * 90) % (h + 60)) - 30
        pygame.draw.line(ov, (140, 200, 255, 40), (0, y), (w, y), 3)
        surf.blit(ov, (0, 0))


class Glitch(Base):
    name = "glitch"

    def draw(self, surf, ctx):
        w, h = surf.get_size()
        if random.random() < 0.14:
            y = random.randint(0, h - 8)
            hh = random.randint(3, 14)
            band = surf.subsurface(pygame.Rect(0, y, w, hh)).copy()
            surf.blit(band, (random.randint(-14, 14), y))


class Stars(Base):
    name = "stars"

    def __init__(self):
        super().__init__()
        self.pts = [(random.random(), random.random(), random.uniform(0.3, 1.0))
                    for _ in range(110)]

    def draw(self, surf, ctx):
        w, h = surf.get_size()
        for x, y, sp in self.pts:
            tw = 0.4 + 0.6 * abs(math.sin(self.t * sp * 2.2 + x * 12))
            c = (int(200 * tw), int(215 * tw), int(255 * tw))
            pygame.draw.circle(surf, c, (int(x * w), int(y * h)), 1)


class Fog(Base):
    name = "fog"

    def draw(self, surf, ctx):
        w, h = surf.get_size()
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        for i in range(6):
            y = int((self.t * 12 + i * 90) % (h + 180)) - 90
            pygame.draw.ellipse(ov, (120, 130, 160, 22),
                                pygame.Rect(-100 + i * 30, y, w + 200, 120))
        surf.blit(ov, (0, 0))


REGISTRY = {cls.name: cls for cls in
            (Rain, Snow, Embers, Flash, Shake, Pulse, Vignette, Scanline, Glitch, Stars, Fog)}


class VFXManager:
    def __init__(self, enabled=None):
        self.enabled = set(enabled or [])
        self.instances: dict = {n: REGISTRY[n]() for n in REGISTRY}

    def set_enabled(self, names) -> None:
        self.enabled = set(n for n in names if n in REGISTRY)

    def toggle(self, name: str) -> bool:
        if name not in REGISTRY:
            return False
        if name in self.enabled:
            self.enabled.discard(name)
            return False
        self.enabled.add(name)
        return True

    def is_on(self, name: str) -> bool:
        return name in self.enabled

    def instance(self, name: str):
        return self.instances.get(name)

    def trigger(self, name: str, amount=1.0) -> None:
        inst = self.instances.get(name)
        if inst and hasattr(inst, "trigger"):
            inst.trigger(amount)

    def shake_offset(self):
        inst = self.instances.get("shake")
        return inst.offset if inst else (0, 0)

    def update(self, dt: float) -> None:
        # shake / flash 属于反馈层，即便未启用也要衰减，避免数值滞留
        always = ("shake", "flash")
        targets = set(self.enabled) | set(always)
        for n in targets:
            self.instances[n].update(dt)

    def draw(self, surf: pygame.Surface, ctx: dict) -> None:
        for n in sorted(self.enabled):
            if n == "shake":
                continue
            self.instances[n].draw(surf, ctx)
