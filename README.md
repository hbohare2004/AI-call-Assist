# AI Call Assistant

A browser-based AI receptionist for Harsh. The Next.js dashboard records complete speech turns and sends them to a FastAPI backend. Sarvam AI transcribes caller speech and speaks the assistant's reply, while Groq handles the conversation and call summaries. SQLite stores call history.

## Architecture

- **Speech to text:** Sarvam AI `saaras:v3` in `transcribe` mode. Language defaults to `unknown` for automatic detection across Hindi and English; WebM and other documented audio formats are accepted.
- **AI responses and call summaries:** Groq Responses API using `openai/gpt-oss-20b`. Recent conversation messages are persisted in SQLite and provided as context. If Groq returns its `tool_use_failed` error for a text-only response, the backend retries that turn once with Groq Chat Completions.
- **Text to speech:** Official `sarvamai` SDK with `bulbul:v4-flash`, speaker `aarti_hi_customer` (Aarti), WAV output at 22050 Hz. Speech language is selected from the generated reply: Hindi for Devanagari and English for Latin text. The initial greeting is in Hindi; replies follow the caller's Hindi or English.
- **Storage:** SQLite in `backend/calls.db`; calls, messages, and structured summaries are stored locally.
- **Telephone integration:** Not included. The browser call/session workflow is kept separate so a telephony adapter can be added later.

All model inference uses hosted APIs; no AI models are run or downloaded locally. API keys stay in the backend environment.

## Project layout

```text
backend/
  main.py
  requirements.txt
  .env.example
  database/
  services/
  sarvam_chat.py
frontend/
  app/
  services/
  package.json
  .env.example
```

Backend Python code and secrets belong under `backend/`; Next.js source and its public API URL setting belong under `frontend/`. The root contains shared project documentation and `.gitignore`.

## Requirements

- Windows 10/11
- Python 3.11+
- Node.js 20.9+
- Chrome or Edge with microphone access
- Groq API key with access to Whisper and GPT-OSS
- Sarvam API key with Bulbul text-to-speech access

## Configure API keys

In PowerShell from the project root:

```powershell
Copy-Item backend\.env.example backend\.env
notepad backend\.env
```

Set `GROQ_API_KEY` and `SARVAM_API_KEY` in `backend\.env`. The dashboard and project messages remain in English; speech is Hindi by default and switches to English when the caller speaks English. The model defaults are already provided by `.env.example`:

```dotenv
GROQ_MODEL=openai/gpt-oss-20b
STT_MODEL=saaras:v3
STT_LANGUAGE_CODE=unknown
TTS_MODEL=bulbul:v4-flash
TTS_SPEAKER=aarti_hi_customer
```

Do not put provider keys in frontend environment variables. `.env` files are excluded by `.gitignore`. The backend loads configuration only from `backend\.env`.

## Run the backend

Open PowerShell in the project root:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Health: <http://127.0.0.1:8000/api/health>  
Interactive API documentation: <http://127.0.0.1:8000/docs>

## Run the frontend

In a second PowerShell window, from the project root:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>, allow microphone access, and start a conversation. Microphone access is prepared before the greeting, then recording resumes as soon as the assistant finishes speaking. Caller speech is automatically sent after the voice activity detector detects the end of an utterance; “Send now” remains available as a manual fallback. The dashboard also supports typed turns, stopping playback, ending calls, and browsing or deleting saved call history.

## Deployment configuration

Deploy `backend/` as the FastAPI service and `frontend/` as the Next.js app. Configure `GROQ_API_KEY` and `SARVAM_API_KEY` as backend-only secrets. Set the frontend's `NEXT_PUBLIC_API_URL` to the deployed backend URL, and set backend `FRONTEND_ORIGINS` to the deployed frontend origin(s), comma-separated with no trailing slash. The checked-in `.env.example` files contain local-development values; copy their variables into your deployment provider's environment settings rather than uploading `.env` files.

SQLite is stored in `backend/calls.db`. If the deployment platform uses ephemeral filesystems, attach persistent storage for this database or call history will be lost on redeploy/restart. The exact deployment steps depend on the hosting provider.

## API

- `POST /api/transcribe` — multipart audio upload (`audio`); optional form field `call_id` persists the transcript.
- `POST /api/chat` — JSON `{"message":"...","call_id":"..."}`; `call_id` is optional and enables conversation context and persistence.
- `POST /api/tts` — JSON `{"text":"..."}`; returns playable `audio/wav`.
- `POST /api/call/process` — multipart `audio` and optional `call_id`; runs Sarvam STT → Groq LLM → Sarvam TTS and returns transcript, response, and base64 WAV audio.
- `POST /api/calls` — creates a call session and initial greeting.
- `POST /api/calls/{id}/transcribe`, `/respond`, `/speak`, and `/end` — call-scoped compatibility endpoints used for session workflows and summary generation.
- `GET /api/calls` and `GET /api/calls/{id}` — retrieve call history or full call details.
- `DELETE /api/calls/{id}` — delete a call and its related records.
- `GET /api/health` and `/health` — report service configuration without exposing API keys.

The browser UI uses `/api/transcribe`, `/api/chat`, and `/api/tts` for each recorded turn. End a conversation to generate and save the structured summary and transcript. Unknown caller details are recorded as “Not provided.” Caller phone numbers are only included if stated in the conversation; this browser demo does not receive telephone-network caller ID.

## Test each service

Start the backend first. These commands exercise the live configured provider APIs:

```powershell
# Groq LLM
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/chat `
  -ContentType "application/json" `
  -Body '{"message":"Hello, I am calling about an appointment."}'

# Sarvam TTS (returns WAV audio at 22050 Hz)
Invoke-WebRequest -Method Post http://127.0.0.1:8000/api/tts `
  -ContentType "application/json" `
  -Body '{"text":"नमस्ते! मैं आपकी किस प्रकार सहायता कर सकती हूँ?"}' `
  -OutFile response.wav

# Sarvam Saaraas STT (replace the path with a supported audio file)
curl.exe -X POST http://127.0.0.1:8000/api/transcribe `
  -F "audio=@C:\path\to\recording.webm"
```

No sample audio is included. Supported audio types are WebM, WAV, MP3, AAC, AIFF, OGG, OPUS, FLAC, MP4/M4A, AMR, and WMA; this backend limits uploads to 25 MB. Sarvam recommends 16 kHz audio; the browser-recorded WebM file is passed through as-is.

## Troubleshooting

- **503 / not configured:** add the relevant provider key to `backend\.env`, then restart FastAPI.
- **401/403:** verify that the backend key is valid and enabled for the requested service/model.
- **429 or 402:** provider rate limits or account quota/credits are exhausted; check provider usage and billing.
- **Unsupported audio / empty transcript:** upload a non-empty supported audio file and record a complete utterance.
- **Sarvam STT/TTS errors:** confirm the Sarvam key, Saaraas/Bulbul model access, and account quota. Provider failures are reported; the app does not return placeholder transcripts or audio.
- **Microphone unavailable:** use a current Chrome/Edge browser and grant microphone access to the local dashboard.
- **Frontend cannot reach backend:** ensure FastAPI is running on port 8000 and the dashboard is served from localhost port 3000 or 3001.

## Privacy and limitations

Audio and transcripts are sent to Groq and generated response text is sent to Sarvam for inference. Calls and transcripts are stored locally in SQLite. This demo is not connected to a telephone network, should not be exposed directly to the public internet, and should not be used for sensitive conversations.
