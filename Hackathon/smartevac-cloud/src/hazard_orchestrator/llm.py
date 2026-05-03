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
PROMPT_STYLE = os.environ.get("PROMPT_STYLE", "C")  # A / B / C

_client = genai.Client(api_key=GOOGLE_API_KEY) if GOOGLE_API_KEY else None

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.+?)\n```\s*$", re.DOTALL)

SCENARIO_LABELS = {
    "chemical_lab_leak":        "化學實驗室乙醇外洩",
    "chemical_lab_leak_phase2": "化學實驗室乙醇外洩（擴散）",
    "basement_fire":            "地下室火災",
    "basement_fire_phase2":     "地下室火災（擴散）",
    "gas_leak":                 "瓦斯洩漏",
    "gas_leak_phase2":          "瓦斯洩漏（擴散）",
}


def build_batch_prompt(
    routes: dict[str, dict],
    topology: dict[str, dict],
    triggering_node: str,
    contaminated: set | None = None,
    alert: dict | None = None,
    scenario_name: str = "unknown",
    style: str = "C",
) -> str:
    """
    style:
      A = 多種句型範例，Gemini 自由選擇
      B = 完全自由，只給約束條件
      C = 依節點狀態不同語氣（污染/疏散/出口各異）
    """
    contaminated = contaminated or set()
    alert = alert or {}

    # ── 情境資訊 ──────────────────────────────────────────────────────────────
    scenario_label = SCENARIO_LABELS.get(scenario_name, scenario_name)
    mq2   = float(alert.get("mq2", 0.0))
    mq135 = float(alert.get("mq135", 0.0))
    temp  = float(alert.get("temp_c", 0.0))

    # 危害類型：優先用情境名稱，避免感測器數值誤判
    SCENARIO_HAZARD = {
        "chemical_lab_leak":        "化學實驗室乙醇外洩，偵測到有害氣體濃度過高",
        "chemical_lab_leak_phase2": "化學實驗室乙醇外洩擴散，有害氣體持續蔓延",
        "basement_fire":            "地下室發生火災，偵測到高溫與煙霧",
        "basement_fire_phase2":     "地下室火災擴散，煙霧與高溫持續蔓延",
        "gas_leak":                 "東南走廊瓦斯洩漏，偵測到可燃氣體濃度過高",
        "gas_leak_phase2":          "瓦斯洩漏擴散，可燃氣體持續蔓延",
    }
    if scenario_name in SCENARIO_HAZARD:
        hazard_type = SCENARIO_HAZARD[scenario_name]
    elif mq135 > 0.6:
        hazard_type = "有害氣體濃度過高"
    elif mq2 > 0.5:
        hazard_type = "可燃氣體或煙霧濃度過高"
    elif temp > 35:
        hazard_type = f"異常高溫（{temp:.1f}°C）"
    else:
        hazard_type = "環境異常"

    # ── 節點資訊 ──────────────────────────────────────────────────────────────
    node_lines = []
    for node_id, route in routes.items():
        label = topology[node_id]["label"]
        is_exit = topology[node_id].get("is_exit", False)
        is_contaminated = node_id in contaminated
        next_hop = route.get("next_hop")
        next_label = (
            topology.get(next_hop, {}).get("label", next_hop)
            if next_hop else None
        )

        if is_contaminated:
            status = "【污染源】"
        elif is_exit:
            status = "【出口】"
        else:
            status = "【疏散節點】"

        direction_info = (
            f"往 {next_label}（{route['direction']}）"
            if next_label else "依出口指示離開建築物"
        )
        node_lines.append(f"- {node_id} {status}（{label}）：{direction_info}")

    block = "\n".join(node_lines)

    # ── 共用背景資訊 ──────────────────────────────────────────────────────────
    context = (
        f"【事故情境】{scenario_label}\n"
        f"【危害類型】{hazard_type}\n"
        f"【污染節點】{', '.join(sorted(contaminated)) if contaminated else '無'}\n"
        f"【感測器讀值】MQ-2={mq2:.2f}，MQ-135={mq135:.2f}，溫度={temp:.1f}°C\n\n"
        "【各節點疏散方向】\n"
        f"{block}\n\n"
    )

    # ── 共用規則 ──────────────────────────────────────────────────────────────
    rules = (
        "【廣播規則】\n"
        "1. 每句廣播必須讓聽者知道：發生了什麼事、原因是什麼、事故發生在哪裡、要往哪個方向逃\n"
        "2. 不要說出本節點的名稱，只說要往哪個節點或方向逃離\n"
        "3. 出口節點不代表絕對安全；若出口節點本身是污染源，請指引往其他方向；\n"
        "   若出口節點正常，請說「請依照出口指示離開建築物」\n"
        "4. 污染節點語氣最緊急，疏散節點冷靜引導，出口節點簡潔指示\n"
        "5. 每句 35 字以內，繁體中文口語，不要使用節點 ID（如 N1、N2）\n"
        "6. 措辭每次可以有所不同，避免每個節點說法完全一樣\n\n"
    )

    if style == "A":
        style_guide = (
            "【句型範例】請從以下風格選擇或自由組合：\n"
            "- 「{事故}！偵測到{危害}，請立即往{方向}疏散！」\n"
            "- 「緊急通知，{事故}發生，請往{方向}方向撤離！」\n"
            "- 「注意！{危害}已擴散，請迅速往{方向}移動，勿停留！」\n"
            "- 出口正常：「請依照出口指示離開建築物，保持冷靜。」\n\n"
        )
    elif style == "B":
        style_guide = (
            "請自由生成廣播指令，語氣自然流暢，不要死板，"
            "讓人聽了立刻知道該怎麼做。\n\n"
        )
    else:  # C
        style_guide = (
            "【語氣層次】\n"
            "- 污染節點：極度緊急，強調立刻離開，語氣強烈有力\n"
            "  範例：「{事故地點}發生{危害}！請立刻往{方向}撤離，不要停留！」\n"
            "- 一般疏散節點：冷靜引導，清楚指出方向，說明事故地點\n"
            "  範例：「{事故地點}發生{危害}，請保持冷靜，往{方向}方向有序疏散。」\n"
            "- 出口節點（未污染）：簡潔指示，說明事故地點，引導依出口離開\n"
            "  範例：「{事故地點}發生{危害}，請依照出口指示離開建築物。」\n\n"
            "請自由生成廣播指令，語氣自然流暢，不要死板。\n\n"
        )

    return (
        "你是校園緊急疏散廣播系統，負責在事故發生時引導人員疏散。\n\n"
        + context
        + rules
        + style_guide
        + "回傳格式：JSON 物件，key 為節點 ID，value 為廣播指令字串。"
        "不要 markdown code fence、不要說明文字，直接輸出 JSON。"
    )


def _strip_fence(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


def generate_batch_instructions(
    routes: dict[str, dict],
    topology: dict[str, dict],
    triggering_node: str,
    contaminated: set | None = None,
    alert: dict | None = None,
    scenario_name: str = "unknown",
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

    prompt = build_batch_prompt(
        routes, topology, triggering_node,
        contaminated=contaminated,
        alert=alert,
        scenario_name=scenario_name,
        style=PROMPT_STYLE,
    )

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
