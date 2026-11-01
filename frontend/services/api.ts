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

async function getErrorMessage(response: Response, fallback: string): Promise<string> {
  const body = await response.text();
  let detail = "";

  if (body) {
    try {
      const data: unknown = JSON.parse(body);
      if (typeof data === "object" && data !== null && "detail" in data) {
        const value = data.detail;
        detail = typeof value === "string" ? value : JSON.stringify(value);
      } else {
        detail = body;
      }
    } catch {
      detail = body;
    }
  }

  const status = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
  const excerpt = detail ? ` ${detail.slice(0, 300)}` : "";
  return `${fallback} (${status}).${excerpt}`;
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchApi(path, init);
  if (!response.ok) {
    throw new Error(await getErrorMessage(response, "The backend request failed."));
  }
  return response.json() as Promise<T>;
}

export async function transcribeAudio(callId: string, audio: Blob) {
  const formData = new FormData();
  formData.append("audio", audio, "caller-audio.webm");
  formData.append("call_id", callId);
  const response = await fetchApi("/api/transcribe", {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await getErrorMessage(response, "Could not transcribe the recording."));
  }
  const data = await response.json();
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
    throw new Error(await getErrorMessage(response, "Could not generate speech."));
  }
  return response.blob();
}
