from __future__ import annotations

import argparse
import json
import locale
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any


APP_VERSION = "0.1.0"
DEFAULT_REFRESH_SECONDS = 60

LANGUAGE_OPTIONS = ["system", "zh-TW", "en"]
THEME_OPTIONS = ["system", "light", "dark"]
DEFAULT_OPACITY_PERCENT = 70

TRANSLATIONS = {
    "zh-TW": {
        "loading": "\u8f09\u5165\u4e2d...",
        "no_usage": "\u6c92\u6709\u7528\u91cf\u8cc7\u6599",
        "unknown_limit": "\u672a\u77e5\u9650\u5236",
        "hour_limit": "{value:g} \u5c0f\u6642\u9650\u5236",
        "day_limit": "{value:g} \u5929\u9650\u5236",
        "reset_unknown": "\u91cd\u7f6e\u6642\u9593\u672a\u77e5",
        "reset_at": "\u91cd\u7f6e {time}",
        "login_error": "Codex \u767b\u5165\u9700\u8981\u8655\u7406\u3002\u8acb\u958b\u555f Codex \u4e26\u91cd\u65b0\u6574\u7406 ChatGPT \u767b\u5165\u72c0\u614b\u3002",
        "read_error": "\u7121\u6cd5\u8b80\u53d6 Codex \u7528\u91cf\u3002\n{message}",
        "tray_show": "\u986f\u793a",
        "tray_exit": "\u7d50\u675f",
        "tray_no_data": "Codex \u7528\u91cf\u5c1a\u672a\u53d6\u5f97",
    },
    "en": {
        "loading": "Loading...",
        "no_usage": "No usage data",
        "unknown_limit": "Unknown limit",
        "hour_limit": "{value:g} hour limit",
        "day_limit": "{value:g} day limit",
        "reset_unknown": "Reset unknown",
        "reset_at": "Resets {time}",
        "login_error": "Codex login needs attention. Open Codex and refresh your ChatGPT login.",
        "read_error": "Unable to read Codex usage.\n{message}",
        "tray_show": "Show",
        "tray_exit": "Exit",
        "tray_no_data": "Codex usage not loaded yet",
    },
}

THEMES = {
    "light": {
        "panel": "#fff3f8",
        "card": "#ffffff",
        "border": "#f3b6cf",
        "text": "#3b1026",
        "muted": "#8a5570",
        "accent": "#d63384",
        "control": "#fde8f1",
        "control_active": "#f8c7dc",
        "slider": "#f3b6cf",
        "slider_fill": "#d63384",
        "error": "#b42318",
    },
    "dark": {
        "panel": "#17111f",
        "card": "#23172f",
        "border": "#5f3a85",
        "text": "#f5ecff",
        "muted": "#bda9d6",
        "accent": "#c084fc",
        "control": "#21162d",
        "control_active": "#3a2550",
        "slider": "#3a2550",
        "slider_fill": "#c084fc",
        "error": "#ffb4c8",
    },
}


class CodexAppServerError(RuntimeError):
    pass


@dataclass
class LimitWindow:
    label: str
    used_percent: float | None
    remaining_percent: float | None
    window_minutes: int | None
    resets_at: str | None


@dataclass
class RateLimitBucket:
    limit_id: str
    name: str
    plan_type: str | None
    primary: LimitWindow | None
    secondary: LimitWindow | None
    reached_type: str | None


@dataclass
class RateLimitSnapshot:
    buckets: list[RateLimitBucket]
    reset_credits: int | None
    fetched_at: str


@dataclass
class UsageDisplayItem:
    window_minutes: int | None
    remaining_percent: float | None
    resets_at: str | None


class CodexAppServerClient:
    def __init__(self, codex_command: str = "codex") -> None:
        self.codex_command = codex_command
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._responses: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._stderr: queue.Queue[str] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def start(self) -> None:
        if self.process is not None:
            return
        if shutil.which(self.codex_command) is None:
            raise CodexAppServerError(
                f"Cannot find '{self.codex_command}'. Install or open Codex so the CLI is on PATH."
            )

        self.process = subprocess.Popen(
            [self.codex_command, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader_thread.start()
        self._stderr_thread.start()

        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex_usage_widget",
                    "title": "Codex Usage Widget",
                    "version": APP_VERSION,
                },
                "capabilities": {"experimentalApi": True},
            },
            timeout=20,
        )
        self.notify("initialized", {})

    def close(self) -> None:
        proc = self.process
        self.process = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def read_rate_limits(self) -> RateLimitSnapshot:
        self.start()
        result = self.request("account/rateLimits/read", {}, timeout=30)
        return parse_rate_limits(result)

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: int = 15) -> Any:
        request_id = self._allocate_id()
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._responses[request_id] = response_queue
        self._send({"method": method, "id": request_id, "params": params or {}})
        try:
            response = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise CodexAppServerError(f"Timed out waiting for {method}. {self._stderr_tail()}") from exc
        finally:
            self._responses.pop(request_id, None)

        if "error" in response:
            message = response["error"].get("message", "Unknown app-server error")
            raise CodexAppServerError(f"{method} failed: {message}")
        return response.get("result", {})

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"method": method, "params": params or {}})

    def _allocate_id(self) -> int:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            return request_id

    def _send(self, message: dict[str, Any]) -> None:
        proc = self.process
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise CodexAppServerError(f"Codex app-server is not running. {self._stderr_tail()}")
        proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    def _read_stdout(self) -> None:
        proc = self.process
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            message_id = message.get("id")
            if message_id in self._responses and "method" not in message:
                self._responses[message_id].put(message)
            elif message_id is not None and "method" in message:
                self._reply_unsupported_request(message_id, message.get("method", "unknown"))

    def _read_stderr(self) -> None:
        proc = self.process
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            self._stderr.put(line.strip())

    def _reply_unsupported_request(self, request_id: int, method: str) -> None:
        try:
            self._send(
                {
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Client cannot satisfy server request: {method}",
                    },
                }
            )
        except CodexAppServerError:
            pass

    def _stderr_tail(self) -> str:
        lines: list[str] = []
        while not self._stderr.empty():
            lines.append(self._stderr.get_nowait())
        return " ".join(lines[-3:])


def parse_rate_limits(result: dict[str, Any]) -> RateLimitSnapshot:
    buckets_by_id = result.get("rateLimitsByLimitId")
    if isinstance(buckets_by_id, dict) and buckets_by_id:
        raw_buckets = list(buckets_by_id.values())
    elif result.get("rateLimits"):
        raw_buckets = [result["rateLimits"]]
    else:
        raw_buckets = []

    buckets = [parse_bucket(bucket) for bucket in raw_buckets if isinstance(bucket, dict)]
    reset_credits = None
    credits = result.get("rateLimitResetCredits")
    if isinstance(credits, dict) and isinstance(credits.get("availableCount"), int):
        reset_credits = credits["availableCount"]

    return RateLimitSnapshot(
        buckets=buckets,
        reset_credits=reset_credits,
        fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def parse_bucket(bucket: dict[str, Any]) -> RateLimitBucket:
    limit_id = str(bucket.get("limitId") or "unknown")
    name = str(bucket.get("limitName") or limit_id)
    return RateLimitBucket(
        limit_id=limit_id,
        name=name,
        plan_type=bucket.get("planType"),
        primary=parse_window("primary", bucket.get("primary")),
        secondary=parse_window("secondary", bucket.get("secondary")),
        reached_type=bucket.get("rateLimitReachedType"),
    )


def parse_window(label: str, raw: Any) -> LimitWindow | None:
    if not isinstance(raw, dict):
        return None
    used_percent = number_or_none(raw.get("usedPercent"))
    remaining_percent = None if used_percent is None else max(0.0, 100.0 - used_percent)
    resets_at = raw.get("resetsAt")
    return LimitWindow(
        label=label,
        used_percent=used_percent,
        remaining_percent=remaining_percent,
        window_minutes=raw.get("windowDurationMins"),
        resets_at=format_unix_time(resets_at) if isinstance(resets_at, (int, float)) else None,
    )


def number_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def format_unix_time(value: int | float) -> str:
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def snapshot_to_text(snapshot: RateLimitSnapshot) -> str:
    if not snapshot.buckets:
        return "No Codex rate-limit buckets were returned."

    lines: list[str] = []
    for bucket in snapshot.buckets:
        plan = f" ({bucket.plan_type})" if bucket.plan_type else ""
        lines.append(f"{bucket.name}{plan}")
        for window in [bucket.primary, bucket.secondary]:
            if window is None:
                continue
            remaining = format_percent(window.remaining_percent)
            used = format_percent(window.used_percent)
            reset = window.resets_at or "unknown"
            duration = f"{window.window_minutes}m" if window.window_minutes else "unknown window"
            lines.append(f"  {window.label}: {remaining} remaining, {used} used, resets {reset} ({duration})")
        if bucket.reached_type:
            lines.append(f"  limit reached: {bucket.reached_type}")
    if snapshot.reset_credits is not None:
        lines.append(f"Reset credits: {snapshot.reset_credits}")
    lines.append(f"Fetched: {snapshot.fetched_at}")
    return "\n".join(lines)


def format_percent(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value.is_integer():
        return f"{int(value)}%"
    return f"{value:.1f}%"


def snapshot_to_display_items(snapshot: RateLimitSnapshot) -> list[UsageDisplayItem]:
    items: list[UsageDisplayItem] = []
    for bucket in snapshot.buckets:
        for window in [bucket.primary, bucket.secondary]:
            if window is None:
                continue
            items.append(
                UsageDisplayItem(
                    window_minutes=window.window_minutes,
                    remaining_percent=window.remaining_percent,
                    resets_at=window.resets_at,
                )
            )
    return items


class UsageWidget:
    def __init__(self, client: CodexAppServerClient, refresh_seconds: int) -> None:
        import tkinter as tk

        self.tk = tk
        self.client = client
        self.refresh_seconds = refresh_seconds
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.closed = False
        self.has_usage_view = False
        self.drag_origin: tuple[int, int] | None = None
        self.language_mode = "system"
        self.theme_mode = "system"
        self.opacity_percent = DEFAULT_OPACITY_PERCENT
        self.current_items: list[UsageDisplayItem] = []
        self.cards: list[dict[str, Any]] = []
        self.message_label: Any | None = None
        self.opacity_canvas: Any | None = None
        self.opacity_value_label: Any | None = None
        self.opacity_canvas_width = 150
        self.tray_icon: Any | None = None
        self.tray_visible = False
        self.last_message_text = ""
        self.last_message_is_error = False

        self.root = tk.Tk()
        self.root.title("")
        self.configure_window_chrome(schedule_retry=True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.opacity_percent / 100)
        self.root.resizable(False, False)
        self.root.geometry("+40+40")

        self.frame = tk.Frame(self.root, padx=10, pady=8)
        self.frame.pack(fill="both", expand=True)
        self.usage_frame = tk.Frame(self.frame)
        self.usage_frame.pack(fill="both", expand=True)
        self.controls_frame = tk.Frame(self.frame)
        self.controls_frame.pack(fill="x", pady=(8, 0))

        self.controls_frame.columnconfigure(2, weight=1)
        self.language_button = self.icon_button(self.controls_frame, self.cycle_language)
        self.language_button.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.theme_button = self.icon_button(self.controls_frame, self.cycle_theme)
        self.theme_button.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.opacity_canvas = tk.Canvas(
            self.controls_frame,
            width=self.opacity_canvas_width,
            height=24,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.opacity_canvas.grid(row=0, column=2, sticky="ew")
        self.opacity_canvas.bind("<Button-1>", self.opacity_from_event)
        self.opacity_canvas.bind("<B1-Motion>", self.opacity_from_event)
        self.opacity_value_label = tk.Label(self.controls_frame, width=4, anchor="e", font=("Segoe UI", 8))
        self.opacity_value_label.grid(row=0, column=3, sticky="e", padx=(6, 0))

        self.apply_theme()
        self.render_message(self.tr("loading"))

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.bind("<F5>", lambda _event: self.refresh_now())
        for widget in (self.root, self.frame, self.usage_frame, self.controls_frame):
            self.bind_drag(widget)
            self.bind_minimize_to_tray(widget)
        self.root.after(100, self.process_events)
        self.refresh_now()
        self.schedule_refresh()

    def run(self) -> None:
        self.root.mainloop()

    def configure_window_chrome(self, schedule_retry: bool = False) -> None:
        self.root.overrideredirect(True)
        if sys.platform == "darwin":
            try:
                self.root.update_idletasks()
                self.root.tk.call("::tk::unsupported::MacWindowStyle", "style", self.root._w, "plain", "none")
            except self.tk.TclError:
                pass
            if schedule_retry:
                self.root.after_idle(self.configure_window_chrome)

    def refresh_now(self) -> None:
        threading.Thread(target=self.fetch_snapshot, daemon=True).start()

    def fetch_snapshot(self) -> None:
        try:
            snapshot = self.client.read_rate_limits()
            self.events.put(("ok", snapshot_to_display_items(snapshot)))
        except Exception as exc:
            self.events.put(("error", readable_error(exc, self.effective_language())))

    def process_events(self) -> None:
        while not self.events.empty():
            kind, payload = self.events.get_nowait()
            if kind == "ok":
                self.render_usage(payload)
            elif not self.has_usage_view:
                self.render_message(payload, error=True)
        if not self.closed:
            self.root.after(100, self.process_events)

    def render_usage(self, items: list[UsageDisplayItem]) -> None:
        if not items:
            if not self.has_usage_view:
                self.render_message(self.tr("no_usage"))
            return
        self.current_items = items
        self.has_usage_view = True
        self.message_label = None
        self.last_message_text = ""
        self.last_message_is_error = False
        if len(self.cards) != len(items):
            self.rebuild_cards(len(items))
        for card, item in zip(self.cards, items):
            card["duration"].configure(text=self.format_duration_label(item.window_minutes))
            card["number"].configure(text=format_percent(item.remaining_percent))
            card["reset"].configure(text=self.format_reset_label(item.resets_at))
        self.sync_control_width_to_cards()
        self.apply_theme()
        self.update_tray_icon()

    def rebuild_cards(self, count: int) -> None:
        self.clear_usage_frame()
        self.cards = []
        for column in range(count):
            card = self.tk.Frame(self.usage_frame, padx=14, pady=10, highlightthickness=1)
            card.grid(row=0, column=column, padx=(0 if column == 0 else 8, 0), sticky="nsew")
            duration = self.tk.Label(card, font=("Segoe UI", 9))
            duration.pack()
            number = self.tk.Label(card, font=("Segoe UI", 30, "bold"))
            number.pack(pady=(1, 0))
            reset = self.tk.Label(card, font=("Segoe UI", 8))
            reset.pack()
            for widget in (card, duration, number, reset):
                self.bind_drag(widget)
                self.bind_minimize_to_tray(widget)
            self.cards.append({"card": card, "duration": duration, "number": number, "reset": reset})

    def sync_control_width_to_cards(self) -> None:
        if self.opacity_canvas is None or self.opacity_value_label is None or not self.cards:
            return
        self.root.update_idletasks()
        cards_width = self.usage_frame.winfo_reqwidth()
        fixed_width = (
            self.language_button.winfo_reqwidth()
            + 6
            + self.theme_button.winfo_reqwidth()
            + 8
            + self.opacity_value_label.winfo_reqwidth()
            + 6
        )
        self.opacity_canvas_width = max(80, cards_width - fixed_width)
        self.opacity_canvas.configure(width=self.opacity_canvas_width)
        self.controls_frame.configure(width=cards_width)
        self.draw_opacity_slider()

    def render_message(self, text: str, error: bool = False) -> None:
        self.current_items = []
        self.cards = []
        self.last_message_text = text
        self.last_message_is_error = error
        self.clear_usage_frame()
        self.message_label = self.tk.Label(
            self.usage_frame,
            text=text,
            justify="center",
            font=("Segoe UI", 10),
            padx=16,
            pady=12,
        )
        self.message_label.error_state = error
        self.message_label.pack()
        self.bind_drag(self.message_label)
        self.bind_minimize_to_tray(self.message_label)
        self.apply_theme()
        self.update_tray_icon()

    def clear_usage_frame(self) -> None:
        for child in self.usage_frame.winfo_children():
            child.destroy()

    def icon_button(self, parent: Any, command: Any) -> Any:
        button = self.tk.Label(
            parent,
            relief="flat",
            bd=0,
            width=3,
            height=1,
            padx=0,
            pady=2,
            font=("Segoe UI Symbol", 11),
            cursor="hand2",
        )
        button.is_active = False

        def set_active(active: bool) -> None:
            button.is_active = active
            colors = self.colors()
            button.configure(bg=colors["control_active"] if active else colors["control"])

        def press(_event: Any) -> str:
            set_active(True)
            return "break"

        def leave(_event: Any) -> str:
            set_active(False)
            return "break"

        def release(event: Any) -> str:
            active = bool(getattr(button, "is_active", False))
            set_active(False)
            if active and 0 <= event.x < button.winfo_width() and 0 <= event.y < button.winfo_height():
                command()
            return "break"

        button.bind("<ButtonPress-1>", press)
        button.bind("<ButtonRelease-1>", release)
        button.bind("<Leave>", leave)
        return button

    def cycle_language(self) -> None:
        self.language_mode = next_option(LANGUAGE_OPTIONS, self.language_mode)
        self.refresh_text()

    def cycle_theme(self) -> None:
        self.theme_mode = next_option(THEME_OPTIONS, self.theme_mode)
        self.apply_theme()
        self.rebuild_tray_menu()
        self.update_tray_icon()

    def opacity_from_event(self, event: Any) -> str:
        width = self.current_opacity_width()
        x = max(0, min(width, event.x))
        self.opacity_percent = round(x / width * 100)
        self.root.attributes("-alpha", max(0, min(100, self.opacity_percent)) / 100)
        self.draw_opacity_slider()
        return "break"

    def refresh_text(self) -> None:
        self.refresh_control_text()
        if self.current_items:
            self.render_usage(self.current_items)
        elif self.message_label is not None:
            error = bool(getattr(self.message_label, "error_state", False))
            # Recompute common first-run errors after a language switch.
            text = self.message_label.cget("text")
            if "Codex" in text and ("login" in text.lower() or "\u767b\u5165" in text):
                text = self.tr("login_error")
            self.render_message(text, error=error)
        self.rebuild_tray_menu()
        self.update_tray_icon()

    def refresh_control_text(self) -> None:
        self.language_button.configure(text=self.language_icon())
        self.theme_button.configure(text=self.theme_icon())
        self.draw_opacity_slider()

    def language_icon(self) -> str:
        if self.language_mode == "system":
            return "A*"
        if self.language_mode == "zh-TW":
            return "\u6587"
        return "A"

    def theme_icon(self) -> str:
        if self.theme_mode == "system":
            return "\u25d0"
        if self.theme_mode == "light":
            return "\u2600"
        return "\u263e"

    def effective_language(self) -> str:
        if self.language_mode != "system":
            return self.language_mode
        if windows_ui_language_is_traditional_chinese():
            return "zh-TW"
        lang = (locale.getlocale()[0] or locale.getdefaultlocale()[0] or "").lower()
        if lang.startswith("zh_tw") or lang.startswith("zh-hant") or lang.startswith("zh_hant"):
            return "zh-TW"
        return "en"

    def tr(self, key: str) -> str:
        return TRANSLATIONS[self.effective_language()][key]

    def effective_theme(self) -> str:
        if self.theme_mode != "system":
            return self.theme_mode
        return detect_system_theme()

    def colors(self) -> dict[str, str]:
        return THEMES[self.effective_theme()]

    def apply_theme(self) -> None:
        colors = self.colors()
        self.root.configure(bg=colors["panel"])
        for widget in (self.frame, self.usage_frame, self.controls_frame):
            widget.configure(bg=colors["panel"])
        for card in self.cards:
            card["card"].configure(bg=colors["card"], highlightbackground=colors["border"])
            card["duration"].configure(bg=colors["card"], fg=colors["muted"])
            card["number"].configure(bg=colors["card"], fg=colors["accent"])
            card["reset"].configure(bg=colors["card"], fg=colors["muted"])
        if self.message_label is not None:
            error = bool(getattr(self.message_label, "error_state", False))
            self.message_label.configure(bg=colors["panel"], fg=colors["error"] if error else colors["text"])
        for button in (self.language_button, self.theme_button):
            button.configure(
                bg=colors["control"],
                fg=colors["text"],
            )
        if self.opacity_canvas is not None:
            self.opacity_canvas.configure(bg=colors["panel"])
        if self.opacity_value_label is not None:
            self.opacity_value_label.configure(bg=colors["panel"], fg=colors["muted"])
        self.refresh_control_text()
        self.root.attributes("-alpha", max(0, min(100, self.opacity_percent)) / 100)

    def current_opacity_width(self) -> int:
        if self.opacity_canvas is None:
            return self.opacity_canvas_width
        return max(80, self.opacity_canvas.winfo_width() or self.opacity_canvas_width)

    def draw_opacity_slider(self) -> None:
        if self.opacity_canvas is None:
            return
        colors = self.colors()
        canvas = self.opacity_canvas
        canvas.delete("all")
        width = self.current_opacity_width()
        height = 24
        track_y = 12
        track_h = 6
        fill_w = round(width * self.opacity_percent / 100)
        canvas.create_rectangle(0, track_y - track_h // 2, width, track_y + track_h // 2, fill=colors["slider"], outline="")
        canvas.create_rectangle(0, track_y - track_h // 2, fill_w, track_y + track_h // 2, fill=colors["slider_fill"], outline="")
        knob_x = max(5, min(width - 5, fill_w))
        canvas.create_oval(knob_x - 5, track_y - 5, knob_x + 5, track_y + 5, fill=colors["text"], outline="")
        if self.opacity_value_label is not None:
            self.opacity_value_label.configure(text=f"{self.opacity_percent}%")

    def format_duration_label(self, window_minutes: int | None) -> str:
        if not window_minutes:
            return self.tr("unknown_limit")
        hours = window_minutes / 60
        if hours > 24:
            return self.tr("day_limit").format(value=window_minutes / 1440)
        return self.tr("hour_limit").format(value=hours)

    def format_reset_label(self, resets_at: str | None) -> str:
        if not resets_at:
            return self.tr("reset_unknown")
        try:
            reset_time = datetime.strptime(resets_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return self.tr("reset_at").format(time=resets_at)
        return self.tr("reset_at").format(time=reset_time.strftime("%m/%d %H:%M"))

    def bind_minimize_to_tray(self, widget: Any) -> None:
        widget.bind("<Double-Button-1>", self.minimize_to_tray)

    def minimize_to_tray(self, _event: Any | None = None) -> str:
        try:
            self.ensure_tray_icon()
            self.update_tray_icon()
            self.root.withdraw()
            self.tray_visible = True
        except Exception as exc:
            self.render_message(readable_error(exc, self.effective_language()), error=True)
        return "break"

    def ensure_tray_icon(self) -> None:
        if self.tray_icon is not None:
            return
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem(self.tr("tray_show"), self.tray_show, default=True),
            pystray.MenuItem(self.tr("tray_exit"), self.tray_exit),
        )
        self.tray_icon = pystray.Icon(
            "codex-usage",
            self.build_tray_image(),
            self.tray_tooltip_text(),
            menu,
        )
        self.tray_icon.run_detached()

    def tray_show(self, _icon: Any = None, _item: Any = None) -> None:
        self.root.after(0, self.restore_from_tray)

    def tray_exit(self, _icon: Any = None, _item: Any = None) -> None:
        self.root.after(0, self.close)

    def restore_from_tray(self) -> None:
        if self.closed:
            return
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.tray_visible = False

    def rebuild_tray_menu(self) -> None:
        if self.tray_icon is None:
            return
        import pystray

        self.tray_icon.menu = pystray.Menu(
            pystray.MenuItem(self.tr("tray_show"), self.tray_show, default=True),
            pystray.MenuItem(self.tr("tray_exit"), self.tray_exit),
        )

    def update_tray_icon(self) -> None:
        if self.tray_icon is None:
            return
        self.tray_icon.icon = self.build_tray_image()
        self.tray_icon.title = self.tray_tooltip_text()

    def build_tray_image(self) -> Any:
        from PIL import Image, ImageDraw, ImageFont

        colors = self.colors()
        size = 64
        image = Image.new("RGBA", (size, size), colors["card"])
        draw = ImageDraw.Draw(image)
        draw.rectangle((1, 1, size - 2, size - 2), outline=colors["accent"], width=3)
        text = self.tray_icon_text()
        font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (size - (bbox[2] - bbox[0])) / 2
        y = (size - (bbox[3] - bbox[1])) / 2 - 1
        draw.text((x, y), text, fill=colors["accent"], font=font)
        return image

    def tray_icon_text(self) -> str:
        percent = self.lowest_remaining_percent()
        if percent is None:
            return "!"
        return str(round(percent))

    def tray_tooltip_text(self) -> str:
        if self.current_items:
            return "\n".join(self.format_tray_item(item) for item in self.current_items)
        if self.last_message_text:
            return self.last_message_text
        return self.tr("tray_no_data")

    def format_tray_item(self, item: UsageDisplayItem) -> str:
        return " | ".join(
            [
                self.format_duration_label(item.window_minutes),
                format_percent(item.remaining_percent),
                self.format_reset_label(item.resets_at),
            ]
        )

    def lowest_remaining_percent(self) -> float | None:
        values = [item.remaining_percent for item in self.current_items if item.remaining_percent is not None]
        if not values:
            return None
        return min(values)

    def bind_drag(self, widget: Any) -> None:
        widget.bind("<ButtonPress-1>", self.start_drag)
        widget.bind("<B1-Motion>", self.drag)
        widget.bind("<ButtonPress-3>", self.begin_context_close)
        widget.bind("<ButtonRelease-3>", self.finish_context_close)

    def begin_context_close(self, _event: Any) -> str:
        return "break"

    def finish_context_close(self, _event: Any) -> str:
        self.root.after(50, self.close)
        return "break"

    def schedule_refresh(self) -> None:
        if self.closed:
            return
        self.root.after(self.refresh_seconds * 1000, self._scheduled_refresh)

    def _scheduled_refresh(self) -> None:
        if not self.closed:
            self.refresh_now()
            self.schedule_refresh()

    def start_drag(self, event: Any) -> None:
        self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag(self, event: Any) -> None:
        if self.drag_origin is None:
            return
        dx, dy = self.drag_origin
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        icon = self.tray_icon
        self.tray_icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        self.client.close()
        try:
            self.root.destroy()
        except Exception:
            pass

def next_option(options: list[str], current: str) -> str:
    try:
        index = options.index(current)
    except ValueError:
        return options[0]
    return options[(index + 1) % len(options)]



def windows_ui_language_is_traditional_chinese() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return False
    primary = lang_id & 0x3FF
    sublang = (lang_id >> 10) & 0x3F
    return primary == 0x04 and sublang in {0x01, 0x03, 0x04}

def detect_system_theme() -> str:
    if sys.platform != "win32":
        return "dark"
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if value else "dark"
    except OSError:
        return "dark"

def readable_error(exc: Exception, language: str = "en") -> str:
    message = str(exc)
    lower = message.lower()
    translations = TRANSLATIONS[language]
    if "unauthorized" in lower or "401" in lower or "refresh" in lower or "authentication required" in lower:
        return translations["login_error"]
    if "cannot find" in lower:
        return message
    return translations["read_error"].format(message=message)


def run_once(client: CodexAppServerClient) -> int:
    try:
        snapshot = client.read_rate_limits()
        print(snapshot_to_text(snapshot))
        return 0
    except Exception as exc:
        language = "zh-TW" if windows_ui_language_is_traditional_chinese() else "en"
        print(readable_error(exc, language), file=sys.stderr)
        return 1
    finally:
        client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Always-on-top Codex usage widget.")
    parser.add_argument("--once", action="store_true", help="Fetch usage once and print it.")
    parser.add_argument("--interval", type=int, default=DEFAULT_REFRESH_SECONDS, help="Refresh interval in seconds.")
    parser.add_argument("--codex", default="codex", help="Codex CLI command or absolute path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = CodexAppServerClient(args.codex)
    if args.once:
        return run_once(client)

    try:
        widget = UsageWidget(client, max(10, args.interval))
        widget.run()
        return 0
    except KeyboardInterrupt:
        client.close()
        return 130
    except Exception as exc:
        client.close()
        print(readable_error(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
