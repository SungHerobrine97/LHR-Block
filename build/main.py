"""程序入口。"""
from __future__ import annotations

import os
import sys

import pygame

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import level as L          # noqa: E402
from engine import settings as S       # noqa: E402
from engine.audio import Audio         # noqa: E402
from engine.save import SaveData       # noqa: E402
from engine.scenes import MenuScene, Scene  # noqa: E402


class App:
    def __init__(self):
        pygame.init()
        S.ensure_dirs()
        pygame.display.set_caption(f"{S.APP_TITLE}  v{S.APP_VERSION}")
        try:
            icon = pygame.Surface((32, 32), pygame.SRCALPHA)
            pygame.draw.rect(icon, S.ACCENT, pygame.Rect(6, 14, 20, 12), border_radius=3)
            pygame.draw.rect(icon, S.GOLD, pygame.Rect(10, 4, 12, 10), border_radius=3)
            pygame.display.set_icon(icon)
        except Exception:
            pass
        self.screen = pygame.display.set_mode((1120, 720), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.running = True
        self.save = SaveData()
        if not self.save.load():
            import time
            self.save.data["created"] = int(time.time())
            self.save.save()
        self.scene: Scene | None = None
        self.editor_scene = None
        self.menu = None
        self.toasts: list = []
        self.audio = Audio(volume=float(self.save.data["options"].get("volume", 80)) / 100.0)
        self.goto(MenuScene(self))

    # -------------------------------------------------- 场景
    def goto(self, scene) -> None:
        if self.scene is not None and hasattr(self.scene, "exit"):
            self.scene.exit()
        self.scene = scene
        if hasattr(scene, "enter"):
            scene.enter()
        if isinstance(scene, MenuScene):
            self.menu = scene

    def toast(self, text: str, color=S.TEXT) -> None:
        self.toasts.append((text, 2.4, color))

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                    break
                if ev.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode((max(800, ev.w),
                                                           max(560, ev.h)),
                                                          pygame.RESIZABLE)
                    if self.scene is not None and hasattr(self.scene, "_build"):
                        self.scene._build()
                    continue
                if self.scene is not None:
                    try:
                        self.scene.handle(ev)
                    except Exception:      # noqa: BLE001
                        # 单次事件处理出错不应该让整个游戏退出
                        import traceback
                        traceback.print_exc()
                        self.toast("操作出错，已忽略", S.BAD)
            if not self.running:
                break
            if self.scene is not None:
                self.scene.update(dt)
                self.scene.draw(self.screen)
            self._draw_toasts(dt)
            pygame.display.flip()
            if pygame.event.peek(pygame.QUIT):
                self.running = False
        self.save.save()
        pygame.quit()

    def _draw_toasts(self, dt: float) -> None:
        out = []
        y = 84
        for text, life, color in self.toasts:
            life -= dt
            if life <= 0:
                continue
            img = S.font(13, True).render(text, True, color)
            tw = img.get_width() + 22
            rect = pygame.Rect(self.screen.get_width() - tw - 18, y, tw, 28)
            S.round_rect(self.screen, rect, S.PANEL2, 8)
            S.round_rect(self.screen, rect, color, 8, 1)
            self.screen.blit(img, (rect.x + 11, rect.centery - img.get_height() // 2))
            y += 34
            out.append((text, life, color))
        self.toasts = out


def bootstrap_content() -> None:
    """首次运行时确保至少有一份可玩的演出。"""
    S.ensure_dirs()
    if not L.list_levels():
        from engine.scenes import default_level_data
        L.save_level(L.Level(default_level_data()), "default.json")


def main() -> int:
    pygame.init()
    bootstrap_content()
    app = App()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
