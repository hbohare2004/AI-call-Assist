from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from database.db import (
    db_connect,
    get_call,
    init_db,
    list_calls,
    update_call_summary,
)
from services.call_service import (
    create_call_session,
    now_iso,
    process_audio_call,
    respond_to_call,
    transcribe_and_store,
)
from services.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    FRONTEND_ORIGINS,
    SARVAM_API_KEY,
    SARVAM_STT_LANGUAGE_CODE,
    SARVAM_TTS_MODEL,
    SARVAM_TTS_SPEAKER,
    STT_MODEL,
)
from services.summary_service import generate_summary
from services.stt_service import MAX_AUDIO_BYTES
from services.tts_service import synthesize_speech

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Call Assistant API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["DELETE", "GET", "POST"],
    allow_headers=["*"],
)

def require_active_call(call_id: str) -> dict:
    call = get_call(call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if call["status"] != "active":
        raise HTTPException(status_code=409, detail="This conversation has already ended.")
    return call


async def read_audio_upload(audio: UploadFile) -> bytes:
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    await audio.close()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded audio is empty.")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio must be 25 MB or smaller.")
    return content


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2000)
    call_id: str | None = Field(default=None, min_length=1)


class RespondRequest(StrictModel):
    transcript: str = Field(min_length=1, max_length=2000)


class TextRequest(StrictModel):
    text: str = Field(min_length=1, max_length=2500)


@app.get("/health")
@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "database": "sqlite",
        "services": {
            "groq": {
                "configured": bool(GROQ_API_KEY),
                "model": GROQ_MODEL,
                "stt_model": STT_MODEL,
            },
            "sarvam": {
                "configured": bool(SARVAM_API_KEY),
                "stt_model": STT_MODEL,
                "stt_language_code": SARVAM_STT_LANGUAGE_CODE,
                "tts_model": SARVAM_TTS_MODEL,
                "speaker": SARVAM_TTS_SPEAKER,
            },
        },
    }


@app.post("/api/calls", status_code=201)
async def start_call() -> dict[str, str]:
    return create_call_session()


@app.post("/api/transcribe")
async def transcribe(
    audio: Annotated[UploadFile, File(description="Caller audio file")],
    call_id: Annotated[str | None, Form()] = None,
) -> dict[str, str | None]:
    if call_id:
        require_active_call(call_id)
    content = await read_audio_upload(audio)
    result = await transcribe_and_store(
        content,
        audio.content_type or "",
        audio.filename,
        call_id,
    )
    return {
        **result,
        "transcript": result["transcription"],
        "created_at": now_iso(),
    }


@app.post("/api/chat")
async def chat(body: ChatRequest) -> dict[str, str]:
    if body.call_id:
        require_active_call(body.call_id)
        call_id = body.call_id
    else:
        call_id = create_call_session()["call_id"]
    return await respond_to_call(call_id, body.message)


@app.post("/api/tts")
async def text_to_speech(body: TextRequest) -> Response:
    audio, media_type = await synthesize_speech(body.text)
    return Response(
        content=audio,
        media_type=media_type,
        headers={"Cache-Control": "no-store", "Content-Disposition": 'inline; filename="assistant-response.wav"'},
    )


@app.post("/api/call/process")
async def process_call(
    audio: Annotated[UploadFile, File(description="A complete caller speech segment")],
    call_id: Annotated[str | None, Form()] = None,
) -> dict[str, str]:
    if call_id:
        require_active_call(call_id)
    content = await read_audio_upload(audio)
    return await process_audio_call(
        content,
        audio.content_type or "",
        audio.filename,
        call_id,
    )


@app.post("/api/calls/{call_id}/transcribe")
async def transcribe_call(
    call_id: str,
    audio: Annotated[UploadFile, File(description="A complete caller speech segment")],
) -> dict[str, str]:
    require_active_call(call_id)
    content = await read_audio_upload(audio)
    transcription = await transcribe_and_store(
        content,
        audio.content_type or "",
        audio.filename,
        call_id,
    )
    return {
        "call_id": call_id,
        "transcript": str(transcription["transcription"]),
        "created_at": now_iso(),
    }


@app.post("/api/calls/{call_id}/respond")
async def respond(call_id: str, body: RespondRequest) -> dict[str, str]:
    require_active_call(call_id)
    return await respond_to_call(call_id, body.transcript)


@app.post("/api/calls/{call_id}/speak")
async def speak(call_id: str, body: TextRequest) -> Response:
    require_active_call(call_id)
    audio, media_type = await synthesize_speech(body.text)
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.post("/api/calls/{call_id}/end")
async def end_call(call_id: str) -> dict:
    call = get_call(call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if call["status"] == "completed":
        details = get_call(call_id, include_messages=True)
        if details and details["call_summary"] is not None:
            return {
                "call_id": call_id,
                "summary": details["call_summary"],
                "transcript": details["call_summary"]["transcript"],
            }

    with db_connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE call_id = ? ORDER BY id",
            (call_id,),
        ).fetchall()
    transcript = "\n".join(
        f"{'Caller' if row['role'] == 'user' else 'AI assistant'}: {row['content']}"
        for row in rows
    )
    summary = await generate_summary(transcript)
    ended_at = call["ended_at"] or now_iso()
    update_call_summary(call_id, ended_at, summary)
    return {"call_id": call_id, "ended_at": ended_at, "summary": summary, "transcript": transcript}


@app.get("/api/calls")
async def get_calls() -> dict:
    return {"calls": list_calls()}


@app.get("/api/calls/{call_id}")
async def get_call_details(call_id: str) -> dict:
    call = get_call(call_id, include_messages=True)
    if call is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return call


@app.delete("/api/calls/{call_id}")
async def delete_call(call_id: str) -> dict[str, str | bool]:
    with db_connect() as conn:
        if conn.execute("SELECT id FROM calls WHERE id = ?", (call_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        conn.execute("DELETE FROM messages WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM call_summaries WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM calls WHERE id = ?", (call_id,))
    return {"deleted": True, "call_id": call_id}
