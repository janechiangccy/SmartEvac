"""
Google Cloud Text-to-Speech — REST API + ThreadPoolExecutor 並行合成。

走 REST 而非 SDK，避免 Lambda 包過大。沿用 Flow 2 已驗證實作。
"""

from __future__ import annotations

import base64
import concurrent.futures
import json
import logging
import os
import urllib.request

logger = logging.getLogger()

GOOGLE_TTS_API_KEY = os.environ.get("GOOGLE_TTS_API_KEY", "")
GOOGLE_TTS_VOICE = os.environ.get("GOOGLE_TTS_VOICE", "cmn-TW-Wavenet-A")


def synthesize_speech(text: str) -> bytes:
    """單次 TTS 合成。回傳 mp3 bytes。"""
    payload = json.dumps(
        {
            "input": {"text": text},
            "voice": {"languageCode": "cmn-TW", "name": GOOGLE_TTS_VOICE},
            "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 22050},
        }
    ).encode("utf-8")

    url = (
        "https://texttospeech.googleapis.com/v1/text:synthesize"
        f"?key={GOOGLE_TTS_API_KEY}"
    )
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read())
    return base64.b64decode(result["audioContent"])


def parallel_synthesize(texts: dict[str, str]) -> dict[str, bytes]:
    """並行合成多節點語音。

    Args:
        texts: {node_id: text}
    Returns:
        {node_id: mp3_bytes}
    Raises:
        失敗時整個 batch raise 第一個 Exception（讓 Lambda 失敗重試）。
    """
    if not texts:
        return {}

    results: dict[str, bytes] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(texts)) as pool:
        future_map = {
            pool.submit(synthesize_speech, t): nid for nid, t in texts.items()
        }
        for future in concurrent.futures.as_completed(future_map):
            node_id = future_map[future]
            results[node_id] = future.result()

    logger.info(f"✅ 並行 TTS 完成 {len(results)} 份")
    return results
