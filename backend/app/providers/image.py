"""Image generation provider (polaroid photos).

- dashscope wanx2.1-t2i-turbo (needs key): real text-to-image
- mock: cycles preset bundled photos after a short theatrical delay
Both paths share a prompt-hash cache and a job store the frontend polls,
so the "developing polaroid" UX and failure degradation are identical."""
from __future__ import annotations

import asyncio
import hashlib
import itertools
import time
import uuid

import httpx

from .. import config

_jobs: dict[str, dict] = {}
_counter = itertools.count(1)

PRESETS = [
    "/assets/polaroid1.jpg",
    "/assets/polaroid2.jpg",
    "/assets/polaroid3.jpg",
]
MOCK_DELAY_S = 2.2          # "developing" wait so the moment feels real
GENERATE_TIMEOUT_S = 45


def _cache_key(prompt: str) -> str:
    return hashlib.sha1(prompt.encode()).hexdigest()[:16]


async def submit(prompt: str) -> str:
    job_id = f"job{next(_counter)}-{uuid.uuid4().hex[:6]}"
    _jobs[job_id] = {"status": "pending", "url": "", "created": time.time()}
    asyncio.get_event_loop().create_task(_run(job_id, prompt))
    return job_id


def status(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        return {"status": "failed", "url": "", "error": "unknown job"}
    return {k: job.get(k, "") for k in ("status", "url", "error", "degraded")}


async def _run(job_id: str, prompt: str) -> None:
    job = _jobs[job_id]
    key = _cache_key(prompt)
    cached = config.IMAGE_CACHE_DIR / f"{key}.png"
    try:
        if cached.exists():
            job.update(status="done", url=f"/image-cache/{key}.png")
            return
        if config.use_dashscope_image() and prompt.strip():
            url = await _dashscope_t2i(prompt, cached)
            job.update(status="done", url=url)
        else:
            await asyncio.sleep(MOCK_DELAY_S)  # let the develop animation play
            preset = PRESETS[len(_jobs) % len(PRESETS)]
            job.update(status="done", url=preset)
    except Exception as e:  # generation failed -> degrade to preset photo
        job.update(status="failed", error=str(e)[:200])
        await asyncio.sleep(0.8)
        preset = PRESETS[len(_jobs) % len(PRESETS)]
        job.update(status="done", url=preset, degraded=True)


async def _dashscope_t2i(prompt: str, out_path) -> str:
    async with httpx.AsyncClient(timeout=GENERATE_TIMEOUT_S) as client:
        r = await client.post(
            f"{config.DASHSCOPE_BASE}/api/v1/services/aigc/text2image/image-synthesis",
            headers={
                "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            json={
                "model": config.DASHSCOPE_IMAGE_MODEL,
                "input": {"prompt": prompt},
                "parameters": {"size": "1024*1024", "n": 1},
            },
        )
        r.raise_for_status()
        task_id = r.json()["output"]["task_id"]

        for _ in range(60):
            await asyncio.sleep(2)
            p = await client.get(
                f"{config.DASHSCOPE_BASE}/api/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}"},
            )
            p.raise_for_status()
            out = p.json()["output"]
            if out.get("task_status") == "SUCCEEDED":
                url = out["results"][0]["url"]
                img = await client.get(url)
                img.raise_for_status()
                out_path.write_bytes(img.content)
                return f"/image-cache/{out_path.name}"
            if out.get("task_status") == "FAILED":
                raise RuntimeError("wanx task failed")
        raise TimeoutError("wanx task timeout")
