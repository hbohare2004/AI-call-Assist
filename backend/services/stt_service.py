from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import HTTPException
from sarvamai import AsyncSarvamAI
from sarvamai.core.api_error import ApiError

from services.config import SARVAM_API_KEY, SARVAM_STT_LANGUAGE_CODE, STT_MODEL

logger = logging.getLogger(__name__)
SUPPORTED_AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".mp4",
    "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/aac": ".aac",
    "audio/aiff": ".aiff",
    "audio/x-aiff": ".aiff",
    "audio/amr": ".amr",
    "audio/x-ms-wma": ".wma",
}
MAX_AUDIO_BYTES = 25 * 1024 * 1024


async def transcribe_audio(audio: bytes, content_type: str, filename: str | None = None) -> str:
    if not SARVAM_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Speech transcription is not configured. Set SARVAM_API_KEY in backend\\.env.",
        )
    if not audio:
        raise HTTPException(status_code=400, detail="The uploaded audio is empty.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio must be 25 MB or smaller.")

    media_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    extension = SUPPORTED_AUDIO_TYPES.get(media_type)
    if extension is None:
        raise HTTPException(
            status_code=415,
            detail="Unsupported audio format. Upload WebM, WAV, MP3, AAC, AIFF, OGG, OPUS, FLAC, MP4/M4A, AMR, or WMA audio.",
        )
    upload_name = Path(filename).name if filename else f"recording{extension}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as http_client:
            client = AsyncSarvamAI(
                api_subscription_key=SARVAM_API_KEY,
                timeout=90.0,
                httpx_client=http_client,
            )
            response = await client.speech_to_text.transcribe(
                file=(upload_name, audio, media_type),
                model=STT_MODEL,
                language_code=SARVAM_STT_LANGUAGE_CODE,
                mode="transcribe",
            )
    except ApiError as exc:
        status_code = exc.status_code
        logger.warning("Sarvam STT request failed with HTTP status %s", status_code)
        if status_code in (401, 403):
            raise HTTPException(
                status_code=503,
                detail="Sarvam rejected SARVAM_API_KEY. Check the key and account access.",
            ) from exc
        if status_code == 429:
            raise HTTPException(status_code=429, detail="Sarvam transcription is rate limited. Try again shortly.") from exc
        if status_code == 402:
            raise HTTPException(
                status_code=402,
                detail="Sarvam account credits are exhausted. Check the account balance and billing.",
            ) from exc
        if status_code in (408, 504):
            raise HTTPException(status_code=504, detail="Sarvam speech transcription timed out.") from exc
        raise HTTPException(
            status_code=502,
            detail=f"Sarvam speech transcription failed (HTTP {status_code or 'unknown'}). Check the audio format and model configuration.",
        ) from exc
    except httpx.TimeoutException as exc:
        logger.warning("Sarvam STT request timed out")
        raise HTTPException(status_code=504, detail="Sarvam speech transcription timed out.") from exc
    except httpx.RequestError as exc:
        logger.warning("Sarvam STT connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not connect to Sarvam speech transcription.") from exc

    transcript = response.transcript
    if not transcript or not transcript.strip():
        raise HTTPException(status_code=422, detail="No speech was detected in the audio.")
    return transcript.strip()
