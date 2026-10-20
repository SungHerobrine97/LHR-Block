"""剧本（Script）解析器与指令虚拟机。

剧本格式（见 rule/editor.md）：

    角色名字: 语句。 // 对话
    :语句文本。 // 旁白
    角色名字：语句。 \\ 指令 // 注释

指令列表：
    win                    直接胜利
    lose [文本]            直接失败（文本缺省用关卡失败文本）
    drop [n]               立即让 n 个方块下落（默认 1，瞬间到底）
    vfx <name> on|off      激活 / 解除 VFX
    clear                  文本消除（清空对白与字幕）
    reset                  重置舞台
    quit                   关闭游戏
    wipe                   删除存档
    delay <ms>             延迟执行后续指令
    shake <强度>           一次性震屏
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

COMMENT = "//"
SEP_CMD = "\\"

SPEAKER_SPLIT = re.compile(r"[:：]")


class Stmt:
    __slots__ = ("speaker", "text", "commands")

    def __init__(self, speaker: str, text: str, commands: List[str]):
        self.speaker = speaker.strip()
        self.text = text.strip()
        self.commands = commands

    def __repr__(self):
        return f"<Stmt {self.speaker!r} {self.text[:16]!r} cmds={self.commands}>"


def parse(text: str) -> List[Stmt]:
    out: List[Stmt] = []
    for raw in str(text or "").splitlines():
        line = raw
        # 去掉行注释
        ci = line.find(COMMENT)
        if ci >= 0:
            line = line[:ci]
        if not line.strip():
            continue
        if "\\" in line:
            head, _, tail = line.partition(SEP_CMD)
        else:
            head, tail = line, ""
        m = SPEAKER_SPLIT.search(head)
        if m:
            speaker = head[:m.start()].strip()
            body = head[m.end():].strip()
        else:
            speaker, body = "", head.strip()
        # 指令区里 `\` 与 `;` 都视为分隔符，便于连写「\ delay 400 \ win」
        cmds = [c.strip() for c in tail.replace(SEP_CMD, ";").split(";") if c.strip()]
        out.append(Stmt(speaker, body, cmds))
    return out


# ---------------------------------------------------------------- 执行器
class Runner:
    """逐条推进剧本；支持 delay 挂起。"""

    def __init__(self, handlers: Dict[str, Callable] | None = None):
        self.handlers = handlers or {}
        self.queue: List[Stmt] = []
        self.index = 0
        self.active = False
        self.wait_ms = 0
        self.pending_cmds: List[str] = []
        self.auto_advance = 0.0
        self.dwell = 0.0
        self.finished: Optional[Callable] = None

    def load(self, stmts: List[Stmt], on_finish: Optional[Callable] = None,
             dwell: float = 0.0) -> None:
        """dwell > 0 时为「环境演出」：每行自动停留 dwell 秒后推进。"""
        self.queue = list(stmts)
        self.index = 0
        self.active = bool(stmts)
        self.wait_ms = 0
        self.pending_cmds = []
        self.dwell = dwell
        self.auto_advance = dwell if stmts else 0.0
        self.finished = on_finish

    def stop(self) -> None:
        self.queue = []
        self.active = False
        self.pending_cmds = []

    @property
    def current(self) -> Optional[Stmt]:
        if self.active and 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    @property
    def waiting(self) -> bool:
        return self.wait_ms > 0

    def update(self, dt: float) -> None:
        """返回 True 表示刚刚消费了「推进」请求。"""
        if self.wait_ms > 0:
            self.wait_ms -= dt * 1000
            if self.wait_ms > 0:
                return
            self.wait_ms = 0
            self._run_cmds(self.pending_cmds)
            self.pending_cmds = []
            return
        if not self.active:
            return
        if self.auto_advance > 0:
            self.auto_advance -= dt
            if self.auto_advance <= 0:
                self.advance()

    def advance(self) -> None:
        """推进到下一条（玩家按键/超时调用）。"""
        if not self.active:
            return
        st = self.current
        if st is not None and st.commands:
            # 指令在「说出这句」时执行
            delay = None
            rest = []
            for c in st.commands:
                head = c.split(None, 1)
                if head and head[0].lower() in ("delay", "wait") and len(head) > 1:
                    delay = head[1]
                    rest.append(delay)
                    continue
                if delay is not None:
                    rest.append(c)
            # 先把 delay 之前的执行掉，delay 之后的挂起
            # 简化：遇到第一个 delay 立即挂起剩余
            idx = next((i for i, c in enumerate(st.commands)
                        if c.split(None, 1)[0].lower() in ("delay", "wait")), None)
            if idx is None:
                self._run_cmds(st.commands)
            else:
                first = st.commands[idx]
                arg = first.split(None, 1)[1] if len(first.split(None, 1)) > 1 else "0"
                try:
                    self.wait_ms = max(0, int(float(arg)))
                except ValueError:
                    self.wait_ms = 0
                self.pending_cmds = st.commands[idx + 1:]
                self._run_cmds(st.commands[:idx])
        self.index += 1
        if self.index >= len(self.queue):
            self.active = False
            self.auto_advance = 0.0
            cb = self.finished
            self.finished = None
            if cb:
                cb()
        else:
            self.auto_advance = self.dwell

    def _run_cmds(self, cmds: List[str]) -> None:
        for c in cmds:
            parts = c.split(None, 1)
            if not parts:
                continue
            name = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            h = self.handlers.get(name)
            if h:
                h(arg)
            else:
                self.handlers.get("_unknown", lambda a: None)(c)


def split_args(arg: str) -> List[str]:
    return [p for p in re.split(r"[\s,]+", arg.strip()) if p]
