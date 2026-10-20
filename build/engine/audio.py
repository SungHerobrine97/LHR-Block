"""音效与背景音乐。

- 内置合成音（无外部资源）：见 SFX / BGM 两张表，按名称播放。
- 也支持外部文件：把 .ogg/.wav/.mp3 放进 content/audio/，脚本里直接用文件名（不含扩展名）。
- 初始化失败（无声卡）时自动静音，不影响游戏运行。

剧本指令：
    sfx  雷声 0.8     播放音效（音量 0~1，可省略）
    bgm  紧张         循环播放背景音乐
    bgm  off          停止背景音乐
    vol  60           全局音量（0~100）
"""
from __future__ import annotations

import array
import math
import os

import pygame

from . import settings as S

SRATE = 22050
try:  # 在 pygame.init() 之前设定采样格式
    pygame.mixer.pre_init(frequency=SRATE, size=-16, channels=1, buffer=512)
except Exception:  # noqa: BLE001
    pass

AUDIO_DIR = os.path.join(S.CONTENT_DIR, "audio")
FILE_EXT = (".ogg", ".wav", ".mp3")


def _L(wave="sine", f=440.0, dur=0.2, vol=0.5, glide=0.0, at=0.0) -> dict:
    """一个音层：波形、起始频率、时长、音量、滑音目标、起始时刻。"""
    return {"wave": wave, "f": f, "dur": dur, "vol": vol, "glide": glide, "at": at}


def _seq(notes, wave="sine", dur=0.3, vol=0.35, at=0.0, gap=0.0) -> list:
    out = []
    t = at
    for f in notes:
        out.append(_L(wave, f, dur, vol, at=t))
        t += dur + gap
    return out


# ---------------------------------------------------------------- 内置音效
SFX: dict = {
    "ui": [_L("square", 660, 0.05, 0.45)],
    "click": [_L("square", 900, 0.04, 0.40)],
    "tick": [_L("square", 1250, 0.03, 0.35)],
    "step": [_L("square", 420, 0.05, 0.30), _L("noise", 0, 0.04, 0.12)],
    "jump": [_L("sine", 520, 0.10, 0.50, glide=860)],
    "land": [_L("sine", 300, 0.09, 0.40, glide=150)],
    "thud": [_L("square", 96, 0.18, 0.85), _L("sine", 58, 0.22, 0.65)],
    "bell": [_L("sine", 880, 0.55, 0.55), _L("sine", 1320, 0.45, 0.28),
             _L("sine", 1760, 0.35, 0.16)],
    "chime": [_L("sine", 1046, 0.30, 0.50), _L("sine", 1568, 0.26, 0.24)],
    "coin": [_L("square", 988, 0.07, 0.45), _L("square", 1319, 0.22, 0.40)],
    "drum": [_L("sine", 150, 0.20, 0.85, glide=60), _L("noise", 0, 0.06, 0.28)],
    "gong": [_L("sine", 110, 1.10, 0.60), _L("saw", 165, 0.90, 0.20),
             _L("noise", 0, 0.35, 0.16)],
    "thunder": [_L("noise", 0, 1.40, 0.45), _L("sine", 48, 1.20, 0.45, glide=30)],
    "whoosh": [_L("noise", 0, 0.45, 0.30, glide=0, at=0)],
    "buzz": [_L("saw", 130, 0.35, 0.45, glide=90)],
    "heartbeat": [_L("sine", 62, 0.16, 0.75), _L("sine", 55, 0.20, 0.55, at=0.24)],
    "applause": [_L("noise", 0, 1.30, 0.38)],
    "glitch": [_L("square", 320, 0.10, 0.45), _L("square", 940, 0.06, 0.35, at=0.08),
               _L("noise", 0, 0.09, 0.25, at=0.14)],
    "sparkle": [_L("sine", 1760, 0.12, 0.30), _L("sine", 2093, 0.10, 0.22, at=0.08),
                _L("sine", 2637, 0.09, 0.16, at=0.16)],
    "door": [_L("sine", 180, 0.50, 0.55, glide=90), _L("noise", 0, 0.16, 0.18, at=0.34)],
    "alarm": [_L("square", 880, 0.14, 0.42), _L("square", 660, 0.14, 0.42, at=0.18),
              _L("square", 880, 0.14, 0.42, at=0.36)],
    "win": [_L("sine", 523, 0.34, 0.40), _L("sine", 659, 0.34, 0.30),
            _L("sine", 784, 0.34, 0.24), _L("sine", 1046, 0.40, 0.20)],
    "lose": [_L("saw", 220, 0.36, 0.45, glide=110),
             _L("square", 146, 0.40, 0.30)],
}
SFX["lock"] = SFX["thud"]
SFX["rotate"] = [_L("square", 720, 0.05, 0.34), _L("square", 1080, 0.05, 0.26, at=0.05)]
SFX["turn"] = SFX["rotate"]

SFX_LABELS = {
    "ui": "界面提示", "click": "点击", "tick": "滴答", "step": "脚步",
    "jump": "跳跃", "land": "落地", "thud": "落块闷响", "lock": "方块固化",
    "rotate": "方块旋转", "turn": "方块旋转",
    "bell": "铃声", "chime": "清音", "coin": "金币", "drum": "鼓点",
    "gong": "铜锣", "thunder": "雷声", "whoosh": "风声", "buzz": "蜂鸣",
    "heartbeat": "心跳", "applause": "掌声", "glitch": "故障",
    "sparkle": "星光", "door": "开门", "alarm": "警报", "win": "胜利",
    "lose": "失败",
}

# ---------------------------------------------------------------- 内置背景音乐
def _bgm_calm():
    layers = []
    for bar in range(4):
        t = bar * 1.6
        layers += _seq([261.6, 329.6, 392.0, 329.6], dur=0.40, vol=0.20, at=t)
        layers.append(_L("sine", 130.8, 1.5, 0.14, at=t))
    return layers


def _bgm_tense():
    layers = []
    for i in range(16):
        t = i * 0.42
        layers.append(_L("sine", 98.0, 0.16, 0.30, at=t))
        if i % 2 == 0:
            layers.append(_L("square", 1200, 0.03, 0.10, at=t + 0.21))
        if i % 4 == 0:
            layers.append(_L("saw", 73.4, 0.34, 0.12, at=t))
    return layers


def _bgm_ominous():
    layers = [_L("sine", 55.0, 6.0, 0.22), _L("sine", 82.4, 6.0, 0.12)]
    for t in (0.8, 2.6, 4.4):
        layers += [_L("sine", 311.1, 0.9, 0.16), _L("sine", 466.2, 0.7, 0.08)]
        layers[-2]["at"] = t
        layers[-1]["at"] = t
    return layers


def _bgm_waltz():
    layers = []
    for bar in range(4):
        t = bar * 1.8
        layers += _seq([392.0, 261.6, 329.6], dur=0.30, vol=0.18, at=t)
        layers.append(_L("sine", 98.0, 0.9, 0.20, at=t))
    return layers


def _bgm_march():
    layers = []
    for i in range(12):
        t = i * 0.5
        layers.append(_L("sine", 130.0, 0.14, 0.35, glide=70, at=t))
        layers.append(_L("square", 660, 0.10, 0.12, at=t))
        if i % 3 == 0:
            layers.append(_L("noise", 0, 0.08, 0.16, at=t))
    return layers


BGM: dict = {
    "calm": _bgm_calm(),
    "tense": _bgm_tense(),
    "ominous": _bgm_ominous(),
    "waltz": _bgm_waltz(),
    "march": _bgm_march(),
}

BGM_LABELS = {
    "calm": "平静", "tense": "紧张", "ominous": "诡异",
    "waltz": "圆舞曲", "march": "进行曲",
}


def resolve_sfx(name: str) -> str:
    """支持中文别名（如「雷声」→ thunder）；找不到时原样返回（可能是文件名）。"""
    n = str(name or "").strip()
    if n in SFX:
        return n
    for key, lab in SFX_LABELS.items():
        if lab == n:
            return key
    return n


def resolve_bgm(name: str) -> str:
    n = str(name or "").strip()
    if n in BGM:
        return n
    for key, lab in BGM_LABELS.items():
        if lab == n:
            return key
    return n


class Audio:
    def __init__(self, enabled: bool = True, volume: float = 0.8):
        self.enabled = enabled
        self.ok = False
        self.master = max(0.0, min(1.0, volume))
        self._cache: dict = {}
        self._bgm_snd = None
        self._bgm_file = False
        self.bgm_name = None
        self.muted = False
        if not enabled:
            return
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=SRATE, size=-16, channels=1, buffer=512)
            self.ok = pygame.mixer.get_init() is not None
        except Exception:  # noqa: BLE001
            self.ok = False

    # -------------------------------------------------- 基础
    @property
    def sr(self) -> int:
        try:
            info = pygame.mixer.get_init()
            return info[0] if info else SRATE
        except Exception:  # noqa: BLE001
            return SRATE

    def set_volume(self, v: float) -> None:
        self.master = max(0.0, min(1.0, v))
        if self._bgm_snd is not None and not self._bgm_file:
            try:
                self._bgm_snd.set_volume(self.master * 0.7)
            except Exception:  # noqa: BLE001
                pass
        elif self._bgm_file:
            try:
                pygame.mixer.music.set_volume(self.master * 0.7)
            except Exception:  # noqa: BLE001
                pass

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        self.set_volume(0.0 if self.muted else self._last_volume())
        return self.muted

    def _last_volume(self) -> float:
        return max(0.05, self.master if self.master > 0.001 else 0.8)

    # -------------------------------------------------- 合成
    def _encode(self, layers: list) -> bytes:
        total = max((l["at"] + l["dur"]) for l in layers)
        n = max(1, int(self.sr * total))
        buf = [0.0] * n
        rng_state = [12345]

        def rnd():
            rng_state[0] = (rng_state[0] * 1103515245 + 12345) & 0x7FFFFFFF
            return (rng_state[0] / 0x7FFFFFFF) * 2.0 - 1.0

        for l in layers:
            wave = l["wave"]
            f0 = float(l["f"])
            f1 = float(l["glide"] or f0)
            dur = float(l["dur"])
            vol = float(l["vol"])
            start = int(self.sr * float(l["at"]))
            m = max(1, int(self.sr * dur))
            aa = max(1, int(self.sr * 0.006))
            for i in range(m):
                k = i / max(1, m - 1)
                freq = f0 + (f1 - f0) * k
                ph = freq * (i / self.sr)
                if wave == "square":
                    v = 1.0 if (ph % 1.0) < 0.5 else -1.0
                elif wave == "saw":
                    v = 2.0 * ((ph % 1.0) - 0.5)
                elif wave == "noise":
                    v = rnd()
                else:
                    v = math.sin(2.0 * math.pi * ph)
                if i < aa:
                    env = i / aa
                else:
                    env = (1.0 - (i - aa) / max(1, m - aa)) ** 1.5
                idx = start + i
                if idx < n:
                    buf[idx] += v * env * vol
        # 归一化 + 编码
        peak = max(0.0001, max(abs(x) for x in buf))
        gain = 0.92 / peak
        try:
            fmt = pygame.mixer.get_init()
            size = fmt[1] if fmt else -16
            chans = fmt[2] if fmt else 1
        except Exception:  # noqa: BLE001
            size, chans = -16, 1
        if size == 8:
            arr = array.array("B", [max(0, min(255, int((x * gain + 1) * 127.5)))
                                    for x in buf])
        else:
            arr = array.array("h", [max(-32767, min(32767, int(x * gain * 32767)))
                                    for x in buf])
        if chans == 2:
            src = list(arr)
            arr = array.array(arr.typecode, [v for v in src for _ in (0, 1)])
        return arr.tobytes()

    def _sound(self, name: str):
        """内置合成音 → Sound；缓存。"""
        if name in self._cache:
            return self._cache[name]
        layers = SFX.get(name)
        if layers is None:
            return None
        try:
            snd = pygame.mixer.Sound(buffer=self._encode(layers))
        except Exception:  # noqa: BLE001
            self.ok = False
            return None
        self._cache[name] = snd
        return snd

    # -------------------------------------------------- 文件
    @staticmethod
    def find_file(name: str):
        if not name:
            return None
        base = str(name).strip()
        for ext in ("",) + FILE_EXT:
            p = os.path.join(AUDIO_DIR, base + ext)
            if os.path.isfile(p):
                return p
        for fn in sorted(os.listdir(AUDIO_DIR)) if os.path.isdir(AUDIO_DIR) else []:
            stem, ext = os.path.splitext(fn)
            if stem.lower() == base.lower() and ext.lower() in FILE_EXT:
                return os.path.join(AUDIO_DIR, fn)
        return None

    @staticmethod
    def list_files() -> list:
        out = []
        if os.path.isdir(AUDIO_DIR):
            for fn in sorted(os.listdir(AUDIO_DIR)):
                if os.path.splitext(fn)[1].lower() in FILE_EXT:
                    out.append(os.path.splitext(fn)[0])
        return out

    @staticmethod
    def list_sfx() -> list:
        return sorted(SFX.keys())

    @staticmethod
    def list_bgm() -> list:
        return sorted(BGM.keys()) + Audio.list_files()

    # -------------------------------------------------- 播放
    def play(self, name: str, vol: float = 1.0) -> bool:
        if not self.ok or self.muted:
            return False
        name = str(name or "").strip()
        if not name:
            return False
        path = self.find_file(name)
        if path:
            try:
                snd = pygame.mixer.Sound(path)
                snd.set_volume(max(0.0, min(1.0, vol)) * self.master)
                snd.play()
                return True
            except Exception:  # noqa: BLE001
                return False
        snd = self._sound(name)
        if snd is None:
            return False
        try:
            snd.set_volume(max(0.0, min(1.0, vol)) * self.master)
            snd.play()
            return True
        except Exception:  # noqa: BLE001
            return False

    def bgm(self, name: str, vol: float = 1.0) -> bool:
        name = str(name or "").strip()
        if name.lower() in ("off", "stop", "none", "0", "停"):
            self.stop_bgm()
            return True
        self.stop_bgm()
        self.bgm_name = name
        if not self.ok or self.muted:
            return False
        path = self.find_file(name)
        if path:
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(max(0.0, min(1.0, vol)) * self.master * 0.7)
                pygame.mixer.music.play(loops=-1, fade_ms=400)
                self._bgm_file = True
                return True
            except Exception:  # noqa: BLE001
                self._bgm_file = False
        layers = BGM.get(name)
        if layers is None:
            return False
        try:
            snd = pygame.mixer.Sound(buffer=self._encode(layers))
            snd.set_volume(max(0.0, min(1.0, vol)) * self.master * 0.7)
            snd.play(loops=-1, fade_ms=400)
            self._bgm_snd = snd
            self._bgm_file = False
            return True
        except Exception:  # noqa: BLE001
            return False

    def stop_bgm(self) -> None:
        self.bgm_name = None
        try:
            if self._bgm_snd is not None:
                self._bgm_snd.stop()
            self._bgm_snd = None
        except Exception:  # noqa: BLE001
            pass
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:  # noqa: BLE001
            pass
        self._bgm_file = False

    # -------------------------------------------------- 便捷
    def jump(self) -> None:
        self.play("jump")

    def lock(self) -> None:
        self.play("thud")

    def rotate(self) -> None:
        self.play("rotate", 0.7)

    def win(self) -> None:
        self.play("win")

    def lose(self) -> None:
        self.play("lose")

    def ui(self) -> None:
        self.play("ui", 0.6)
