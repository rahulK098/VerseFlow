def align(audio_path: str, transcript: dict) -> list[dict]:
    """Return word-level timestamps, best source available.

    Priority:
    1. WhisperX forced alignment (most accurate, optional dependency)
    2. faster-whisper's own word timestamps (already in the transcript — accurate)
    3. Even distribution within segments (last-resort stub)
    """
    try:
        import torch
        import whisperx
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_a, metadata = whisperx.load_align_model(language_code="en", device=device)
        result = whisperx.align(
            transcript.get("segments", []),
            model_a,
            metadata,
            audio_path,
            device,
            return_char_alignments=False,
        )
        words = []
        for seg in result.get("segments", []):
            for w in seg.get("words", []):
                words.append({
                    "word": w.get("word", ""),
                    "start": w.get("start", 0.0),
                    "end": w.get("end", 0.0),
                    "confidence": w.get("score", 1.0),
                })
        if words:
            return words
    except ImportError:
        pass

    # faster-whisper word timestamps (produced by transcribe() with word_timestamps=True)
    if transcript.get("words"):
        return transcript["words"]

    # Approximate: distribute words evenly within each segment
    words = []
    for seg in transcript.get("segments", []):
        seg_words = seg["text"].split()
        if not seg_words:
            continue
        duration = seg["end"] - seg["start"]
        wd = duration / max(len(seg_words), 1)
        for i, word in enumerate(seg_words):
            words.append({
                "word": word,
                "start": round(seg["start"] + i * wd, 3),
                "end": round(seg["start"] + (i + 1) * wd, 3),
                "confidence": 0.5,
            })
    return words
