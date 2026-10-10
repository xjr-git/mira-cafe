"""Concurrency verification for mira-cafe (run against a live server).

Three tests:
  A. session isolation  - two different X-Sid clients must NOT share state
  B. load test          - 10 concurrent chat rounds (distinct sids),
                          report success rate / first-subtitle / total (P50/P95)
  C. interrupt storm    - fire a round then interrupt it immediately, then
                          start a fresh round on the SAME sid; stale events
                          from round 1 must not leak into round 2

Usage: python concurrency_test.py https://host:port
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
VERIFY = BASE.startswith("https")

QA = [
    "你好，你是谁？",
    "今天雨真大啊",
    "你是做什么工作的？",
    "这家店要打烊了吗",
    "给我讲讲你旅行的事",
    "你为什么一个人在这里",
    "咖啡好喝吗",
    "外面雨停了吗",
    "你在等什么人吗",
    "聊点开心的吧",
]


def hdr(sid: str) -> dict:
    return {"Content-Type": "application/json", "X-Sid": sid}


async def one_round(c: httpx.AsyncClient, sid: str, text: str, stop_after_first_sub: bool = False):
    """Stream one chat round; returns dict of timings + event counts."""
    t0 = time.perf_counter()
    first_sub = None
    n_audio = n_events = 0
    stale = False
    async with c.stream("POST", f"{BASE}/api/chat", headers=hdr(sid),
                        json={"text": text}, timeout=90) as r:
        event = None
        rid = None
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
                n_events += 1
            elif line.startswith("data:") and event:
                data = line[5:].strip()
                if event == "round":
                    rid = int(data.split(":")[1].strip("{} \"").split(",")[0].split(":")[-1]) if data else None
                    try:
                        rid = __import__("json").loads(data)["round_id"]
                    except Exception:
                        pass
                elif event == "subtitle" and first_sub is None:
                    first_sub = time.perf_counter() - t0
                    if stop_after_first_sub:
                        break
                elif event == "audio":
                    n_audio += 1
                    try:
                        d = __import__("json").loads(data)
                        if rid is not None and d.get("round_id") != rid:
                            stale = True
                        if d.get("seq", 0) < 0:
                            stale = True
                    except Exception:
                        pass
                elif event == "error":
                    stale = True
    total = time.perf_counter() - t0
    return {"first_sub": first_sub, "total": total, "audio": n_audio,
            "events": n_events, "stale": stale}


async def test_isolation(c: httpx.AsyncClient):
    print("\n=== Test A: 会话隔离（两个 sid 互不串台）===")
    sa, sb = "test-sid-A", "test-sid-B"
    await c.post(f"{BASE}/api/reset", headers=hdr(sa))
    await c.post(f"{BASE}/api/reset", headers=hdr(sb))

    await one_round(c, sa, "你好")                       # A聊一轮
    state_a = (await c.get(f"{BASE}/api/state", headers=hdr(sa))).json()
    state_b = (await c.get(f"{BASE}/api/state", headers=hdr(sb))).json()

    ok = state_a["turns"] == 1 and state_b["turns"] == 0 and state_b["node"] == "opening"
    print(f"  A: turns={state_a['turns']} node={state_a['node']} | B: turns={state_b['turns']} node={state_b['node']}")
    print(f"  -> {'PASS 会话已隔离' if ok else 'FAIL 状态串台！'}")
    return ok


async def test_load(c: httpx.AsyncClient):
    print("\n=== Test B: 10 路并发压测（独立 sid）===")
    sids = [f"load-{i}" for i in range(10)]
    await asyncio.gather(*[c.post(f"{BASE}/api/reset", headers=hdr(s)) for s in sids])

    t0 = time.perf_counter()
    results = await asyncio.gather(*[
        one_round(c, s, QA[i % len(QA)]) for i, s in enumerate(sids)
    ], return_exceptions=True)
    wall = time.perf_counter() - t0

    ok_results, errs = [], []
    for r in results:
        if isinstance(r, Exception):
            errs.append(str(r)[:80])
        elif r["events"] > 0 and not r["stale"]:
            ok_results.append(r)
        else:
            errs.append("stale/error events")

    ok = len(ok_results) >= 9 and not errs
    if ok_results:
        subs = sorted(r["first_sub"] for r in ok_results if r["first_sub"])
        totals = sorted(r["total"] for r in ok_results)
        auds = sum(r["audio"] for r in ok_results)

        def pct(lst, p):
            return lst[min(len(lst) - 1, int(len(lst) * p))] if lst else 0

        print(f"  成功 {len(ok_results)}/10 | 失败: {errs if errs else '无'}")
        print(f"  首字幕  P50={pct(subs, .5):.2f}s  P95={pct(subs, .95):.2f}s")
        print(f"  整轮    P50={pct(totals, .5):.2f}s  P95={pct(totals, .95):.2f}s")
        print(f"  音频事件总数 {auds} | 并发墙钟时间 {wall:.2f}s")
    print(f"  -> {'PASS 并发正常' if ok else 'FAIL 存在失败轮'}")
    return ok


async def test_interrupt(c: httpx.AsyncClient):
    print("\n=== Test C: 打断风暴（同 sid 连续打断后新轮不受污染）===")
    sid = "storm-1"
    await c.post(f"{BASE}/api/reset", headers=hdr(sid))

    # round 1: start, wait for first subtitle, then interrupt mid-stream
    t0 = time.perf_counter()
    task = asyncio.create_task(one_round(c, sid, "给我讲讲你旅行的事，多讲一些"))
    await asyncio.sleep(2.0)                      # round 1 in-flight
    r = await c.post(f"{BASE}/api/interrupt", headers=hdr(sid), json={"round_id": 1})
    cancelled = r.json().get("cancelled", 0)
    r1 = await task
    t_interrupt = time.perf_counter() - t0

    # round 2 must complete cleanly on the same sid
    r2 = await one_round(c, sid, "你好")
    state = (await c.get(f"{BASE}/api/state", headers=hdr(sid))).json()

    # round1 should end fast after interrupt (stream cut), round2 healthy
    ok = r2["events"] > 0 and not r2["stale"] and r2["audio"] > 0 and state["turns"] >= 1
    print(f"  轮1: 打断后 {t_interrupt:.2f}s 收尾（事件 {r1['events']} 个）| 服务端标记取消 {cancelled} 轮")
    print(f"  轮2: 事件 {r2['events']} 个、音频 {r2['audio']} 段、无脏事件 {'✔' if not r2['stale'] else '✘'} | turns={state['turns']}")
    print(f"  -> {'PASS 打断后链路干净' if ok else 'FAIL 打断后出现脏状态'}")
    return ok


async def main():
    async with httpx.AsyncClient(verify=VERIFY, timeout=120) as c:
        state = (await c.get(f"{BASE}/api/state")).json()
        print(f"target={BASE}  mock={state.get('mock_mode')}  node={state.get('node')}")
        a = await test_isolation(c)
        b = await test_load(c)
        ci = await test_interrupt(c)
        print("\n================ SUMMARY ================")
        print(f"  会话隔离: {'PASS' if a else 'FAIL'}")
        print(f"  并发压测: {'PASS' if b else 'FAIL'}")
        print(f"  打断风暴: {'PASS' if ci else 'FAIL'}")
        print("  总体:", "ALL GREEN" if (a and b and ci) else "HAS FAILURES")


if __name__ == "__main__":
    asyncio.run(main())
