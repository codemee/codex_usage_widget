# 專案規範

## 專案結構

- `codex_usage_widget.py`：主要應用程式，包含 Codex app-server 用量讀取、Tkinter 面板、主題/語系/透明度控制與系統匣功能。
- `README.md`：給使用者看的安裝、啟動與操作說明。
- `PRD.md`：目前已實作功能需求與驗收方式。
- `pyproject.toml` / `uv.lock`：Python 版本與依賴鎖定。

## 使用 uv 管理 Python 環境

專案中需要使用 Python 時：

- 一律使用 uv 建置 Python 環境，不要使用其他工具
- 一律將 Python 安裝到 uv 的全域環境中，不要裝到專案內
- 若未指明，請使用 Python 3.13
- 必要時使用 `uv init` 初始化專案
- 使用 `uv add/remove` 管理套件
- 使用 `uv run` 執行 Python 腳本檔

## 常用指令

```powershell
uv sync
uv run --python 3.13 python codex_usage_widget.py
uv run --python 3.13 python codex_usage_widget.py --once
uv run --python 3.13 python -m py_compile codex_usage_widget.py
```

## 依賴注意事項

系統匣功能依賴 `pystray` 與 `Pillow`。新增或移除套件時，一律使用 `uv add` 或 `uv remove`，並保留 `uv.lock` 更新。
