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
        "concurrent": 1,            # 舞台上同时存在的方块数（1 = 一次一块）
        "spawn_gap": 0.35,          # 多块模式下两块之间的生成间隔（秒）
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
    "events": [],       # 事件列表：{trigger, param, mode, script, once}（也兼容旧的字典写法）
    "shapes": [],       # 自定义形状：{id, name, color, cells}
    "terrain": [],
    "tags": [],
}

# ---------------------------------------------------------------- 触发时机
# (trigger, 中文名, 参数类型)；参数类型 None / "int" / "float" / "shape" / "key"
TRIGGERS = [
    ("on_start", "开演时", None),
    ("on_spawn", "方块出现时", None),
    ("on_aim_end", "倒计时结束、开始下落时", None),
    ("on_lock", "方块固化后", None),
    ("on_row", "小人抵达第 N 行", "int"),
    ("on_height", "最高抵达第 N 行", "int"),
    ("on_time", "开演后第 N 秒", "float"),
    ("on_lock_count", "已固化 N 块", "int"),
    ("on_piece", "出现某个形状时", "shape"),
    ("on_key", "玩家按下某键时", "key"),
    ("on_win", "胜利时", None),
    ("on_lose", "失败时", None),
]
TRIGGER_NAMES = {t: n for t, n, _ in TRIGGERS}
TRIGGER_KINDS = {t: k for t, _, k in TRIGGERS}
TRIGGER_KEYS = [t for t, _, _ in TRIGGERS]

MODES = ("ambient", "blocking")
MODE_LABELS = {"ambient": "自动推进（不暂停）", "blocking": "等待玩家确认"}


def trigger_name(trigger: str) -> str:
    return TRIGGER_NAMES.get(str(trigger), str(trigger))


def trigger_label(trigger: str, param=None) -> str:
    """生成「触发时机 + 参数」的可读描述，如「小人抵达第 5 行」。"""
    base = trigger_name(trigger)
    if param is None or param == "":
        return base
    kind = TRIGGER_KINDS.get(trigger)
    if kind == "shape":
        return f"{base}：{param}"
    if kind == "key":
        return f"{base}：{str(param).upper()}"
    if "N" in base:
        return base.replace("N", str(param))
    return f"{base}（{param}）"


def _coerce_param(trigger: str, value):
    kind = TRIGGER_KINDS.get(trigger)
    if value is None or value == "":
        return None
    if kind in (None,):
        return None
    if kind == "int":
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0
    if kind == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    return str(value)


def split_trigger(key: str):
    """'on_row:5' -> ('on_row', 5)；未知前缀原样返回。"""
    base, _, arg = str(key).partition(":")
    if base in TRIGGER_NAMES:
        return base, _coerce_param(base, arg)
    return str(key), None


def _event_from_pair(key, val) -> dict:
    trigger, param = split_trigger(key)
    ev = {"trigger": trigger, "param": param, "script": "",
          "mode": "blocking" if trigger == "on_start" else "ambient",
          "once": True}
    if isinstance(val, str):
        ev["script"] = val
    elif isinstance(val, dict):
        ev["script"] = str(val.get("script", "") or "")
        ev["mode"] = str(val.get("mode") or ev["mode"])
        if "story" in val:
            ev["story"] = str(val["story"])
        if val.get("param") is not None:
            ev["param"] = _coerce_param(trigger, val.get("param"))
        ev["once"] = bool(val.get("once", True)) and \
            not (val.get("repeat") is False)
    elif isinstance(val, list):
        ev["script"] = "\n".join(str(x) for x in val)
    return ev


def normalize_events(raw) -> List[dict]:
    """把 dict / list 两种写法的 events 统一成列表形式。"""
    out: List[dict] = []
    if isinstance(raw, dict):
        for key, val in raw.items():
            out.append(_event_from_pair(key, val))
    elif isinstance(raw, list):
        for i, item in enumerate(raw):
            if isinstance(item, dict):
                trigger = str(item.get("trigger") or item.get("on") or "on_lock")
                ev = {"trigger": trigger,
                      "param": _coerce_param(trigger, item.get("param")),
                      "script": str(item.get("script", "") or ""),
                      "mode": str(item.get("mode") or
                                  ("blocking" if trigger == "on_start" else "ambient")),
                      "once": bool(item.get("once", True))
                      and not (item.get("repeat") is False)}
                if item.get("story"):
                    ev["story"] = str(item["story"])
                if item.get("id"):
                    ev["id"] = str(item["id"])
                ev["_i"] = i
                out.append(ev)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                out.append(_event_from_pair(item[0], item[1]))
    return out


# ---------------------------------------------------------------- 形状
def cells_from_text(text) -> List[List[int]]:
    """把 '010/111' 或 ['010', '111'] 转成格子坐标列表。"""
    rows = text.split("/") if isinstance(text, str) else list(text or [])
    out: List[List[int]] = []
    for y, row in enumerate(rows):
        for x, ch in enumerate(str(row).strip()):
            if ch in "#1*xX":
                out.append([x, y])
    return out


def cells_to_text(cells) -> str:
    cells = [(int(c[0]), int(c[1])) for c in cells or []]
    if not cells:
        return ""
    w = max(x for x, _ in cells) + 1
    h = max(y for _, y in cells) + 1
    s = set(cells)
    return "/".join("".join("1" if (x, y) in s else "0" for x in range(w))
                    for y in range(h))


def normalize_shape(raw: dict) -> dict | None:
    """规整一个自定义形状定义：{id, name, color, cells}。"""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("id") or raw.get("kind") or "").strip()
    cells = raw.get("cells")
    if isinstance(cells, str):
        cells = cells_from_text(cells)
    elif cells is None and raw.get("text"):
        cells = cells_from_text(raw.get("text"))
    cells = [(int(c[0]), int(c[1])) for c in (cells or []) if len(c) >= 2]
    if not kind or not cells:
        return None
    return {"id": kind, "name": str(raw.get("name") or kind),
            "color": int(raw.get("color", 1) or 1),
            "cells": [[x, y] for x, y in cells]}


def register_level_shapes(lv: "Level") -> List[str]:
    """把关卡自带的自定义形状注册进形状表，返回成功注册的 id 列表。"""
    from . import pieces
    out: List[str] = []
    for raw in (lv.get("shapes") or []):
        sh = normalize_shape(raw)
        if not sh:
            continue
        if pieces.register_shape(sh["id"], [tuple(c) for c in sh["cells"]],
                                 sh["color"], sh["name"]):
            out.append(sh["id"])
    return out


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

    # -------------------------------------------------- 事件
    def events_list(self) -> List[dict]:
        """规范化后的事件列表（兼容旧字典写法）。"""
        return normalize_events(self.data.get("events"))

    def event(self, name: str):
        """兼容接口：取某个触发时机的第一条事件值。"""
        raw = self.data.get("events")
        if isinstance(raw, dict):
            return raw.get(name)
        trigger, param = split_trigger(name)
        for i, ev in enumerate(normalize_events(raw)):
            if ev.get("trigger") == trigger and ev.get("param") == param:
                return {"script": ev.get("script", ""), "mode": ev.get("mode", "ambient"),
                        "once": ev.get("once", True), "_i": i}
        return None

    def ensure_events_list(self) -> List[dict]:
        """把 data['events'] 就地转成列表并返回。"""
        if not isinstance(self.data.get("events"), list):
            evs = normalize_events(self.data.get("events"))
            self.data["events"] = [{k: v for k, v in e.items() if k != "_i"}
                                   for e in evs]
        return self.data["events"]

    def add_event(self, trigger: str = "on_lock", param=None,
                  script: str = "", mode: str = "ambient") -> dict:
        ev = {"trigger": trigger, "param": _coerce_param(trigger, param),
              "script": script, "mode": mode, "once": True}
        self.ensure_events_list().append(ev)
        return ev

    # -------------------------------------------------- 形状
    def shapes_list(self) -> List[dict]:
        out = []
        for raw in (self.get("shapes") or []):
            sh = normalize_shape(raw)
            if sh:
                out.append(sh)
        return out

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


def export_level(lv: Level, path: str) -> bool:
    """把单个演出导出为 JSON 文件（含自定义形状与事件）。"""
    data = lv.to_dict()
    data["_format"] = "climbtower.level"
    data["_version"] = 1
    return save_json(path, data)


def export_bundle(levels: List[Level], path: str) -> bool:
    """把多份演出打包成一个 JSON（便于备份 / 分享）。"""
    data = {"_format": "climbtower.bundle", "_version": 1,
            "levels": [lv.to_dict() for lv in levels]}
    return save_json(path, data)


def import_level(path: str) -> Level | None:
    """从 JSON 载入一份演出（自动识别单文件 / 打包文件，只取第一份）。"""
    out = import_levels(path)
    return out[0] if out else None


def import_levels(path: str) -> List[Level]:
    """从 JSON 载入演出，兼容单文件与 {"levels": [...]} 打包格式。"""
    raw = load_json(path)
    if not isinstance(raw, dict):
        return []
    base = os.path.splitext(os.path.basename(path))[0]
    items: List[dict] = []
    if isinstance(raw.get("levels"), list):
        items = [x for x in raw["levels"] if isinstance(x, dict)]
    else:
        items = [raw]
    out: List[Level] = []
    for i, item in enumerate(items):
        item = dict(item)
        item.pop("_format", None)
        item.pop("_version", None)
        if not item.get("id"):
            item["id"] = base if len(items) == 1 else f"{base}_{i + 1}"
        out.append(Level(item))
    return out


def import_level_file(path: str, overwrite: bool = True) -> List[str]:
    """导入并安装到 content/levels，返回写入的文件名列表。"""
    S.ensure_dirs()
    written = []
    for lv in import_levels(path):
        fn = safe_name(lv.id) + ".json"
        dst = os.path.join(S.LEVELS_DIR, fn)
        if os.path.exists(dst) and not overwrite:
            n = 1
            while os.path.exists(os.path.join(S.LEVELS_DIR, fn)):
                n += 1
                fn = f"{safe_name(lv.id)}_{n}.json"
            dst = os.path.join(S.LEVELS_DIR, fn)
        save_level(lv, fn)
        written.append(fn)
    return written


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
