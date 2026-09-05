# -*- coding: utf-8 -*-
import os
import sys
import time
import shutil
import json
import streamlit as st

# 引用核心模組
from core.audio_processor import AudioProcessor
from core.groq_service import GroqTranscribeService

# 頁面基本配置 (寬版現代風)
st.set_page_config(
    page_title="快音逐字稿 — 巨型長語音/影片極速轉文字稿系統",
    page_icon="🎙️",
    layout="wide"
)

# 自訂現代感 CSS 樣式
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: -webkit-linear-gradient(45deg, #007AFF, #00C6FF);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0px;
    }
    .sub-title {
        color: #8E8E93;
        font-size: 1rem;
        margin-bottom: 20px;
    }
    .metric-card {
        background-color: #1C1C1E;
        border-radius: 10px;
        padding: 15px;
        border: 1px solid #2C2C2E;
        text-align: center;
    }
    .stTextArea textarea {
        font-size: 15px !important;
        line-height: 1.6 !important;
    }
</style>
""", unsafe_allow_html=True)

# 讀取系統環境變數的 GROQ_API_KEY 作為 fallback
default_key = os.environ.get("GROQ_API_KEY", "")

# 側邊欄：設定配置
with st.sidebar:
    st.header("⚙️ 轉錄服務配置")
    
    # 支援透過 URL 參數初始化 (由 localStorage 回填時使用)
    query_params = st.query_params
    initial_key = query_params.get("key", default_key)

    api_key_input = st.text_area(
        "Groq API Key (支援多組以逗號分隔)",
        value=initial_key,
        help="支援逗號、分號或換行分隔多組金鑰（如 gsk_1, gsk_2）。轉錄成功後會自動保存在瀏覽器 LocalStorage！",
        height=100
    )
    
    # 注入前端 JavaScript: 自動從瀏覽器 localStorage 讀取先前儲存的金鑰
    st.components.v1.html("""
    <script>
        (function() {
            const savedKey = localStorage.getItem("KUAIYIN_GROQ_KEYS");
            if (savedKey) {
                const urlParams = new URLSearchParams(window.parent.location.search);
                if (!urlParams.get("key")) {
                    urlParams.set("key", savedKey);
                    window.parent.location.search = urlParams.toString();
                }
            }
        })();
    </script>
    """, height=0)

    
    st.markdown("---")
    st.subheader("🛠️ 轉檔與切片參數")
    chunk_minutes = st.slider("音訊切片長度 (分鐘)", min_value=5, max_value=15, value=10, step=1,
                             help="針對超過 25MB 的長檔案自動切片。每段預設 10 分鐘，約 4.8MB。")
    
    parallel_workers = st.slider("最大並行線程數 (Parallel Workers)", min_value=1, max_value=8, value=5,
                                help="同時發送給 Groq 雲端運算的片段數量。多線程並行可大幅縮短轉寫時間！")
    
    st.markdown("---")
    st.markdown("💡 **支援格式**：`MP3`, `WAV`, `M4A`, `OGG`, `MP4`, `MKV`, `MOV` 等巨型長檔案（**支援 1GB+ 影片/音訊**）。")

# 主介面
st.markdown('<div class="main-title">🎙️ 快音逐字稿 (KuaiYin Transcriber)</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">專為長錄音、長會議、大影片設計的毫秒級「語音轉文字稿」極速引擎</div>', unsafe_allow_html=True)

# 檔案上傳區
uploaded_file = st.file_uploader(
    "📁 請將音訊或影片檔案拖曳至此處，或點擊瀏覽選取檔案（支援 1GB+ 檔案）",
    type=["mp3", "wav", "m4a", "ogg", "flac", "aac", "mp4", "mkv", "mov", "avi", "webm"],
    help="檔案會直接由本地底層 FFmpeg 進行高效串流抽音訊與壓縮，記憶體不爆掉。"
)

if uploaded_file:
    file_size_mb = uploaded_file.size / (1024 * 1024)
    file_size_str = f"{file_size_mb:.1f} MB" if file_size_mb < 1024 else f"{file_size_mb/1024:.2f} GB"
    
    col_info1, col_info2, col_info3 = st.columns(3)
    with col_info1:
        st.info(f"📄 **檔案名稱**: `{uploaded_file.name}`")
    with col_info2:
        st.info(f"⚖️ **檔案大小**: `{file_size_str}`")
    with col_info3:
        st.info(f"🎯 **處理模式**: FFmpeg 串流抽音 ＋ Groq Whisper")

    # 開始轉寫按鈕
    start_button = st.button("🚀 開始極速轉錄為文字稿", type="primary", use_container_width=True)

    if start_button:
        if not api_key_input.strip():
            st.error("❌ 請先在左側邊欄輸入至少一組有效的 Groq API Key！")
            st.stop()

        # 建立工作目錄
        work_dir = os.path.join(os.getcwd(), "workspace")
        os.makedirs(work_dir, exist_ok=True)
        saved_input_path = os.path.join(work_dir, uploaded_file.name)
        compressed_audio_path = os.path.join(work_dir, "compressed_mono.mp3")

        status_box = st.status("⏳ 正在全力處理中，請稍候...", expanded=True)
        
        try:
            # 步驟 1: 儲存檔案
            status_box.write("📥 [1/4] 正在接收檔案寫入本地緩衝區...")
            with open(saved_input_path, "wb") as f:
                shutil.copyfileobj(uploaded_file, f)

            # 步驟 2: FFmpeg 串流抽音與壓縮
            status_box.write("🎵 [2/4] 使用 FFmpeg 極速抽離音軌並壓縮為 16kHz 單聲道音訊...")
            processor = AudioProcessor(temp_dir=os.path.join(work_dir, "chunks"))
            t0 = time.time()
            processor.extract_and_compress_audio(saved_input_path, compressed_audio_path)
            compress_time = time.time() - t0
            
            comp_size_mb = os.path.getsize(compressed_audio_path) / (1024 * 1024)
            status_box.write(f"✓ 音訊抽離瘦身完成！(原檔 {file_size_str} ➡️ 瘦身後 {comp_size_mb:.1f} MB，耗時 {compress_time:.1f} 秒)")

            # 步驟 3: 智慧分段切片
            status_box.write(f"✂️ [3/4] 依據每 {chunk_minutes} 分鐘進行切片計算 (<25MB)...")
            chunks = processor.slice_audio(compressed_audio_path, chunk_duration_sec=chunk_minutes * 60)
            status_box.write(f"✓ 共切分為 {len(chunks)} 個小片段，準備同時發送至 Groq LPU 叢集...")

            # 步驟 4: 多執行緒並行呼叫 Groq Whisper
            progress_bar = st.progress(0, text="正在調度多線程向 Groq Whisper 發送切片...")
            groq_service = GroqTranscribeService(api_keys=api_key_input)

            def update_progress(done_count, total_count):
                pct = int((done_count / total_count) * 100)
                progress_bar.progress(pct, text=f"⚡ 正在並行推論轉錄中: 已完成 {done_count}/{total_count} 片段 ({pct}%)")

            t_start_trans = time.time()
            parallel_results = groq_service.transcribe_chunks_parallel(
                chunks, 
                max_workers=parallel_workers,
                progress_callback=update_progress
            )
            trans_time = time.time() - t_start_trans
            status_box.write(f"✓ 所有片段轉寫完畢！總耗時: {trans_time:.1f} 秒！")

            # 步驟 5: 拼裝全文與時間軸字幕
            status_box.write("🧩 [4/4] 正在按時間軸拼接完整逐字稿與 SRT 字幕...")
            full_text, full_srt = groq_service.assemble_results(parallel_results)

            status_box.update(label="🎉 恭喜！逐字稿全部轉錄完成！", state="complete", expanded=False)
            progress_bar.empty()

            # 轉錄成功！自動將此組有效金鑰儲存至使用者的瀏覽器 LocalStorage
            safe_key_json = json.dumps(api_key_input.strip())
            save_script = f"""
            <script>
                (function() {{
                    const keyVal = {safe_key_json};
                    localStorage.setItem("KUAIYIN_GROQ_KEYS", keyVal);
                    const url = new URL(window.parent.location.href);
                    url.searchParams.set("key", keyVal);
                    window.parent.history.replaceState(null, "", url.toString());
                }})();
            </script>
            """
            st.components.v1.html(save_script, height=0)

            # 統計卡片
            char_count = len(full_text.replace(" ", "").replace("\n", ""))
            total_duration_sec = processor.get_audio_duration_seconds(compressed_audio_path)
            m, s = divmod(total_duration_sec, 60)
            h, m = divmod(m, 60)
            time_str = f"{int(h)}時{int(m)}分{int(s)}秒" if h > 0 else f"{int(m)}分{int(s)}秒"

            st.success(f"✨ 成功完成轉錄！音訊總長度約 **{time_str}**，辨識出 **{char_count:,}** 個字，轉錄耗時僅 **{trans_time:.1f} 秒**！")

            # 展示與下載分頁
            tab_text, tab_srt = st.tabs(["📝 完整逐字稿文字", "⏱️ 帶時間軸字幕 (SRT)"])

            with tab_text:
                st.download_button(
                    label="💾 下載完整逐字稿 (.txt)",
                    data=full_text,
                    file_name=f"{os.path.splitext(uploaded_file.name)[0]}_逐字稿.txt",
                    mime="text/plain",
                    use_container_width=True
                )
                st.text_area("逐字稿內容預覽與編輯", value=full_text, height=450)

            with tab_srt:
                st.download_button(
                    label="💾 下載帶時間軸字幕 (.srt)",
                    data=full_srt,
                    file_name=f"{os.path.splitext(uploaded_file.name)[0]}.srt",
                    mime="text/plain",
                    use_container_width=True
                )
                st.text_area("SRT 字幕內容預覽", value=full_srt, height=450)

        except Exception as e:
            status_box.update(label="❌ 處理過程中發生錯誤", state="error")
            st.error(f"錯誤訊息: {str(e)}")
        finally:
            # 清理暫存檔案 (避免佔據硬碟)
            try:
                if os.path.exists(saved_input_path): os.remove(saved_input_path)
                if os.path.exists(compressed_audio_path): os.remove(compressed_audio_path)
            except Exception:
                pass
