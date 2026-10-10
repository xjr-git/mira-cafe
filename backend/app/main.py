"""Mira Cafe - real-time interactive scene MVP.

One FastAPI service serves:
  /                the scene (zero-build frontend)
  /api/chat        POST -> SSE stream of round/subtitle/audio/directive events
  /api/interrupt   POST  mark rounds dead (belt & braces; the client also
                         aborts the fetch, which cancels the SSE generator)
  /api/image       polaroid generation job (submit / poll), with cache + degrade
  /audio, /image-cache  synthesized speech and generated pictures
  /metrics         tiny latency observability page
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, directives, story
from .guard import RoundGuard
from .providers import image as image_provider
from .providers import llm as llm_provider
from .providers import tts as tts_provider
from .session import SESSION

app = FastAPI(title="mira-cafe", version="1.0.0")
GUARD = RoundGuard()


class ChatReq(BaseModel):
    text: str


class InterruptReq(BaseModel):
    round_id: int


class ImageReq(BaseModel):
    prompt: str = ""


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def split_sentences(text: str) -> list[str]:
    parts = [p for p in re.split(r"(?<=[。！？…；!?;\n])", text) if p and p.strip()]
    # drop fragments with nothing pronounceable (e.g. a bare "……")
    parts = [p for p in parts if re.search(r"[\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9]", p)]
    if not parts and text.strip():
        parts = [text.strip()]
    # merge ultra-short fragments into neighbours to avoid choppy audio
    merged: list[str] = []
    for p in parts:
        p = p.strip()
        if merged and len(p) <= 2:
            merged[-1] += p
        else:
            merged.append(p)
    return merged


@app.post("/api/chat")
async def chat(req: ChatReq):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "empty text")
    round_id = GUARD.begin(text)
    t_start = time.perf_counter()

    async def gen():
        try:
            yield sse("round", {"round_id": round_id})
            yield sse("state", {"state": "thinking", "round_id": round_id})

            result = await llm_provider.generate(SESSION, text, GUARD)
            if GUARD.is_dead(round_id):   # interrupted while thinking
                return
            SESSION.add_history("user", text)
            SESSION.add_history("assistant", result["say"])

            if result.get("fallback"):
                yield sse("notice", {
                    "round_id": round_id,
                    "message": "LLM 超时/不可用，已降级为剧本模式继续",
                })

            dirs = directives.validate(result.get("directives"))
            for d in dirs:
                if d["t"] == "media" and d["kind"] == "polaroid":
                    job_id = await image_provider.submit(d.get("prompt", ""))
                    d["job_id"] = job_id
            for d in dirs:
                yield sse("directive", {"round_id": round_id, **d})

            yield sse("state", {"state": "speaking", "round_id": round_id})

            seq = 0
            tts_failed = False
            for sent in split_sentences(result["say"]):
                try:
                    name = await tts_provider.synth(sent, GUARD)
                except Exception:
                    tts_failed = True          # degrade: subtitle only
                    name = ""
                if GUARD.is_dead(round_id):
                    return
                yield sse("subtitle", {"seq": seq, "text": sent, "round_id": round_id})
                if name:
                    yield sse("audio", {"seq": seq, "url": f"/audio/{name}", "round_id": round_id})
                seq += 1
            if tts_failed:
                yield sse("notice", {"round_id": round_id, "message": "语音合成部分失败，本轮仅显示字幕"})

            GUARD.patch(total_ms=int((time.perf_counter() - t_start) * 1000))
            yield sse("done", {"round_id": round_id})
        except asyncio.CancelledError:
            # client aborted = user interrupted; nothing stale will be sent
            GUARD.mark_interrupted(round_id)
            raise
        except Exception as e:
            yield sse("error", {"round_id": round_id, "message": str(e)[:200]})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/interrupt")
async def interrupt(req: InterruptReq):
    n = GUARD.mark_interrupted(req.round_id)
    return {"ok": True, "cancelled": n}


@app.post("/api/image")
async def image_submit(req: ImageReq):
    job_id = await image_provider.submit(req.prompt)
    return {"job_id": job_id}


@app.get("/api/image/{job_id}")
async def image_status(job_id: str):
    return image_provider.status(job_id)


@app.get("/api/state")
async def state():
    return {
        "node": SESSION.node,
        "turns": len(SESSION.history) // 2,
        "media_shown": SESSION.media_shown,
        "rain_stopped": SESSION.rain_stopped,
        "mock_mode": not config.DASHSCOPE_API_KEY,
    }


@app.post("/api/reset")
async def reset():
    SESSION.reset()
    return {"ok": True}


@app.get("/api/metrics")
async def metrics():
    rows = [m.__dict__ for m in GUARD.metrics]
    done = [m for m in GUARD.metrics if not m.interrupted and m.total_ms]
    summary = {}
    if done:
        summary = {
            "rounds": len(done),
            "avg_llm_ms": sum(m.llm_ms for m in done) // len(done),
            "avg_tts_first_ms": sum(m.tts_first_ms for m in done) // len(done),
            "avg_total_ms": sum(m.total_ms for m in done) // len(done),
        }
    return {"summary": summary, "rounds": rows[-30:]}


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page():
    rows = "".join(
        f"<tr><td>{m.round_id}</td><td>{m.text}</td><td>{m.llm_ms}</td>"
        f"<td>{m.tts_first_ms}</td><td>{m.total_ms}</td>"
        f"<td>{'yes' if m.interrupted else ''}</td></tr>"
        for m in reversed(GUARD.metrics[-30:])
    )
    return f"""<html><head><meta charset="utf-8"><title>mira-cafe metrics</title>
<style>body{{font-family:monospace;background:#111;color:#ddd;padding:24px}}
table{{border-collapse:collapse}}td,th{{border:1px solid #444;padding:4px 10px}}</style></head>
<body><h2>mira-cafe round metrics</h2>
<p>refresh to update; interrupted rounds are excluded from averages</p>
<table><tr><th>round</th><th>text</th><th>llm_ms</th><th>tts_first_ms</th><th>total_ms</th><th>interrupted</th></tr>
{rows}</table></body></html>"""


# static frontend + generated media --------------------------------------
app.mount("/audio", StaticFiles(directory=str(config.TTS_DIR)), name="audio")
app.mount("/image-cache", StaticFiles(directory=str(config.IMAGE_CACHE_DIR)), name="image-cache")
app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")
