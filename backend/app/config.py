"""Central configuration. All external credentials are optional:
without DASHSCOPE_API_KEY the app runs in full Mock mode."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # mira-cafe/
APP_DIR = Path(__file__).resolve().parent                 # backend/app
STATIC_DIR = APP_DIR / "static"
RUNTIME_DIR = APP_DIR / "runtime"
TTS_DIR = RUNTIME_DIR / "tts"
IMAGE_CACHE_DIR = RUNTIME_DIR / "image_cache"

load_dotenv(BASE_DIR / ".env")

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()

TTS_PROVIDER = os.getenv("MIRA_TTS_PROVIDER", "auto").strip().lower()
IMAGE_PROVIDER = os.getenv("MIRA_IMAGE_PROVIDER", "auto").strip().lower()
LLM_MODEL = os.getenv("MIRA_LLM_MODEL", "qwen-plus").strip()

EDGE_TTS_VOICE = "zh-CN-XiaoyiNeural"          # young female voice
DASHSCOPE_TTS_MODEL = "cosyvoice-v2"
DASHSCOPE_TTS_VOICE = "longxiaochun"
DASHSCOPE_IMAGE_MODEL = "wanx2.1-t2i-turbo"
DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"

PORT = int(os.getenv("MIRA_PORT", "8000"))

for d in (TTS_DIR, IMAGE_CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)


def use_dashscope_tts() -> bool:
    if TTS_PROVIDER == "edge":
        return False
    if TTS_PROVIDER == "dashscope":
        return bool(DASHSCOPE_API_KEY)
    return bool(DASHSCOPE_API_KEY)  # auto


def use_dashscope_image() -> bool:
    if IMAGE_PROVIDER == "mock":
        return False
    if IMAGE_PROVIDER == "dashscope":
        return bool(DASHSCOPE_API_KEY)
    return bool(DASHSCOPE_API_KEY)  # auto


def use_dashscope_llm() -> bool:
    return bool(DASHSCOPE_API_KEY)
