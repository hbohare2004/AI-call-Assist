from __future__ import annotations

import base64
import binascii
import logging
import re

import httpx
from fastapi import HTTPException
from sarvamai import AsyncSarvamAI
from sarvamai.core.api_error import ApiError

from services.config import SARVAM_API_KEY, SARVAM_TTS_MODEL, SARVAM_TTS_SPEAKER

logger = logging.getLogger(__name__)
MAX_TTS_TEXT_LENGTH = 2500
DEVANAGARI_PATTERN = re.compile(r"[\u0900-\u097f]")


async def synthesize_speech(text: str) -> tuple[bytes, str]:
    cleaned_text = text.strip()
    if not cleaned_text:
        raise HTTPException(status_code=422, detail="Speech text cannot be blank.")
    if len(cleaned_text) > MAX_TTS_TEXT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Sarvam text-to-speech supports up to {MAX_TTS_TEXT_LENGTH} characters per request.",
        )
    if not SARVAM_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Speech generation is not configured. Set SARVAM_API_KEY in the project .env file.",
        )

    language_code = "hi-IN" if DEVANAGARI_PATTERN.search(cleaned_text) else "en-IN"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http_client:
            client = AsyncSarvamAI(
                api_subscription_key=SARVAM_API_KEY,
                timeout=60.0,
                httpx_client=http_client,
            )
            response = await client.text_to_speech.convert(
                text=cleaned_text,
                model=SARVAM_TTS_MODEL,
                language_code=language_code,
                speaker=SARVAM_TTS_SPEAKER,
                pace=1,
                speech_sample_rate=22050,
                output_audio_codec="wav",
            )
    except ApiError as exc:
        status_code = exc.status_code
        logger.warning("Sarvam TTS request failed with HTTP status %s", status_code)
        if status_code in (401, 403):
            raise HTTPException(
                status_code=503,
                detail="Sarvam rejected SARVAM_API_KEY. Check the key and account access.",
            ) from exc
        if status_code == 429:
            raise HTTPException(status_code=429, detail="Sarvam speech generation is rate limited. Try again shortly.") from exc
        if status_code == 402:
            raise HTTPException(
                status_code=402,
                detail="Sarvam account credits are exhausted. Check the account balance and billing.",
            ) from exc
        if status_code in (408, 504):
            raise HTTPException(status_code=504, detail="Sarvam speech generation timed out.") from exc
        raise HTTPException(
            status_code=502,
            detail=f"Sarvam speech generation failed (HTTP {status_code or 'unknown'}).",
        ) from exc
    except httpx.TimeoutException as exc:
        logger.warning("Sarvam TTS request timed out")
        raise HTTPException(status_code=504, detail="Sarvam speech generation timed out.") from exc
    except httpx.RequestError as exc:
        logger.warning("Sarvam TTS connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not connect to Sarvam speech generation.") from exc

    if not response.audios or not response.audios[0]:
        raise HTTPException(status_code=502, detail="Sarvam returned an empty speech response.")
    try:
        audio = base64.b64decode("".join(response.audios), validate=True)
    except (binascii.Error, ValueError) as exc:
        logger.warning("Sarvam TTS returned invalid base64 audio")
        raise HTTPException(status_code=502, detail="Sarvam returned invalid audio data.") from exc
    if not audio:
        raise HTTPException(status_code=502, detail="Sarvam returned empty audio data.")
    return audio, "audio/wav"
