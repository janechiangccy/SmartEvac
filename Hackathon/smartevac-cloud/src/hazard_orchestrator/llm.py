"""
Gemini 批次指令生成。

不對每個節點分別呼叫，而是組單一 prompt 列出所有節點處置，要求一次回 JSON 物件。
延遲從 N×800ms 壓到 1×1200ms。

沿用 Flow 2 的 503 retry 機制。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from google import genai
from google.genai import errors as genai_errors

logger = logging.getLogger()

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

_client = genai.Client(api_key=GOOGLE_API_KEY) if GOOGLE_API_KEY else None

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.+?)\n```\s*$", re.DOTALL)


def build_batch_prompt(
    routes: dict[str, dict],
    topology: dict[str, dict],
    triggering_node: str,
) -> str:
    lines = []
    for node_id, route in routes.items():
        label = topology[node_id]["label"]
        lines.append(
            f"- {node_id}（{label}）：方向 {route['direction']}，{route['hint']}"
        )
    block = "\n".join(lines)
    return (
        "你是校園火災／氣體外洩疏散指揮系統。下面列出當前各走廊節點的處置方案，"
        "請為每個節點輸出一句 25 字以內的繁體中文口語廣播指令，"
        "語氣冷靜清楚，要強調急迫但不要恐嚇。\n\n"
        f"污染源節點：{triggering_node}\n\n"
        "節點處置：\n"
        f"{block}\n\n"
        "回傳格式：JSON 物件，key 為節點 ID，value 為該節點的廣播指令字串。"
        "不要 markdown code fence、不要任何說明文字，直接輸出 JSON。"
    )


def _strip_fence(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


def generate_batch_instructions(
    routes: dict[str, dict],
    topology: dict[str, dict],
    triggering_node: str,
) -> dict[str, str]:
    """呼叫 Gemini 一次拿到所有節點指令。

    Returns:
        {node_id: instruction_text}

    Raises:
        RuntimeError: GOOGLE_API_KEY 未設定
        genai_errors.APIError: Gemini API 失敗（已 retry 一次）
        ValueError: 回應遺漏節點
        json.JSONDecodeError: 回應非有效 JSON
    """
    if _client is None:
        raise RuntimeError("GOOGLE_API_KEY 未設定")

    prompt = build_batch_prompt(routes, topology, triggering_node)

    # 503 重試一次（Gemini Flash 偶發塞車）
    for attempt in range(2):
        try:
            response = _client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            break
        except genai_errors.APIError as e:
            if attempt == 0 and getattr(e, "code", None) == 503:
                logger.warning("Gemini 503 塞車，2 秒後重試一次")
                time.sleep(2)
                continue
            raise

    text = _strip_fence(response.text or "")
    data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError(f"Gemini 回應非物件：{text[:200]}")
    for node_id in routes:
        if node_id not in data:
            raise ValueError(f"Gemini 回應遺漏節點 {node_id}：{text[:200]}")
        if not isinstance(data[node_id], str):
            raise ValueError(f"Gemini 節點 {node_id} 指令非字串：{data[node_id]!r}")

    logger.info(f"✅ Gemini 批次回應 {len(data)} 個節點")
    return data
