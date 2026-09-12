def detect_beats(audio_path: str) -> dict:
    """Track beats with librosa. Returns {"tempo": bpm, "beats": [sec, ...]}.

    Beat times drive beat-synced clip cuts at render time. Empty result when
    librosa is unavailable or the track has no clear pulse — renders fall back
    to fixed-length cuts.
    """
    try:
        import librosa
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        times = librosa.frames_to_time(beat_frames, sr=sr)
        tempo_val = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
        return {
            "tempo": round(tempo_val, 1),
            "beats": [round(float(t), 3) for t in times],
        }
    except Exception as exc:
        print(f"[beats] beat detection unavailable: {exc}")
        return {"tempo": 0.0, "beats": []}
