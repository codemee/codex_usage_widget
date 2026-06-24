# Codex Usage Widget

Traditional Chinese: [README.zh-TW.md](README.zh-TW.md)

Codex Usage Widget is a small always-on-top desktop panel for monitoring Codex rate-limit usage. It reads usage data from the local Codex app-server with `account/rateLimits/read`, shows the remaining percentage for each limit window, and can minimize to the system tray.

## Features

- Always-on-top frameless floating usage panel
- Remaining usage shown as large percentage cards
- Traditional Chinese and English UI, with system-language detection
- Pink light theme and purple dark theme, with system-theme detection and readable controls
- Adjustable panel opacity, defaulting to 70%
- System tray mode with percentage icon and usage tooltip
- Manual refresh with `F5`

## Requirements

- Codex CLI available on `PATH`
- An active Codex/ChatGPT login in the local Codex app
- `uv`
- Python 3.13 managed through `uv`

This project uses `pystray` and `Pillow` for cross-platform tray support.

## Setup

Install Python 3.13 through `uv` if needed:

```powershell
uv python install 3.13
```

Install dependencies:

```powershell
uv sync
```

If `uv` has cache permission issues on Windows, set a writable cache directory before running commands:

```powershell
$env:UV_CACHE_DIR='C:\Users\test_codex\Documents\codex-usage\.uv-cache'
```

## Usage

Start the widget:

```powershell
uv run --python 3.13 python codex_usage_widget.py
```

Fetch usage once in the terminal:

```powershell
uv run --python 3.13 python codex_usage_widget.py --once
```

Optional arguments:

```powershell
uv run --python 3.13 python codex_usage_widget.py --interval 60 --codex codex
```

## Controls

- Drag the panel with the left mouse button.
- Press `F5` to refresh usage.
- Press `Esc` to exit.
- Right-click the panel to exit.
- Double-click the panel or a usage card to minimize to the system tray.
- Double-click the tray icon, or use the tray menu `Show`, to restore the panel.
- Use the language icon to cycle system, Traditional Chinese, and English.
- Use the theme icon to cycle system, light, and dark themes.
- Drag the opacity slider to change transparency.

## Troubleshooting

If the widget says Codex login needs attention, open Codex and refresh or restore the ChatGPT login session, then press `F5`.

If the tray icon does not restore the panel on double-click on a specific desktop environment, use the tray icon menu and choose `Show`.
