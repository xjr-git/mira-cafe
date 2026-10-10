"""TTS provider.

- dashscope CosyVoice2 (needs key)  - primary when available
- edge-tts (free, no key)           - default / fallback

Text is pre-split into sentences by the caller so the first audio chunk
streams out quickly; results are cached on disk by content hash.

Concurrency safety (multi-client):
- _SEMO caps concurrent synthesis jobs (protects the 2C2G box's bandwidth
  and the provider's QPS); extras just queue.
- cache files are written to a unique .part temp then os.replace()'d into
  place, so a concurrent reader can never see a half-written mp3.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time

import httpx

from .. import config

_SEMO = asyncio.Semaphore(6)

_sentinel = object()


async def synth(text: str) -> str:
    """Synthesize one sentence, return the served file name (under /audio/)."""
    voice_key = config.EDGE_TTS_VOICE if not config.use_dashscope_tts() else config.DASHSCOPE_TTS_VOICE
    name = hashlib.sha1(f"{voice_key}::{text}".encode()).hexdigest()[:16] + ".mp3"
    path = config.TTS_DIR / name
    if path.exists() and path.stat().st_size > 1000:
        return name

    async with _SEMO:
        # double-check: another task may have finished the same file while
        # we were queued on the semaphore
        if path.exists() and path.stat().st_size > 1000:
            return name
        try:
            if config.use_dashscope_tts():
                await _dashscope_tts(text, path)
            else:
                await _edge_tts(text, path)
        except Exception:
            # provider failed -> degrade to edge-tts before giving up
            await _edge_tts(text, path)
    return name


async def _edge_tts(text: str, path) -> None:
    import edge_tts

    com = edge_tts.Communicate(text, config.EDGE_TTS_VOICE, rate="+4%")
    await _atomic_save(com, path)


async def _atomic_save(com, path) -> None:
    tmp = path.with_suffix(f".{os.getpid()}{id(com)}.part")
    try:
        await com.save(str(tmp))
        os.replace(tmp, path)          # atomic on POSIX & Windows
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


async def _dashscope_tts(text: str, path) -> None:
    """Non-streaming CosyVoice2 call via dashscope REST (adequate per
    sentence; streaming adds little once sentences are short)."""
    import base64

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{config.DASHSCOPE_BASE}/api/v1/services/audio/tts",
            headers={
                "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.DASHSCOPE_TTS_MODEL,
                "input": {"text": text, "voice": config.DASHSCOPE_TTS_VOICE},
                "parameters": {"format": "mp3"},
            },
        )
        r.raise_for_status()
        data = r.json()
        audio_b64 = data.get("output", {}).get("audio") or data.get("output", {}).get("data")
        if not audio_b64:
            raise RuntimeError(f"tts response missing audio: {str(data)[:200]}")
        tmp = path.with_suffix(f".{os.getpid()}.part")
        try:
            tmp.write_bytes(base64.b64decode(audio_b64))
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
