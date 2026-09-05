@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 快音逐字稿 - KuaiYin Transcriber Web

echo ========================================================
echo   快音長語音/影片逐字稿轉錄系統 (KuaiYin Transcriber)
echo ========================================================
echo.
echo 正在檢查與啟動 Web 服務 (支援 4GB 超大檔案上傳)...
python -m streamlit run app.py --server.maxUploadSize 4096
if errorlevel 1 (
    echo.
    echo [錯誤] 啟動失敗，請確認已安裝 Python 與必要相依套件：
    echo pip install -r requirements.txt
    pause
)
