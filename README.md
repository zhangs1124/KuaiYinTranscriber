# KuaiYin Transcriber (快音逐字稿系統)

專為超長錄音與巨型影音檔案 (支援 1GB+) 設計的高速逐字稿與 SRT 字幕轉錄系統。基於 Python、Streamlit、FFmpeg 串流抽取與 Groq Whisper 平行切片轉錄。

## 🌟 核心特色
- **突破大小限制**：採用 FFmpeg 串流直接抽離音訊並轉換為輕量單聲道 MP3，處理 1GB+ 影片不爆記憶體。
- **智慧重疊切片**：自動以 10 分鐘 (<25MB) 為單位分段，具備 1 秒前後重疊 (Overlap)，完全符合 Groq 限制且不截斷字詞。
- **多 API Key 輪替與平行轉錄**：支援填入多把 Groq Key，透過多執行緒平行發送請求，數十分鐘影音在 1~2 分鐘內辨識完成。
- **精準時間軸字幕輸出**：自動校準切片時間戳記偏移，輸出標準 SRT 字幕與純文字全文。
- **現代化 Web UI**：開箱即用，支援拖放上傳與一鍵下載。

## 🚀 快速開始

### 1. 安裝環境與相依套件
```bash
pip install -r requirements.txt
```

### 2. 啟動系統
- **Windows 一鍵啟動**：雙擊 `run.bat`。
- **命令列啟動**：
```bash
python -m streamlit run app.py
```
啟動後瀏覽器打開 `http://localhost:8501` 即可使用。
