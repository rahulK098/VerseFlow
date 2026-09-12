import os

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
# VAD is OFF by default: Silero VAD treats singing as non-speech and can strip
# most of a song (observed: 1:51 removed from a 2:45 track). Enable via
# WHISPER_VAD=1 for talking content (podcasts/interviews) to skip silence.
WHISPER_VAD = os.getenv("WHISPER_VAD", "0").lower() in ("1", "true", "yes")


def transcribe(audio_path: str) -> dict:
    """Transcribe audio with faster-whisper; falls back to a stub if not installed.

    Returns word-level timestamps (faster-whisper's cross-attention alignment) so
    captions sync without needing WhisperX.
    """
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type="int8")
        segments_iter, info = model.transcribe(
            audio_path,
            beam_size=5,
            word_timestamps=True,
            vad_filter=WHISPER_VAD,
            vad_parameters={"min_silence_duration_ms": 500} if WHISPER_VAD else None,
        )
        segments = []
        words = []
        text_parts = []
        for seg in segments_iter:
            segments.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
            text_parts.append(seg.text.strip())
            for w in seg.words or []:
                words.append({
                    "word": w.word.strip(),
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "confidence": round(w.probability, 3),
                })
        return {
            "text": " ".join(text_parts),
            "segments": segments,
            "words": words,
            "duration_sec": float(info.duration),
        }
    except ImportError:
        print("[transcribe] faster-whisper not installed — returning stub transcript")
        return {
            "text": "Stub lyrics — install faster-whisper for real transcription",
            "segments": [{"start": 0.0, "end": 5.0, "text": "Stub lyrics"}],
            "words": [],
            "duration_sec": 30.0,
        }
