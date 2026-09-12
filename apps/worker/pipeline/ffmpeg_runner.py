import math
import shutil
import subprocess
import tempfile
from pathlib import Path

# Output dimensions per aspect ratio
_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1":  (1080, 1080),
}


def _dims(aspect: str) -> tuple[int, int]:
    return _DIMENSIONS.get(aspect, _DIMENSIONS["9:16"])


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _audio_trim_filter(audio_start: float, duration: float) -> str:
    # Decode-side trim: sample-accurate even on VBR MP3s, where input-side
    # -ss byte-estimates the seek point and can land up to ~1 s off,
    # desyncing captions from the audio.
    return f"atrim=start={audio_start}:duration={duration},asetpts=PTS-STARTPTS"


def _prepare_clip(clip_path: str, each_dur: float, tmp_dir: str, idx: int, w: int, h: int) -> str | None:
    """Crop/scale any source video to w×h and cut to exactly each_dur seconds.

    -stream_loop repeats sources shorter than their slot so every prepared clip
    fills its full duration; fps/SAR are normalized because the concat demuxer
    needs identical stream parameters — mixed frame rates cause frozen frames.
    """
    out = str(Path(tmp_dir) / f"clip_{idx:04d}.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", clip_path,
        # Scale to fill, then center-crop to exact size — handles any AR
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=30,setsar=1",
        "-t", str(each_dur),
        "-c:v", "libx264", "-preset", "fast", "-crf", "28",
        "-an",
        out,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"[ffmpeg_runner] clip prep failed ({clip_path[-40:]}): {result.stderr[-300:]}")
        return None
    return out


def _render_black_bg(
    duration: float,
    audio_start: float,
    audio_file: str,
    ass_escaped: str,
    output_path: str,
    w: int,
    h: int,
) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d={duration}",
        "-i", audio_file,
        "-vf", f"ass={ass_escaped},scale={w}:{h}",
        "-af", _audio_trim_filter(audio_start, duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg (black bg) failed:\n{result.stderr[-800:]}")


def _visualizer_filter(style: str, w: int, h: int) -> str:
    """Audio-reactive background filters — pure FFmpeg, no extra dependencies."""
    if style == "waves":
        return (
            f"showwaves=s={w}x{h}:mode=cline:rate=25:colors=0x8B5CF6|0xEC4899,"
            f"format=yuv420p"
        )
    if style == "scope":
        return (
            f"avectorscope=s={w}x{h}:rate=25:draw=line:scale=cbrt,"
            f"format=yuv420p"
        )
    # default: spectrum
    return (
        f"showspectrum=s={w}x{h}:mode=combined:color=fiery:scale=cbrt:slide=scroll:fps=25,"
        f"format=yuv420p"
    )


def _render_visualizer_bg(
    duration: float,
    audio_start: float,
    audio_file: str,
    ass_escaped: str,
    output_path: str,
    w: int,
    h: int,
    style: str = "visualizer",
) -> None:
    filter_complex = (
        f"[0:a]{_audio_trim_filter(audio_start, duration)},asplit=2[a1][a2];"
        f"[a1]{_visualizer_filter(style, w, h)}[bg];"
        f"[bg]ass={ass_escaped}[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", audio_file,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a2]",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"[ffmpeg_runner] visualizer failed — falling back to black bg:\n{result.stderr[-400:]}")
        _render_black_bg(duration, audio_start, audio_file, ass_escaped, output_path, w, h)


def _render_from_source(
    source_video: str,
    duration: float,
    audio_start: float,
    ass_escaped: str,
    output_path: str,
    w: int,
    h: int,
) -> None:
    """Cut the clip straight from the uploaded video: crop to aspect, burn captions.

    Coarse input seek 2 s early keeps long videos fast; the decode-side
    trim/atrim pair stays frame/sample-accurate.
    """
    coarse = max(0.0, audio_start - 2.0)
    fine = audio_start - coarse
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(coarse), "-i", source_video,
        "-vf", (
            f"trim=start={fine}:duration={duration},setpts=PTS-STARTPTS,"
            f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"ass={ass_escaped}"
        ),
        "-af", _audio_trim_filter(fine, duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg (source video) failed:\n{result.stderr[-800:]}")


def _beat_cut_durations(
    duration: float,
    beats: list[float],
    target: float = 6.0,
    min_len: float = 2.5,
) -> list[float]:
    """Split the render into clip slots that end on musical beats.

    Aims for ~target-second slots but snaps each boundary to the nearest beat,
    so background cuts land on the music. Falls back to fixed slots without beats.
    """
    if not beats:
        n = max(1, math.ceil(duration / 8.0))
        return [round(duration / n, 3)] * n

    cuts = [0.0]
    while duration - cuts[-1] > target + min_len:
        want = cuts[-1] + target
        window = [b for b in beats if cuts[-1] + min_len <= b <= want + (target - min_len)]
        nxt = min(window, key=lambda b: abs(b - want)) if window else want
        cuts.append(round(nxt, 3))
    durs = [round(b - a, 3) for a, b in zip(cuts, cuts[1:])]
    durs.append(round(duration - cuts[-1], 3))
    return [d for d in durs if d > 0.05]


def _render_with_clips(
    stock_clips: list[str],
    duration: float,
    audio_start: float,
    audio_file: str,
    ass_escaped: str,
    output_path: str,
    w: int,
    h: int,
    beat_times: list[float] | None = None,
) -> None:
    """Concat stock clips as background (cut on beats when known), burn captions."""
    slot_durs = _beat_cut_durations(duration, beat_times or [])

    with tempfile.TemporaryDirectory() as tmp:
        # Loop through available clips to fill the required slots
        looped = [stock_clips[i % len(stock_clips)] for i in range(len(slot_durs))]

        prepared: list[str] = []
        for i, (src, slot_dur) in enumerate(zip(looped, slot_durs)):
            out = _prepare_clip(src, slot_dur, tmp, i, w, h)
            if out:
                prepared.append(out)

        if not prepared:
            print("[ffmpeg_runner] all clip preps failed — falling back to black background")
            _render_black_bg(duration, audio_start, audio_file, ass_escaped, output_path, w, h)
            return

        # Write FFmpeg concat demuxer list (POSIX paths, single-quote escaped)
        concat_txt = Path(tmp) / "concat.txt"
        lines = [f"file '{p.replace(chr(92), '/').replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
                 for p in prepared]
        concat_txt.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            "ffmpeg", "-y",
            # Stock clip track (pre-processed to target aspect, trimmed)
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-i", audio_file,
            # tpad clone-holds the last frame if the concat track comes up short,
            # BEFORE captions are burned — so captions always cover the full render
            "-vf", (
                f"tpad=stop_mode=clone:stop_duration={duration},"
                f"ass={ass_escaped},scale={w}:{h}"
            ),
            "-af", _audio_trim_filter(audio_start, duration),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "26",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[ffmpeg_runner] stock clip render failed — falling back to black bg:\n{result.stderr[-400:]}")
            _render_black_bg(duration, audio_start, audio_file, ass_escaped, output_path, w, h)


def render_video(
    timeline: dict,
    ass_path: str,
    output_path: str,
    stock_clips: list[str] | None = None,
    background: str = "stock",
    aspect: str = "9:16",
    source_video: str | None = None,
) -> None:
    """Render an MP4 with captions synced to a trimmed audio segment.

    background: "stock" (clips) | "blank" (black) | "visualizer" (spectrum) | "source" (uploaded video)
    aspect: "9:16" | "16:9" | "1:1"
    """
    audio_file  = timeline.get("audio_file", "")
    duration    = timeline.get("total_duration", 30.0)
    audio_start = timeline.get("audio_start_sec", 0.0)
    beat_times  = timeline.get("beat_times", [])
    w, h = _dims(aspect)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if not _ffmpeg_available():
        Path(output_path).write_bytes(b"\x00" * 128)
        print("[ffmpeg_runner] FFmpeg not found — created stub")
        return

    ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")

    if background == "source" and source_video and Path(source_video).exists():
        _render_from_source(source_video, duration, audio_start, ass_escaped, output_path, w, h)
    elif background in ("visualizer", "waves", "scope"):
        _render_visualizer_bg(duration, audio_start, audio_file, ass_escaped, output_path, w, h, style=background)
    elif background != "blank" and stock_clips:
        _render_with_clips(
            stock_clips, duration, audio_start, audio_file, ass_escaped, output_path, w, h,
            beat_times=beat_times,
        )
    else:
        _render_black_bg(duration, audio_start, audio_file, ass_escaped, output_path, w, h)
