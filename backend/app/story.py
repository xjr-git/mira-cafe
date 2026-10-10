"""Scripted story brain ("Mock mode").

A deterministic keyword + story-node engine that drives Mira's 3-5 minute
arc without any external API. This is what runs when DASHSCOPE_API_KEY is
absent, and it is also the fallback when the real LLM times out or returns
malformed JSON - so the demo can never die mid-conversation."""
from __future__ import annotations

from .session import Session

POLAROID_LINES = [
    ("你看这张——京都的雨夜，灯笼全泡在水里。他以前总说，雨里的街才像会呼吸。", "happy"),
    ("这张是雨刚停的时候拍的。地上的光还没干，像整条街都在慢慢清醒。", "surprised"),
    ("最后这张……是他拍我的。桌上两杯热可可，一杯是我的，一杯一直是他的。", "shy"),
]


def _kw(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def respond(session: Session, text: str) -> dict:
    """Return {"say": str, "directives": [..]} based on node + keywords."""
    t = text or ""
    node = session.node
    say = ""
    dirs: list[dict] = []

    # ---- universal: wants to see photos ---------------------------------
    if node != "ending" and _kw(t, "照片", "摄影", "相机", "拍", "作品"):
        idx = session.media_shown
        if idx < len(POLAROID_LINES):
            line, emo = POLAROID_LINES[idx]
            session.media_shown += 1
            session.goto("reveal")
            return {
                "say": line if idx else "你想看照片？……好吧，只给你看一张。 " + line,
                "directives": [
                    {"t": "emotion", "v": emo},
                    {"t": "action", "v": "look_camera"},
                    {"t": "media", "kind": "polaroid",
                     "prompt": "travel film photo taken by Mira"},
                ],
            }
        session.goto("reveal")

    # ---- ending trigger ---------------------------------------------------
    if node in ("reveal", "confide") and (
        session.media_shown >= 2 or _kw(t, "雨停", "停了", "告别", "再见", "走了")
    ) and not session.rain_stopped:
        session.rain_stopped = True
        session.goto("ending")
        return {
            "say": "……你听。雨停了。他没赶上这场雨，那大概，是我等错了伞。谢谢你听完一个陌生人的故事——今晚的咖啡记我账上。雨后的街很干净，很适合走路。",
            "directives": [
                {"t": "emotion", "v": "surprised"},
                {"t": "scene", "v": "rain_stop"},
                {"t": "emotion", "v": "happy"},
            ],
        }

    # ---- per-node rules ----------------------------------------------------
    if _kw(t, "你是谁", "名字", "叫什么", "介绍"):
        say = "我叫 Mira，二十六岁，自由旅行摄影师。泡在这家店的时间，比按快门的时间还长。"
        dirs = [{"t": "emotion", "v": "happy"}, {"t": "action", "v": "stir_coffee"}]
    elif _kw(t, "等人", "等谁", "在等"):
        say = "你怎么知道我在等人……不，是我自己说漏嘴了。我在等一个人。他答应过，雨停之前会回来。"
        dirs = [{"t": "emotion", "v": "shy"}, {"t": "action", "v": "stir_coffee"}]
        session.goto("confide")
    elif _kw(t, "雨", "暴雨", "天气"):
        say = "暴雨天我总在这家店里发呆。雨声很吵，但吵得刚刚好，能把别的声音都盖过去。"
        dirs = [{"t": "emotion", "v": "sad"}, {"t": "action", "v": "gaze_window"}]
    elif _kw(t, "咖啡", "喝", "点单", "推荐", "菜单"):
        say = "这家的康帕努拉豆不错，奶放少一点更香。要我帮你叫一杯吗？外面雨这么大，急什么。"
        dirs = [{"t": "emotion", "v": "happy"}]
    elif _kw(t, "他", "那个人", "约定", "回来"):
        say = "三年前我们约好，各自去旅行一年，回到这家店碰面。今天正好是期限。雨这么大……他大概在路上吧。"
        dirs = [{"t": "emotion", "v": "sad"}, {"t": "action", "v": "gaze_window"}]
        session.goto("confide")
    elif _kw(t, "再见", "拜拜", "走了", "告辞"):
        say = "路上小心。伞……我把这把借你。反正，等的人回来会带新的。"
        dirs = [{"t": "emotion", "v": "sad"}]
        session.goto("ending")
    else:
        # node-specific smalltalk
        if node == "opening":
            say = "……啊，抱歉，走神了。欢迎光临。这么大的雨，你也是进来躲雨的吗？"
            dirs = [{"t": "emotion", "v": "surprised"}]
            session.goto("smalltalk")
        elif node == "smalltalk":
            say = "雨夜的客人不多。你坐这儿吧——有人说，暴雨的夜晚适合说真话，你信吗？"
            dirs = [{"t": "emotion", "v": "shy"}, {"t": "action", "v": "stir_coffee"}]
        elif node == "confide":
            say = "抱歉，说这些有点突然。就当……听一个陌生人的故事，好不好？"
            dirs = [{"t": "emotion", "v": "shy"}]
        elif node == "reveal":
            say = "我拍了三年雨景，因为他说过最喜欢雨里的街。这些照片，本来是准备送他的。"
            dirs = [{"t": "emotion", "v": "sad"}, {"t": "action", "v": "look_camera"}]
        else:  # ending
            say = "雨后的空气真好。这条街被洗过一遍，路灯都变亮了。……下次再来，我请你喝热可可。"
            dirs = [{"t": "emotion", "v": "happy"}]

    return {"say": say, "directives": dirs}
