# -*- coding: utf-8 -*-
import os
import time
import requests
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

class GroqKeyPool:
    """
    多 API Key 輪替與故障轉移池 (Failover Pool)。
    支援以逗號、分號或換行分隔多組金鑰。遇到 429 或 401 自動換 Key。
    """
    def __init__(self, raw_keys: str):
        self.keys = []
        self.current_index = 0
        self.set_keys(raw_keys)

    def set_keys(self, raw_keys: str):
        self.keys = []
        if raw_keys:
            # 分隔符號：逗號、分號、換行
            delimiters = [',', ';', '\n', '\r']
            tokens = [raw_keys]
            for d in delimiters:
                new_tokens = []
                for t in tokens:
                    new_tokens.extend(t.split(d))
                tokens = new_tokens
            
            for t in tokens:
                cleaned = t.strip()
                if cleaned and cleaned not in self.keys:
                    self.keys.append(cleaned)
        self.current_index = 0

    def get_current_key(self) -> Optional[str]:
        if not self.keys:
            return None
        return self.keys[self.current_index % len(self.keys)]

    def switch_next_key(self) -> str:
        if len(self.keys) <= 1:
            return self.get_current_key()
        prev = self.current_index
        self.current_index = (self.current_index + 1) % len(self.keys)
        print(f"[GroqKeyPool] 觸發故障轉移，切換金鑰: #{prev+1} -> #{self.current_index+1}")
        return self.get_current_key()

class GroqTranscribeService:
    """
    Groq Whisper 語音轉錄服務，支援切片並行加速與帶時間軸 SRT / 逐字稿組裝。
    """
    def __init__(self, api_keys: str, base_url: str = "https://api.groq.com/openai/v1"):
        self.key_pool = GroqKeyPool(api_keys)
        self.base_url = base_url.rstrip('/')

    def transcribe_single_chunk(self, chunk_file_path: str, prompt: str = "以下是繁體中文的演講或會議對話。") -> Dict[str, Any]:
        """
        將單一切片上傳至 Groq Whisper API 進行轉寫。
        包含 429 / 401 故障轉移自動重試機制。
        """
        url = f"{self.base_url}/audio/transcriptions"
        total_keys = len(self.key_pool.keys)
        attempts = 0

        while attempts < max(1, total_keys):
            attempts += 1
            api_key = self.key_pool.get_current_key()
            if not api_key:
                raise ValueError("未設定有效的 Groq API Key！")

            headers = {
                "Authorization": f"Bearer {api_key}"
            }

            try:
                with open(chunk_file_path, "rb") as f:
                    files = {
                        "file": (os.path.basename(chunk_file_path), f, "audio/mpeg")
                    }
                    data = {
                        "model": "whisper-large-v3",
                        "response_format": "verbose_json", # 取回帶時間戳的段落資訊
                        "language": "zh",
                        "prompt": prompt
                    }
                    resp = requests.post(url, headers=headers, files=files, data=data, timeout=60)

                if resp.status_code in [429, 401]:
                    print(f"[GroqTranscribe] 遇到 HTTP {resp.status_code}，嘗試換 Key 重試...")
                    self.key_pool.switch_next_key()
                    time.sleep(0.5)
                    continue

                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempts >= total_keys:
                    raise e
                self.key_pool.switch_next_key()
                time.sleep(0.5)

        raise RuntimeError("所有 API Key 均轉錄失敗。")

    def transcribe_chunks_parallel(self, chunks: List[tuple], max_workers: int = 5, progress_callback=None) -> List[Dict[str, Any]]:
        """
        使用線程池並行發送多個切片至 Groq Whisper LPU 叢集！
        1 小時音訊 (6 個切片) 同時並行處理，數秒完成！
        """
        results = [None] * len(chunks)
        completed_count = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 建立工作字典：future -> (index, chunk_path, start_sec, end_sec)
            future_to_chunk = {
                executor.submit(self.transcribe_single_chunk, chunk[0]): (i, chunk)
                for i, chunk in enumerate(chunks)
            }

            for future in as_completed(future_to_chunk):
                idx, chunk_info = future_to_chunk[future]
                chunk_path, start_sec, end_sec = chunk_info
                try:
                    data = future.result()
                    results[idx] = {
                        "index": idx,
                        "start_offset": start_sec,
                        "data": data
                    }
                except Exception as ex:
                    print(f"切片 {idx} 轉錄錯誤: {ex}")
                    results[idx] = {
                        "index": idx,
                        "start_offset": start_sec,
                        "data": {"text": f"[轉寫異常: {str(ex)}]", "segments": []}
                    }

                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, len(chunks))

        return results

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """格式化為 SRT 格式時間戳: HH:MM:SS,mmm"""
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        millis = int((s - int(s)) * 1000)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{millis:03d}"

    def assemble_results(self, parallel_results: List[Dict[str, Any]]) -> Tuple[str, str]:
        """
        將所有切片結果依據時間軸組裝：
        回傳: (完整逐字稿文字, 帶時間軸的 SRT 字幕文字)
        """
        full_text_list = []
        srt_entries = []
        srt_index = 1

        # 按照切片原本順序處理
        for item in parallel_results:
            if not item or "data" not in item:
                continue
            data = item["data"]
            offset = item.get("start_offset", 0.0)

            # 純文字累積
            text = data.get("text", "").strip()
            if text:
                full_text_list.append(text)

            # 字幕段落時間軸重組
            segments = data.get("segments", [])
            for seg in segments:
                seg_start = offset + seg.get("start", 0.0)
                seg_end = offset + seg.get("end", 0.0)
                seg_text = seg.get("text", "").strip()
                if not seg_text:
                    continue

                start_str = self.format_timestamp(seg_start)
                end_str = self.format_timestamp(seg_end)
                srt_entries.append(f"{srt_index}\n{start_str} --> {end_str}\n{seg_text}\n")
                srt_index += 1

        full_transcript = "\n\n".join(full_text_list)
        full_srt = "\n".join(srt_entries)
        return full_transcript, full_srt
