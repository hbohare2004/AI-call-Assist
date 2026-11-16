"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { chatMessage, generateSpeech, requestJson, transcribeAudio } from "../services/api";

type Status = "Ready" | "Listening" | "Processing" | "AI Speaking" | "Completed" | "Error";
type CallItem = {
  id: string;
  started_at: string;
  ended_at: string | null;
  summary: string | null;
  status: string;
  caller_name: string | null;
};

const SPEECH_RMS_THRESHOLD = 0.012;
const SILENCE_RMS_THRESHOLD = 0.008;
const MIN_SPEECH_DURATION_MS = 250;
const END_OF_SPEECH_SILENCE_MS = 600;
const INITIAL_GREETING = "नमस्ते! मैं हर्ष की एआई सहायक हूँ। हर्ष अभी उपलब्ध नहीं हैं। बताइए, आपको क्या काम था?";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}

export default function Home() {
  const [callId, setCallId] = useState<string | null>(null);
  const [calls, setCalls] = useState<CallItem[]>([]);
  const [status, setStatus] = useState<Status>("Ready");
  const [busy, setBusy] = useState(false);
  const [isStartingCall, setIsStartingCall] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isAiSpeaking, setIsAiSpeaking] = useState(false);
  const [error, setError] = useState("");
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [deletingCallId, setDeletingCallId] = useState<string | null>(null);
  const [isDeletingAllCalls, setIsDeletingAllCalls] = useState(false);

  const callIdRef = useRef<string | null>(null);
  const isCallActiveRef = useRef(false);
  const isEndingCallRef = useRef(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const microphoneStreamRef = useRef<MediaStream | null>(null);
  const microphoneAnalyserRef = useRef<AnalyserNode | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const vadFrameRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const activeTurnPromiseRef = useRef<Promise<void>>(Promise.resolve());
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef("");
  const greetingAudioRef = useRef<{ text: string; promise: Promise<Blob> } | null>(null);

  const refreshCalls = useCallback(async () => {
    try {
      const data = await requestJson<{ calls: CallItem[] }>("/api/calls");
      setCalls(data.calls);
    } catch (requestError) {
      setError(errorText(requestError));
      setStatus("Error");
    }
  }, []);

  useEffect(() => {
    const audioElement = audioRef.current;
    void refreshCalls();
    if (!greetingAudioRef.current) {
      const greetingPromise = generateSpeech(INITIAL_GREETING);
      greetingAudioRef.current = { text: INITIAL_GREETING, promise: greetingPromise };
      void greetingPromise.catch(() => {
        if (greetingAudioRef.current?.promise === greetingPromise) {
          greetingAudioRef.current = null;
        }
      });
    }
    return () => {
      isCallActiveRef.current = false;
      const recorder = recorderRef.current;
      if (vadFrameRef.current !== null) {
        window.cancelAnimationFrame(vadFrameRef.current);
      }
      if (audioContextRef.current && audioContextRef.current.state !== "closed") {
        void audioContextRef.current.close();
      }
      microphoneStreamRef.current?.getTracks().forEach((track) => track.stop());
      if (recorder) {
        recorder.onstop = null;
        if (recorder.state === "recording") recorder.stop();
      }
      audioElement?.pause();
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    };
  }, [refreshCalls]);

  useEffect(() => {
    if (!isHistoryOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setIsHistoryOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isHistoryOpen]);

  async function playSpeech(text: string, preparedAudio?: Blob) {
    const blob = preparedAudio ?? await generateSpeech(text);
    if (!blob.size) throw new Error("The speech service returned empty audio.");
    const nextUrl = URL.createObjectURL(blob);
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    audioUrlRef.current = nextUrl;

    const audio = audioRef.current;
    if (!audio) throw new Error("Audio playback is not available in this browser.");
    audio.src = nextUrl;
    setIsAiSpeaking(true);
    setStatus("AI Speaking");

    await new Promise<void>((resolve, reject) => {
      const finish = () => {
        audio.onended = null;
        audio.onpause = null;
        audio.onerror = null;
        setIsAiSpeaking(false);
        resolve();
      };
      audio.onended = finish;
      audio.onpause = finish;
      audio.onerror = () => {
        audio.onended = null;
        audio.onpause = null;
        audio.onerror = null;
        setIsAiSpeaking(false);
        reject(new Error("The generated audio could not be played."));
      };
      audio.play().catch((playError: unknown) => {
        audio.onended = null;
        audio.onpause = null;
        audio.onerror = null;
        setIsAiSpeaking(false);
        reject(playError);
      });
    });
  }

  async function sendTranscript(transcript: string, activeId: string) {
    const cleaned = transcript.trim();
    if (!cleaned) return;
    setError("");
    setBusy(true);
    setStatus("Processing");

    try {
      const data = await chatMessage(activeId, cleaned);
      await playSpeech(data.response);
    } catch (requestError) {
      setError(errorText(requestError));
      setStatus("Error");
    } finally {
      if (
        isCallActiveRef.current
        && !isEndingCallRef.current
        && callIdRef.current === activeId
      ) {
        await startRecording();
      }
      setBusy(false);
    }
  }

  async function processAudio(blob: Blob, activeId: string | null) {
    if (!activeId || !blob.size) {
      setError("The recording was empty. Please record a complete utterance and try again.");
      setStatus("Error");
      return;
    }

    setBusy(true);
    setError("");
    setStatus("Processing");
    try {
      const data = await transcribeAudio(activeId, blob);
      const transcript = data.transcript.trim();
      if (!transcript) throw new Error("No speech was detected. Please try recording again.");
      await sendTranscript(transcript, activeId);
    } catch (requestError) {
      setError(errorText(requestError));
      setStatus("Error");
      setBusy(false);
      if (
        isCallActiveRef.current
        && !isEndingCallRef.current
        && callIdRef.current === activeId
      ) {
        await startRecording();
      }
    }
  }

  async function prepareMicrophone() {
    if (microphoneStreamRef.current && microphoneAnalyserRef.current) return;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        autoGainControl: true,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    let audioContext: AudioContext | null = null;
    try {
      audioContext = new AudioContext();
      await audioContext.resume();
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      microphoneStreamRef.current = stream;
      microphoneAnalyserRef.current = analyser;
      audioContextRef.current = audioContext;
    } catch (error) {
      stream.getTracks().forEach((track) => track.stop());
      if (audioContext && audioContext.state !== "closed") await audioContext.close();
      throw error;
    }
  }

  function releaseMicrophone() {
    microphoneStreamRef.current?.getTracks().forEach((track) => track.stop());
    microphoneStreamRef.current = null;
    microphoneAnalyserRef.current = null;
    const audioContext = audioContextRef.current;
    audioContextRef.current = null;
    if (audioContext && audioContext.state !== "closed") {
      void audioContext.close();
    }
  }

  async function startRecording() {
    if (!isCallActiveRef.current || recorderRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser does not support microphone recording. Use a recent Chrome or Edge release.");
      setStatus("Error");
      return;
    }

    try {
      await prepareMicrophone();
      const stream = microphoneStreamRef.current;
      const analyser = microphoneAnalyserRef.current;
      if (!stream || !analyser) {
        throw new Error("Microphone could not be prepared for recording.");
      }
      const recorder = new MediaRecorder(stream);
      const samples = new Float32Array(analyser.fftSize);
      recordingChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) recordingChunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setError("The microphone recording failed. Check browser microphone permissions and try again.");
        setStatus("Error");
      };
      recorder.onstop = () => {
        if (vadFrameRef.current !== null) {
          window.cancelAnimationFrame(vadFrameRef.current);
          vadFrameRef.current = null;
        }
        const contentType = recorder.mimeType || "audio/webm";
        const blob = new Blob(recordingChunksRef.current, { type: contentType });
        recordingChunksRef.current = [];
        recorderRef.current = null;
        setIsRecording(false);
        if (blob.size && isCallActiveRef.current) {
          activeTurnPromiseRef.current = processAudio(blob, callIdRef.current);
        } else if (isCallActiveRef.current) {
          setError("No audio was recorded. Please try again.");
          setStatus("Error");
        }
      };
      recorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
      setStatus("Listening");

      let speechDuration = 0;
      let speechDetected = false;
      let silenceStartedAt: number | null = null;
      let previousFrameAt = performance.now();
      const monitorSpeech = (now: number) => {
        if (recorder.state !== "recording") return;
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
        const frameDuration = Math.min(now - previousFrameAt, 100);
        previousFrameAt = now;

        if (rms >= SPEECH_RMS_THRESHOLD) {
          speechDuration += frameDuration;
          if (speechDuration >= MIN_SPEECH_DURATION_MS) speechDetected = true;
          silenceStartedAt = null;
        } else if (speechDetected && rms < SILENCE_RMS_THRESHOLD) {
          silenceStartedAt ??= now;
          if (now - silenceStartedAt >= END_OF_SPEECH_SILENCE_MS) {
            recorder.stop();
            return;
          }
        } else {
          if (!speechDetected) speechDuration = 0;
          silenceStartedAt = null;
        }

        vadFrameRef.current = window.requestAnimationFrame(monitorSpeech);
      };
      vadFrameRef.current = window.requestAnimationFrame(monitorSpeech);
    } catch (recordingError) {
      setError(
        recordingError instanceof DOMException && recordingError.name === "NotAllowedError"
          ? "Microphone permission was denied. Allow microphone access in your browser and try again."
          : errorText(recordingError),
      );
      setStatus("Error");
    }
  }

  async function stopRecording() {
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") {
      await new Promise<void>((resolve) => {
        recorder.addEventListener("stop", () => resolve(), { once: true });
        recorder.stop();
      });
    }
    await activeTurnPromiseRef.current;
  }

  async function startConversation() {
    isEndingCallRef.current = false;
    setIsStartingCall(true);
    setBusy(true);
    setError("");
    setIsHistoryOpen(false);
    setStatus("Processing");
    try {
      const data = await requestJson<{ call_id: string; greeting: string }>("/api/calls", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      callIdRef.current = data.call_id;
      isCallActiveRef.current = true;
      setCallId(data.call_id);
      const greetingAudioPromise = greetingAudioRef.current?.text === data.greeting
        ? greetingAudioRef.current.promise.catch(() => generateSpeech(data.greeting))
        : generateSpeech(data.greeting);
      const [, greetingAudio] = await Promise.all([prepareMicrophone(), greetingAudioPromise]);

      try {
        await playSpeech(data.greeting, greetingAudio);
      } catch (speechError) {
        setError(errorText(speechError));
      }
      void refreshCalls();
      await startRecording();
    } catch (requestError) {
      setError(errorText(requestError));
      setStatus("Error");
    } finally {
      setIsStartingCall(false);
      setBusy(false);
    }
  }

  async function endConversation() {
    const activeId = callIdRef.current;
    if (!activeId || isEndingCallRef.current) return;
    isEndingCallRef.current = true;
    isCallActiveRef.current = false;
    audioRef.current?.pause();
    setBusy(true);
    setStatus("Processing");
    try {
      if (recorderRef.current?.state === "recording") {
        await stopRecording();
      } else {
        await activeTurnPromiseRef.current;
      }
      isCallActiveRef.current = false;
      releaseMicrophone();
      await requestJson<Record<string, unknown>>(`/api/calls/${activeId}/end`, {
        method: "POST",
      });
      setCallId(null);
      callIdRef.current = null;
      setStatus("Completed");
      await refreshCalls();
    } catch (requestError) {
      setError(errorText(requestError));
      setStatus("Error");
    } finally {
      isEndingCallRef.current = false;
      setBusy(false);
    }
  }

  async function deleteHistory(id: string) {
    if (!window.confirm("Delete this call from history? This cannot be undone.")) return;
    setDeletingCallId(id);
    try {
      await requestJson(`/api/calls/${id}`, { method: "DELETE" });
      setCalls((existing) => existing.filter((call) => call.id !== id));
    } catch (requestError) {
      setError(errorText(requestError));
      setStatus("Error");
    } finally {
      setDeletingCallId(null);
    }
  }

  async function deleteAllHistory() {
    if (
      !calls.length
      || callIdRef.current
      || deletingCallId
      || isDeletingAllCalls
      || !window.confirm("Delete all saved call history? This cannot be undone.")
    ) {
      return;
    }
    setIsDeletingAllCalls(true);
    try {
      await requestJson<{ deleted: boolean }>("/api/calls", { method: "DELETE" });
      setCalls([]);
      setError("");
    } catch (requestError) {
      setError(errorText(requestError));
      setStatus("Error");
    } finally {
      setIsDeletingAllCalls(false);
    }
  }

  return (
    <main className="app-shell min-h-screen px-4 py-8 sm:px-8">
      <div className="app-container mx-auto max-w-6xl">
        <header className="app-header mb-8 flex flex-col justify-between gap-5 sm:flex-row sm:items-center">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <span className={`h-2.5 w-2.5 rounded-full ${callId ? "bg-emerald-400 animate-pulse" : "bg-slate-500"}`} />
              <span className="pill">GROQ · SARVAM AI · SQLITE</span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">AI Call Assistant</h1>
            <p className="muted mt-2">A personal AI receptionist for calls you can’t answer.</p>
          </div>
          <div className="flex flex-col gap-3 sm:items-end">
            <button
              type="button"
              onClick={() => {
                void refreshCalls();
                setIsHistoryOpen(true);
              }}
              className="history-trigger"
              aria-haspopup="dialog"
              aria-expanded={isHistoryOpen}
            >
              Call history <span className="history-count">{calls.length}</span>
            </button>
          </div>
        </header>

        {error && (
          <div role="alert" className="mb-5 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
            {error}
          </div>
        )}

        <section className="call-console panel" aria-label="AI call assistant">
          <div
            className={`assistant-orb ${isAiSpeaking ? "is-speaking" : ""} ${callId && isRecording ? "is-listening" : ""}`}
            role="img"
            aria-label={isAiSpeaking ? "AI assistant is speaking" : "AI assistant"}
          >
            <div className="assistant-orb-core" />
          </div>
          <button
            type="button"
            onClick={() => void (callId ? endConversation() : startConversation())}
            disabled={isStartingCall}
            className={`conversation-toggle ${callId ? "is-active" : ""}`}
          >
            {callId ? "Stop conversation" : isStartingCall ? "Starting…" : "Start conversation"}
          </button>
          <p className="call-status" aria-live="polite">
            {isStartingCall ? "Starting conversation…" : status}
          </p>
          <audio ref={audioRef} className="sr-only" aria-hidden="true" />
        </section>

        {isHistoryOpen && (
          <div
            className="history-backdrop"
            onClick={() => setIsHistoryOpen(false)}
          >
            <section
              className="history-dialog panel"
              role="dialog"
              aria-modal="true"
              aria-labelledby="history-title"
              onClick={(event) => event.stopPropagation()}
            >
              <header className="history-dialog-header">
                <div>
                  <h2 id="history-title">Call history</h2>
                  <p className="muted">{calls.length} recent conversations</p>
                </div>
                <div className="history-dialog-actions">
                  <button
                    type="button"
                    onClick={() => void deleteAllHistory()}
                    disabled={!calls.length || !!callId || busy || !!deletingCallId || isDeletingAllCalls}
                    className="delete-all-action"
                  >
                    {isDeletingAllCalls ? "Deleting…" : "Delete all"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void refreshCalls()}
                    className="refresh-action rounded-lg border border-slate-700 px-3 py-2 text-sm"
                  >
                    Refresh
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsHistoryOpen(false)}
                    className="history-close"
                    aria-label="Close call history"
                  >
                    ×
                  </button>
                </div>
              </header>
              <div className="history-list">
                {calls.length === 0 ? (
                  <p className="muted rounded-xl border border-dashed border-slate-700 p-5 text-center text-sm">
                    Saved conversations will appear here.
                  </p>
                ) : (
                  calls.map((call) => (
                    <article key={call.id} className="history-item">
                      <div className="history-details">
                        <span className="history-item-meta">
                          <span className="text-sm font-semibold">
                            {call.caller_name && call.caller_name !== "Not provided" ? call.caller_name : "Caller"}
                          </span>
                          <span className="pill">{call.status}</span>
                        </span>
                        <span className="muted text-xs">{new Date(call.started_at).toLocaleString()}</span>
                        <span className="muted text-sm">{call.summary || "Summary not available yet."}</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => void deleteHistory(call.id)}
                        disabled={deletingCallId === call.id || call.id === callId || isDeletingAllCalls}
                        className="history-delete"
                      >
                        {deletingCallId === call.id ? "Deleting…" : "Delete"}
                      </button>
                    </article>
                  ))
                )}
              </div>
            </section>
          </div>
        )}

        <footer className="muted mt-7 text-center text-xs">
          Browser voice demo · Audio is sent to Groq and response text to Sarvam AI · No phone-network integration
        </footer>
      </div>
    </main>
  );
}
