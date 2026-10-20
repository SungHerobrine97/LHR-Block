"""关卡数据模型 + 内容加载（关卡 / 剧情 / 特色玩法预设）。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from . import settings as S
from .scriptvm import parse

DEFAULTS: Dict[str, Any] = {
    "id": "untitled",
    "title": "未命名演出",
    "subtitle": "",
    "author": "无名 Mayor",
    "stage": {"width": 10, "height": 20},
    "blocks": {
        "pool": ["I", "O", "T", "S", "Z", "J", "L"],
        "allow_rotation": True,     # 生成时是否随机朝向
        "player_rotate": True,      # 玩家能否用 X 键旋转（固化后一律不可改）
        "hover": "follow",          # follow | random | manual
        "aim_time": [2.0, 9.9],     # 倒计时范围（<10 秒，最小 2 秒）
        "fall_interval": 0.30,      # 每格下落耗时
        "fall_interval_min": 0.10,
        "ramp": 0.985,              # 每次固化后的加速系数
        "preview": True,
    },
    "player": {
        "spawn_col": None,
        "move_speed": 6.4,
        "jump_height": 2.6,      # 可跳上约 2 格高的方块（3 格需借助跳+跨）
        "gravity": 34.0,
        "climb": 1,
        "air_control": 1.0,
    },
    "goal": {"type": "reach_row", "row": 0, "seconds": 60, "count": 20},
    "fail": {
        "text": "败北",
        "texts": {},
        "crush": True,      # 被下落的方块命中（PRD 基础规则）
        "buried": True,     # 被困在封闭空间内（PRD 基础规则）
        "stuck": False,     # 再也爬不上去（可选硬核规则）
        "overflow": False,  # 舞台被填满（可选；默认不判负，方块改为不再落下）
    },
    "vfx": [],
    "audio": {"bgm": "", "volume": 100},   # 开演循环音乐（内置名或 content/audio 文件）与音量
    "events": {},
    "terrain": [],
    "tags": [],
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Level:
    def __init__(self, data: dict | None = None, path: str | None = None):
        self.data = _deep_merge(DEFAULTS, data or {})
        self.path = path

    # -------------------------------------------------- 属性
    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    @property
    def id(self) -> str:
        return self.data.get("id") or "untitled"

    @property
    def title(self) -> str:
        return self.data.get("title") or self.id

    @property
    def width(self) -> int:
        return int(self.data["stage"]["width"])

    @property
    def height(self) -> int:
        return int(self.data["stage"]["height"])

    @property
    def goal_row(self) -> int:
        g = self.data["goal"]
        return int(g.get("row", 0))

    @property
    def fail_texts(self) -> dict:
        return self.data["fail"].get("texts") or {}

    def fail_text(self, reason: str) -> str:
        t = self.fail_texts.get(reason)
        if t:
            return t
        return self.data["fail"].get("text") or DEFAULTS["fail"]["text"]

    def event(self, name: str):
        return self.data.get("events", {}).get(name)

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self.data))

    def summary(self) -> str:
        g = self.data["goal"]
        mapping = {
            "reach_row": f"到达第 {self.goal_row} 行",
            "survive": f"坚持 {int(g.get('seconds', 60))} 秒",
            "lock_count": f"承受 {int(g.get('count', 20))} 块",
            "none": "由剧本来定",
        }
        return mapping.get(g.get("type"), "到达舞台顶部")


# ---------------------------------------------------------------- 载入
def safe_name(s: str) -> str:
    keep = []
    for ch in (s or "").strip():
        keep.append(ch if (ch.isalnum() or ch in "-_ ()（）") else "_")
    return ("".join(keep) or "untitled")[:64]


def load_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_json(path: str, data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def load_level(path: str) -> Level | None:
    raw = load_json(path)
    if raw is None:
        return None
    raw.setdefault("id", os.path.splitext(os.path.basename(path))[0])
    return Level(raw, path)


def list_levels() -> List[Level]:
    S.ensure_dirs()
    out = []
    for fn in sorted(os.listdir(S.LEVELS_DIR)):
        if not fn.lower().endswith(".json"):
            continue
        lv = load_level(os.path.join(S.LEVELS_DIR, fn))
        if lv:
            out.append(lv)
    out.sort(key=lambda x: (x.data.get("order", 99), x.id))
    return out


def save_level(lv: Level, filename: str | None = None) -> str:
    S.ensure_dirs()
    fn = filename or (safe_name(lv.id) + ".json")
    if not fn.lower().endswith(".json"):
        fn += ".json"
    path = os.path.join(S.LEVELS_DIR, fn)
    save_json(path, lv.to_dict())
    lv.path = path
    return path


def load_story(name: str) -> str:
    S.ensure_dirs()
    for ext in ("", ".story", ".txt"):
        p = os.path.join(S.STORIES_DIR, name + ext)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return ""
    return ""


def list_stories() -> List[str]:
    S.ensure_dirs()
    out = []
    for fn in sorted(os.listdir(S.STORIES_DIR)):
        if fn.lower().endswith((".story", ".txt")):
            out.append(fn)
    return out


def save_story(name: str, text: str) -> str:
    S.ensure_dirs()
    p = os.path.join(S.STORIES_DIR, name if name.endswith((".story", ".txt")) else name + ".story")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def load_preset(path: str) -> dict | None:
    return load_json(path)


def list_presets() -> List[dict]:
    S.ensure_dirs()
    out = []
    for fn in sorted(os.listdir(S.PRESETS_DIR)):
        if not fn.lower().endswith(".json"):
            continue
        raw = load_json(os.path.join(S.PRESETS_DIR, fn))
        if raw:
            raw.setdefault("id", os.path.splitext(fn)[0])
            raw["_file"] = fn
            out.append(raw)
    return out


def apply_preset(lv: Level, preset: dict) -> Level:
    """把特色玩法预设叠加到关卡上。"""
    body = {k: v for k, v in preset.items() if k not in ("id", "_file", "name", "desc")}
    lv.data = _deep_merge(lv.data, body)
    lv.data["tags"] = sorted(set(lv.data.get("tags", []) + [preset.get("id", "preset")]))
    return lv


def story_statements(text: str):
    return parse(text)
