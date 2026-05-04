# NameCutter

NameCutter 是一個 Windows 桌面小工具，用來批量處理過長檔名。它會遞迴掃描來源資料夾，保留原本的子資料夾結構，並依照「輸出後完整絕對路徑」是否超過限制來決定是否截短檔名。

目前版本重點：

- 預設最大路徑長度為 `66`，可在 GUI 內調整
- 只縮短檔名，不縮短資料夾名稱
- 保留完整副檔名，例如 `.tar.gz`
- 預覽後才執行，避免直接改壞大量檔案
- 支援輸出到另一個資料夾，或原地更名
- 提供 PyInstaller 打包腳本，產出 `NameCutter.exe`

## 本機執行

```powershell
$env:PYTHONPATH="src"
python main.py
```

## 測試

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

## 打包 exe

```powershell
.\build.ps1
```

產出檔會在 `dist\NameCutter.exe`。

## 規則摘要

- 判斷基準是「輸出後完整絕對路徑字元數」
- 若路徑長度 `<=` 限制，不改檔名
- 若路徑長度超限，只從檔名尾端開始截短，優先保留前綴
- 若截短後重名，會自動加入 `_1`、`_2`
- 若即使縮到極短仍無法符合限制，該檔案會被跳過並在結果內標示

