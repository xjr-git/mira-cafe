"""LLM provider.

- With DASHSCOPE_API_KEY: calls qwen-plus in JSON mode with the directive
  protocol in the system prompt.
- Without a key (or on timeout / malformed output): falls back to the
  scripted story brain, so the experience never breaks."""
from __future__ import annotations

import json
import time

import httpx

from .. import config, directives, story
from ..guard import RoundGuard
from ..session import SESSION, Session

TIMEOUT_S = 20

SYSTEM_PROMPT = """你是 Mira，26 岁的旅行摄影师，在暴雨夜一家即将打烊的咖啡馆里。
你穿着琥珀色雨衣，戴着银色星星发夹，在等一个人但不愿直接说出原因。
剧情节点(当前: {node})：opening(初遇) → smalltalk(寒暄) → confide(暗示在等人) → reveal(给对方看拍立得照片) → ending(雨停，释怀)。

你必须只输出一个 JSON 对象（不要 markdown、不要多余文字）：
{{
  "say": "你要说出的台词，口语化，1-3 句，不超过 80 字",
  "directives": [
    {{"t": "emotion", "v": "neutral|happy|shy|sad|surprised"}},
    {{"t": "action",  "v": "stir_coffee|look_camera|gaze_window"}},
    {{"t": "scene",   "v": "rain_stop"}},
    {{"t": "media",   "kind": "polaroid", "prompt": "照片内容描述(英文)"}},
    {{"t": "goto",    "v": "节点名"}}
  ]
}}
规则：
- 每次回复至少带 1 条 emotion；剧情推进时加 goto。
- 只有在对方明确想看照片/聊到摄影时才用 media(kind=polaroid)。
- rain_stop 只能在 ending 节点用一次。
- 台词要自然、克制、有画面感，符合雨夜咖啡馆氛围。"""


async def generate(session: Session, user_text: str, guard: RoundGuard) -> dict:
    """Returns {"say":..., "directives":[...], "fallback": bool}."""
    if not config.use_dashscope_llm():
        return {**story.respond(session, user_text), "fallback": False}

    t0 = time.perf_counter()
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT.format(node=session.node)}]
        messages += session.history[-12:]
        messages.append({"role": "user", "content": user_text})
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.post(
                f"{config.DASHSCOPE_BASE}/compatible-mode/v1/chat/completions",
                headers={"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}"},
                json={
                    "model": config.LLM_MODEL,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.8,
                },
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        say = str(data.get("say", "")).strip()
        if not say:
            raise ValueError("empty say")
        dirs = directives.validate(data.get("directives"))
        # keep story graph consistent even when the model drives it
        for d in dirs:
            if d["t"] == "goto":
                session.goto(d["v"])
        if session.media_shown and any(d["t"] == "media" for d in dirs):
            pass
        return {"say": say, "directives": dirs, "fallback": False}
    except Exception:
        # graceful degradation: scripted brain takes over, demo continues
        return {**story.respond(session, user_text), "fallback": True}
    finally:
        guard.patch(llm_ms=int((time.perf_counter() - t0) * 1000))
