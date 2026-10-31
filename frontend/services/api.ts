const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

async function fetchApi(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API}${path}`, init);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        `Cannot reach the backend at ${API}. Check that FastAPI is running and allows this dashboard's origin.`,
      );
    }
    throw error;
  }
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchApi(path, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "The backend request failed.";
    throw new Error(detail);
  }
  return data as T;
}

export async function transcribeAudio(callId: string, audio: Blob) {
  const formData = new FormData();
  formData.append("audio", audio, "caller-audio.webm");
  formData.append("call_id", callId);
  const response = await fetchApi("/api/transcribe", {
    method: "POST",
    body: formData,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "Could not transcribe the recording.";
    throw new Error(detail);
  }
  if (typeof data.transcript !== "string") {
    throw new Error("The transcription service returned an invalid response.");
  }
  return {
    transcript: data.transcript,
    created_at: typeof data.created_at === "string" ? data.created_at : undefined,
  };
}

export async function chatMessage(callId: string, message: string): Promise<{ response: string }> {
  return requestJson<{ response: string }>("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, call_id: callId }),
  });
}

export async function generateSpeech(text: string): Promise<Blob> {
  const response = await fetchApi("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? data.detail : "Could not generate speech.";
    throw new Error(detail);
  }
  return response.blob();
}
