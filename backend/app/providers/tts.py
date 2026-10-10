"""TTS provider.

- dashscope CosyVoice2 (needs key)  - primary when available
- edge-tts (free, no key)           - default / fallback

Text is pre-split into sentences by the caller so the first audio chunk
streams out quickly; results are cached on disk by content hash."""
from __future__ import annotations

import asyncio
import hashlib
import time

import httpx

from .. import config
from ..guard import RoundGuard

_sentinel = object()


async def synth(text: str, guard: RoundGuard) -> str:
    """Synthesize one sentence, return the served file name (under /audio/)."""
    voice_key = config.EDGE_TTS_VOICE if not config.use_dashscope_tts() else config.DASHSCOPE_TTS_VOICE
    name = hashlib.sha1(f"{voice_key}::{text}".encode()).hexdigest()[:16] + ".mp3"
    path = config.TTS_DIR / name
    if path.exists() and path.stat().st_size > 1000:
        return name

    t0 = time.perf_counter()
    try:
        if config.use_dashscope_tts():
            await _dashscope_tts(text, path)
        else:
            await _edge_tts(text, path)
    except Exception:
        # provider failed -> degrade to edge-tts before giving up
        await _edge_tts(text, path)
    finally:
        if guard._current and not guard._current.tts_first_ms:
            guard.patch(tts_first_ms=int((time.perf_counter() - t0) * 1000))
    return name


async def _edge_tts(text: str, path) -> None:
    import edge_tts

    com = edge_tts.Communicate(text, config.EDGE_TTS_VOICE, rate="+4%")
    await com.save(str(path))


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
        path.write_bytes(base64.b64decode(audio_b64))
