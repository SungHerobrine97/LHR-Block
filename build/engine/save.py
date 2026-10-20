"""存档读写。"""
from __future__ import annotations

import json
import os
import time

from . import settings as S

VERSION = 1
DEFAULT = {
    "version": VERSION,
    "created": 0,
    "last_level": None,
    "levels": {},        # id -> {cleared, best_row, attempts, clears, best_ms}
    "seen": [],          # 已读剧情 id
    "options": {"sound": True, "show_ghost": True, "volume": 80},
}


class SaveData:
    def __init__(self, path: str | None = None):
        self.path = path or S.SAVE_FILE
        self.data = json.loads(json.dumps(DEFAULT))

    # -------------------------------------------------- IO
    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def load(self) -> bool:
        if not self.exists():
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return False
        merged = json.loads(json.dumps(DEFAULT))
        for k, v in (raw or {}).items():
            merged[k] = v
        merged["version"] = VERSION
        self.data = merged
        return True

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    def wipe(self) -> bool:
        self.data = json.loads(json.dumps(DEFAULT))
        self.data["created"] = int(time.time())
        try:
            if os.path.isfile(self.path):
                os.remove(self.path)
        except OSError:
            pass
        self.save()
        return True

    # -------------------------------------------------- 便捷访问
    def level(self, lid: str) -> dict:
        lv = self.data["levels"].get(lid)
        if lv is None:
            lv = {"cleared": False, "best_row": None, "attempts": 0,
                  "clears": 0, "best_ms": None}
            self.data["levels"][lid] = lv
        return lv

    def record_attempt(self, lid: str) -> None:
        self.level(lid)["attempts"] += 1
        self.data["last_level"] = lid

    def record_clear(self, lid: str, ms: int | None = None) -> None:
        lv = self.level(lid)
        lv["cleared"] = True
        lv["clears"] += 1
        if ms is not None:
            if lv.get("best_ms") is None or ms < lv["best_ms"]:
                lv["best_ms"] = ms

    def record_height(self, lid: str, row: int) -> None:
        lv = self.level(lid)
        if lv.get("best_row") is None or row < lv["best_row"]:
            lv["best_row"] = row

    def mark_seen(self, sid: str) -> None:
        if sid and sid not in self.data["seen"]:
            self.data["seen"].append(sid)

    def has_seen(self, sid: str) -> bool:
        return bool(sid) and sid in self.data["seen"]

    def summary(self) -> str:
        lv = self.data["levels"]
        cleared = sum(1 for v in lv.values() if v.get("cleared"))
        return f"已通过 {cleared} / {len(lv)} 场演出"
