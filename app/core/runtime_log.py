from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any

from app.core.config import LOGS_ROOT
from app.core.utils import strip_text

RUNTIME_LOG_PATH = LOGS_ROOT / "backend.log"
LOG_SOURCES = {
    "backend.log": LOGS_ROOT / "backend.log",
    "backend.previous.log": LOGS_ROOT / "backend.previous.log",
    "admin-ui.out.log": LOGS_ROOT / "admin-ui.out.log",
    "admin-ui.err.log": LOGS_ROOT / "admin-ui.err.log",
    "download.out.log": LOGS_ROOT / "download.out.log",
    "download.err.log": LOGS_ROOT / "download.err.log",
}


class RuntimeEventLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()

    def reset_for_launch(self) -> None:
        previous_path = self.path.with_name(f"{self.path.stem}.previous{self.path.suffix}")
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 0:
                previous_path.unlink(missing_ok=True)
                try:
                    self.path.replace(previous_path)
                except OSError:
                    previous_path.write_text(
                        self.path.read_text(encoding="utf-8", errors="replace"),
                        encoding="utf-8",
                    )
            self.path.write_text("", encoding="utf-8")

    def append(self, event: str, **fields: Any) -> None:
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        details = " ".join(
            f"{key}={self._format_value(value)}"
            for key, value in fields.items()
            if value is not None and self._format_value(value) != ""
        )
        line = f"{timestamp} | {event}"
        if details:
            line = f"{line} | {details}"
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")

    def tail(self, limit: int = 120, *, newest_first: bool = True) -> str:
        return read_log_source(self.path.name, limit=limit, newest_first=newest_first)

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.3f}"
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        text = str(value).replace("\r", " ").replace("\n", " ").strip()
        if " " in text:
            return json.dumps(text, ensure_ascii=False)
        return text


def read_log_source(source: str = "backend.log", *, limit: int = 120, newest_first: bool = True) -> str:
    source_name = strip_text(source) or "backend.log"
    path = LOG_SOURCES.get(source_name)
    if path is None:
        allowed = ", ".join(sorted(LOG_SOURCES))
        return f"Unknown log source: {source_name}. Allowed: {allowed}"
    if not path.exists():
        return f"No log file yet: {path}"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-max(limit, 1) :]
    if newest_first:
        tail = list(reversed(tail))
    return "\n".join(tail) or f"No log entries yet: {path}"


RUNTIME_EVENTS = RuntimeEventLog(RUNTIME_LOG_PATH)
