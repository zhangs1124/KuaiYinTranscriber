# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import shutil
from typing import List, Tuple

# 自動加載 static_ffmpeg 路徑，確保任何環境下皆有 ffmpeg
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception as e:
    pass

class AudioProcessor:
    """
    負責巨型音訊/影片檔案 (支援 1GB+) 的音軌抽離、瘦身壓縮與智慧切片 (<25MB)。
    """
    def __init__(self, temp_dir: str = "temp_chunks"):
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)

    def cleanup_temp(self):
        """清理切片暫存檔案"""
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass
            os.makedirs(self.temp_dir, exist_ok=True)

    def extract_and_compress_audio(self, input_file_path: str, output_mp3_path: str) -> bool:
        """
        利用 FFmpeg 串流將輸入檔案 (不論是 1GB 的 MP4 影片還是 WAV 音檔)
        極速抽離音軌，並壓縮成 16kHz 單聲道 64kbps MP3。
        這能將 1GB 的影片瞬間瘦身成約 20~30MB 的極小純語音檔，省記憶體且保證品質！
        """
        cmd = [
            "ffmpeg", "-y",
            "-i", input_file_path,
            "-vn",                      # 捨棄畫面 (不解碼影片串流，極省資源)
            "-acodec", "libmp3lame",    # 轉為 MP3
            "-ac", "1",                 # 單聲道 (Mono)
            "-ar", "16000",             # 16kHz 取樣率 (Whisper 最佳語音取樣率)
            "-b:a", "64k",              # 64kbps 碼率 (人聲清晰且檔案極小)
            output_mp3_path
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return os.path.exists(output_mp3_path) and os.path.getsize(output_mp3_path) > 0
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"FFmpeg 音訊壓縮失敗: {e.stderr}")

    def get_audio_duration_seconds(self, file_path: str) -> float:
        """取得音訊總秒數"""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return float(res.stdout.strip())
        except Exception:
            # 備用方案：透過 ffprobe 或預估
            return 0.0

    def slice_audio(self, input_audio_path: str, chunk_duration_sec: int = 600) -> List[Tuple[str, float, float]]:
        """
        將音訊檔案切成多個小片段 (預設每段 10 分鐘 = 600 秒，約 4.8MB，遠低於 Groq 25MB 限制)。
        每段保留 1 秒微小 overlap，避免正好切在說話中間導致斷字。
        回傳清單格式：[(切片檔案路徑, 起始秒數, 結束秒數), ...]
        """
        self.cleanup_temp()
        total_duration = self.get_audio_duration_seconds(input_audio_path)
        
        # 如果音訊本身小於 25MB 且小於 10 分鐘，直接使用，不切片
        file_size_mb = os.path.getsize(input_audio_path) / (1024 * 1024)
        if file_size_mb < 24.0 and (total_duration == 0 or total_duration <= chunk_duration_sec):
            return [(input_audio_path, 0.0, total_duration)]

        chunks = []
        start_time = 0.0
        overlap = 1.0 # 1 秒重疊
        index = 0

        while start_time < total_duration:
            duration = chunk_duration_sec
            if start_time + duration > total_duration:
                duration = total_duration - start_time

            chunk_filename = os.path.join(self.temp_dir, f"chunk_{index:03d}.mp3")
            
            # 使用 ffmpeg 毫秒級精確擷取切片
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-t", str(duration),
                "-i", input_audio_path,
                "-acodec", "copy",       # 直接複製串流，切片瞬間完成 (零重編碼時間)
                chunk_filename
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            
            if os.path.exists(chunk_filename) and os.path.getsize(chunk_filename) > 0:
                chunks.append((chunk_filename, start_time, start_time + duration))

            index += 1
            # 下一個切片起始點推進 (減去 overlap)
            start_time += (duration - overlap)
            if duration <= overlap:
                break

        return chunks
