SHORT_DURATION = 60.0  # YouTube Shorts max


def build_timeline(analysis: dict, input_file: str, render_type: str) -> dict:
    """
    Slice the song into per-render segments.

      lyric_video  — full song (0 → total_duration)
      short_1      — 0 → 60 s
      short_2      — 60 → 120 s
      short_3      — 120 → 180 s

    Words are filtered to the segment window and their timestamps are shifted
    to 0-relative so the ASS captions align with the trimmed audio.
    Segments that fall entirely outside the song duration have total_duration=0
    and should be skipped by the caller.
    """
    total_duration = analysis.get("duration_sec", 30.0)

    if render_type == "lyric_video":
        start_sec = 0.0
        end_sec = total_duration
    else:
        # short_1 → idx 0, short_2 → idx 1, short_3 → idx 2
        idx = int(render_type[-1]) - 1
        start_sec = SHORT_DURATION * idx
        end_sec = min(start_sec + SHORT_DURATION, total_duration)

    segment_duration = max(0.0, round(end_sec - start_sec, 3))

    # Keep only words that start inside this segment; shift timestamps to 0-relative.
    all_words = analysis.get("words", [])
    segment_words = [
        {
            **w,
            "start": round(w["start"] - start_sec, 3),
            "end":   round(w["end"]   - start_sec, 3),
        }
        for w in all_words
        if start_sec <= w.get("start", 0.0) < end_sec
    ]

    return {
        "job_id":          analysis.get("job_id", ""),
        "type":            render_type,
        "audio_file":      input_file,
        "audio_start_sec": start_sec,       # where to seek in the source audio
        "total_duration":  segment_duration, # length of this clip
        "clips":           [],
        "captions":        segment_words,   # pre-filtered, 0-relative timestamps
    }
