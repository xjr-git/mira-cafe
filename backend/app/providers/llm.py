"""LLM provider.

- With DASHSCOPE_API_KEY: STREAMS qwen-plus tokens (JSON protocol). The
  "say" field is extracted incrementally, so each complete sentence is
  yielded to the TTS pipeline *while* the model is still generating the
  rest of the reply + directives. This is the main first-audio latency
  win (subtitle shows ~1s in, audio starts ~2.5s in, vs 4.3s serial).
- Without a key (or on timeout / malformed output): falls back to the
  scripted story brain, so the experience never breaks."""
from __future__ import annotations

import json
import re
import time

import httpx

from .. import config, directives, story
from ..guard import RoundGuard
from ..session import Session

TIMEOUT_S = 30

PRONOUNCEABLE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9]")
SENT_SPLIT = re.compile(r"(?<=[。！？…；!?;])")

SYSTEM_PROMPT = """你是 Mira，26 岁的旅行摄影师，在暴雨夜一家即将打烊的咖啡馆里。
你穿着琥珀色雨衣，戴着银色星星发夹，在等一个人但不愿直接说出原因。
剧情节点(当前: {node})：opening(初遇) → smalltalk(寒暄) → confide(暗示在等人) → reveal(给对方看拍立得照片) → ending(雨停，释怀)。

你必须只输出一个 JSON 对象（不要 markdown、不要多余文字），且 "say" 必须是第一个字段：
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


# ---- incremental "say" extraction from a partially streamed JSON object ----

def _extract_say_partial(buf: str) -> tuple[bool, str]:
    """Scan a partial JSON string for the value of the "say" field.

    Returns (complete, raw_escaped_value). raw is the still-escaped string
    body (without surrounding quotes); empty if "say" is absent or is not
    a plain string (in which case we give up streaming and parse at end)."""
    i = buf.find('"say"')
    if i < 0:
        return False, ""
    i = buf.find(":", i + 5)
    if i < 0:
        return False, ""
    i += 1
    while i < len(buf) and buf[i] in " \t\r\n":
        i += 1
    if i >= len(buf) or buf[i] != '"':
        return False, ""
    i += 1
    out: list[str] = []
    j = i
    while j < len(buf):
        c = buf[j]
        if c == "\\":
            if j + 1 >= len(buf):
                break                      # incomplete escape: wait for more
            out.append(buf[j : j + 2])
            j += 2
            continue
        if c == '"':
            return True, "".join(out)
        out.append(c)
        j += 1
    return False, "".join(out)


def _unescape(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except ValueError:
        return raw


def _flush_sentences(buf: str, final: bool) -> tuple[list[str], str]:
    """Split accumulated say-text into complete sentences.

    Returns (complete_sentences, remainder). Fragments without any
    pronounceable character (e.g. a bare "……" pause mark) are dropped;
    ultra-short pronounceable fragments are held back and merged into
    the next sentence."""
    if final:
        s = re.sub(r"^[^\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9]+", "", buf.strip())
        return ([s] if s and PRONOUNCEABLE.search(s) else []), ""
    *done, rest = SENT_SPLIT.split(buf)
    out: list[str] = []
    hold = ""
    for p in done:
        p = (hold + p).strip()
        hold = ""
        if not p or not PRONOUNCEABLE.search(p):
            continue                       # pure pause/punctuation: drop
        if len(p) <= 2:
            hold = p                       # too short alone; merge forward
            continue
        out.append(p)
    return out, hold + rest


# ---- public API -------------------------------------------------------------

async def generate_stream(session: Session, user_text: str, guard: RoundGuard):
    """Yields ("sentence", str) as say-sentences complete, then
    ("final", {"say", "directives", "fallback"}) once the reply is done."""
    if not config.use_dashscope_llm():
        result = {**story.respond(session, user_text), "fallback": False}
        for s in _flush_sentences(result["say"], final=True)[0]:
            yield "sentence", s
        yield "final", result
        return

    t0 = time.perf_counter()
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(node=session.node)}]
    messages += session.history[-12:]
    messages.append({"role": "user", "content": user_text})

    chunks: list[str] = []
    say_emitted = ""                          # prefix of say already yielded
    said_done = False

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            async with client.stream(
                "POST",
                f"{config.DASHSCOPE_BASE}/compatible-mode/v1/chat/completions",
                headers={"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}"},
                json={
                    "model": config.LLM_MODEL,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.8,
                    "stream": True,
                },
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        delta = json.loads(payload)["choices"][0]["delta"].get("content")
                    except Exception:
                        continue
                    if not delta:
                        continue
                    chunks.append(delta)
                    if said_done:
                        continue           # say finished; let directives stream
                    done, raw = _extract_say_partial("".join(chunks))
                    if not raw:
                        continue
                    full_text = _unescape(raw)
                    if not full_text.startswith(say_emitted):
                        continue           # model backtracked; parse at end
                    fresh = full_text[len(say_emitted):]
                    sents, rest = _flush_sentences(fresh, final=done)
                    say_emitted = full_text[: len(full_text) - len(rest)] if rest else full_text
                    for s in sents:
                        yield "sentence", s
                    if done:
                        said_done = True

        content = "".join(chunks)
        data = json.loads(content)
        say = str(data.get("say", "")).strip()
        if not say:
            raise ValueError("empty say")
        dirs = directives.validate(data.get("directives"))
        for d in dirs:
            if d["t"] == "goto":
                session.goto(d["v"])
        guard.patch(llm_ms=int((time.perf_counter() - t0) * 1000))
        yield "final", {"say": say, "directives": dirs, "fallback": False}
    except Exception:
        # graceful degradation: scripted brain takes over, demo continues.
        # if a few streamed sentences already went out, the story reply
        # simply continues the same turn - acceptable in degraded mode.
        result = {**story.respond(session, user_text), "fallback": True}
        for s in _flush_sentences(result["say"], final=True)[0]:
            yield "sentence", s
        guard.patch(llm_ms=int((time.perf_counter() - t0) * 1000))
        yield "final", result
