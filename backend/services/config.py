from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BACKEND_DIR / "calls.db"

load_dotenv(BACKEND_DIR / ".env", override=False)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
STT_MODEL = os.getenv("STT_MODEL", "saaras:v3")
SARVAM_STT_LANGUAGE_CODE = os.getenv("STT_LANGUAGE_CODE", "unknown")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_TTS_MODEL = os.getenv("TTS_MODEL", "bulbul:v4-flash")
SARVAM_TTS_SPEAKER = os.getenv("TTS_SPEAKER", "aarti_hi_customer")
FRONTEND_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
    ).split(",")
    if origin.strip()
)
