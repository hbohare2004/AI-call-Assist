from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from database.db import db_connect, insert_message
from services.llm_service import SYSTEM_PROMPT, generate_response
from services.stt_service import transcribe_audio
from services.tts_service import synthesize_speech

GREETING = "नमस्ते! मैं हर्ष की एआई सहायक हूँ। हर्ष अभी उपलब्ध नहीं हैं। बताइए, आपको क्या काम था?"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_call_session() -> dict[str, str]:
    call_id = str(uuid.uuid4())
    started_at = now_iso()
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO calls (id, started_at, status) VALUES (?, ?, 'active')",
            (call_id, started_at),
        )
        insert_message(conn, call_id, "assistant", GREETING, started_at)
    return {"call_id": call_id, "started_at": started_at, "greeting": GREETING}


async def respond_to_call(call_id: str, transcript: str) -> dict[str, str]:
    cleaned_transcript = transcript.strip()
    if not cleaned_transcript:
        raise HTTPException(status_code=422, detail="Message cannot be blank.")

    with db_connect() as conn:
        latest = conn.execute(
            "SELECT role, content FROM messages WHERE call_id = ? ORDER BY id DESC LIMIT 1",
            (call_id,),
        ).fetchone()
        if not latest or latest["role"] != "user" or latest["content"] != cleaned_transcript:
            insert_message(conn, call_id, "user", cleaned_transcript, now_iso())
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE call_id = ? ORDER BY id DESC LIMIT 24",
            (call_id,),
        ).fetchall()
    history = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
    response = await generate_response(history, instructions=SYSTEM_PROMPT)
    created_at = now_iso()
    with db_connect() as conn:
        insert_message(conn, call_id, "assistant", response, created_at)
    return {"call_id": call_id, "response": response, "created_at": created_at}


async def process_audio_call(
    audio: bytes,
    content_type: str,
    filename: str | None = None,
    call_id: str | None = None,
) -> dict[str, str]:
    if call_id is None:
        call = create_call_session()
        call_id = call["call_id"]

    transcription = await transcribe_audio(audio, content_type, filename)
    with db_connect() as conn:
        insert_message(conn, call_id, "user", transcription, now_iso())
    answer = await respond_to_call(call_id, transcription)
    audio_bytes, media_type = await synthesize_speech(answer["response"])
    return {
        "call_id": call_id,
        "transcription": transcription,
        "response": answer["response"],
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_media_type": media_type,
    }


async def transcribe_and_store(
    audio: bytes,
    content_type: str,
    filename: str | None = None,
    call_id: str | None = None,
) -> dict[str, str | None]:
    transcription = await transcribe_audio(audio, content_type, filename)
    if call_id is not None:
        with db_connect() as conn:
            insert_message(conn, call_id, "user", transcription, now_iso())
    return {"call_id": call_id, "transcription": transcription}
