# Codex 用量小工具

Codex 用量小工具是一個永遠置頂的桌面浮動面板，用來監看 Codex 剩餘用量。它透過本機 Codex app-server 的 `account/rateLimits/read` 取得用量資訊，顯示每個限制視窗的剩餘百分比，並支援縮小到系統匣。

## 功能

- 永遠置頂、無標題列的浮動用量面板
- 以大型百分比卡片顯示剩餘用量
- 支援繁體中文與英文介面，並可跟隨系統語言
- 提供粉色淺色主題與紫色深色主題，並可跟隨系統主題且保持控制按鈕可讀
- 可調整整體透明度，預設為 70%
- 支援系統匣模式，圖示會顯示剩餘百分比
- 系統匣 tooltip 與選單會顯示用量摘要
- 可用 `F5` 手動重新整理

## 需求

- `codex` CLI 可在 `PATH` 中執行
- 本機 Codex app 已登入可用的 Codex/ChatGPT 帳號
- `uv`
- 透過 `uv` 管理的 Python 3.13

本專案使用 `pystray` 與 `Pillow` 提供跨平台系統匣功能。

## 安裝

如有需要，先透過 `uv` 安裝 Python 3.13：

```powershell
uv python install 3.13
```

安裝專案依賴：

```powershell
uv sync
```

如果在 Windows 上遇到 `uv` 快取權限問題，可以先指定可寫入的快取目錄：

```powershell
$env:UV_CACHE_DIR='C:\Users\test_codex\Documents\codex-usage\.uv-cache'
```

## 使用方式

啟動小工具：

```powershell
uv run --python 3.13 python codex_usage_widget.py
```

只在終端機讀取一次用量：

```powershell
uv run --python 3.13 python codex_usage_widget.py --once
```

可選參數範例：

```powershell
uv run --python 3.13 python codex_usage_widget.py --interval 60 --codex codex
```

## 操作

- 用滑鼠左鍵拖曳面板可移動位置。
- 按 `F5` 可重新整理用量。
- 按 `Esc` 可結束程式。
- 在面板上按滑鼠右鍵可結束程式。
- 雙按面板或用量卡片可縮小到系統匣。
- 雙按系統匣圖示，或從系統匣選單點選 `Show`，可恢復面板。
- 如果桌面環境的 tooltip 延遲或未顯示，可開啟系統匣選單查看最新用量摘要。
- 點選語言圖示可在跟隨系統、繁體中文、英文之間切換。
- 點選主題圖示可在跟隨系統、淺色、深色之間切換。
- 拖曳透明度滑桿可調整面板透明度。

## 疑難排解

如果小工具顯示 Codex 登入需要處理，請開啟 Codex 並重新整理或恢復 ChatGPT 登入狀態，然後按 `F5` 重新整理。

如果在特定桌面環境中雙按系統匣圖示無法恢復面板，請改用系統匣右鍵選單中的 `Show`。

如果 macOS 或其他桌面環境的系統匣 tooltip 顯示不穩定，請開啟系統匣選單讀取同一份用量摘要。
