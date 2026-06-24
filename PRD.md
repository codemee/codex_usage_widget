# 跨平台系統匣功能

## 目前狀態

已實作於 `codex_usage_widget.py`，使用 `pystray` 與 `Pillow` 提供系統匣功能。

## 已完成需求

1. 在面板或用量卡片上雙按可縮小到系統匣。
2. 系統匣圖示會以最低剩餘用量百分比顯示；尚無成功資料時顯示驚嘆號。
3. 滑鼠移到系統匣圖示時，會顯示用量摘要 tooltip。
4. 在系統匣圖示上執行預設動作可回到正常面板顯示方式。
5. 系統匣右鍵選單提供 `Show` / `Exit` 作為跨平台 fallback。

## 驗收方式

```powershell
uv run --python 3.13 python -m py_compile codex_usage_widget.py
uv run --python 3.13 python codex_usage_widget.py
```

手動確認雙按面板會隱藏視窗並出現系統匣圖示，hover tooltip 顯示用量資訊，雙按圖示或點選 `Show` 可恢復面板。
