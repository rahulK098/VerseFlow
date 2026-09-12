from pathlib import Path

# Play resolution per output aspect (must match ffmpeg_runner._DIMENSIONS)
_PLAY_RES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1":  (1080, 1080),
}
# Bottom margin per aspect (distance of bottom-aligned captions from frame bottom)
_MARGIN_V: dict[str, int] = {"9:16": 640, "16:9": 120, "1:1": 200}

# ASS colors use &HAABBGGRR (alpha, blue, green, red).
# "effect" is an ASS override-tag prefix applied to every word line —
# \fad fades, \t(…\fscx\fscy) animates scale, \move slides position.
# __CX__/__Y0__/__Y1__ tokens are replaced with aspect-specific coordinates.
_TEMPLATES: dict[str, dict] = {
    "minimal": {
        "fontsize": 72,
        "primary":   "&H00FFFFFF",  # white
        "secondary": "&H00000000",
        "outline":   "&H00000000",  # black
        "back":      "&H80000000",  # semi-transparent shadow
        "bold": -1, "border": 1, "outline_size": 3, "shadow": 1,
        "alignment": 2,  # bottom-center
        "margin_v": 640,
        "karaoke": False,
        "effect": "{\\fad(80,80)}",
    },
    "bold": {
        "fontsize": 90,
        "primary":   "&H0000FFFF",  # yellow (R=255,G=255,B=0)
        "secondary": "&H00000000",
        "outline":   "&H00000000",  # black
        "back":      "&H80000000",
        "bold": -1, "border": 1, "outline_size": 5, "shadow": 1,
        "alignment": 2,
        "margin_v": 640,
        "karaoke": False,
        "effect": "{\\fad(60,60)\\t(0,100,\\fscx112\\fscy112)\\t(100,190,\\fscx100\\fscy100)}",
    },
    "karaoke": {
        "fontsize": 72,
        "primary":   "&H00FFFFFF",  # white (inactive words)
        "secondary": "&H0000FFFF",  # yellow (active word sweeps in)
        "outline":   "&H00000000",
        "back":      "&H80000000",
        "bold": -1, "border": 1, "outline_size": 3, "shadow": 1,
        "alignment": 2,
        "margin_v": 640,
        "karaoke": True,
        "effect": "",  # \k tags provide the animation
    },
    "neon": {
        "fontsize": 78,
        "primary":   "&H00FFFF00",  # cyan (R=0,G=255,B=255)
        "secondary": "&H00000000",
        "outline":   "&H00800080",  # purple
        "back":      "&H80000000",
        "bold": -1, "border": 1, "outline_size": 4, "shadow": 2,
        "alignment": 5,  # center-center
        "margin_v": 0,
        "karaoke": False,
        "effect": "{\\fad(140,140)\\t(0,220,\\fscx106\\fscy106)}",
    },
    "pop": {
        "fontsize": 84,
        "primary":   "&H00FFFFFF",  # white
        "secondary": "&H00000000",
        "outline":   "&H00CC6600",  # deep blue-purple
        "back":      "&H80000000",
        "bold": -1, "border": 1, "outline_size": 4, "shadow": 2,
        "alignment": 2,
        "margin_v": 640,
        "karaoke": False,
        # Bounce in: overshoot to 130 %, settle to 100 %
        "effect": "{\\fad(40,70)\\t(0,110,\\fscx130\\fscy130)\\t(110,210,\\fscx100\\fscy100)}",
    },
    "slide": {
        "fontsize": 76,
        "primary":   "&H00FFFFFF",  # white
        "secondary": "&H00000000",
        "outline":   "&H00000000",
        "back":      "&H80000000",
        "bold": -1, "border": 1, "outline_size": 3, "shadow": 1,
        "alignment": 2,
        "margin_v": 640,
        "karaoke": False,
        # Slide up 60 px while fading in (anchor: bottom-center)
        "effect": "{\\move(__CX__,__Y0__,__CX__,__Y1__,0,140)\\fad(110,110)}",
    },
}


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _build_word_lines(words: list[dict], effect: str = "") -> list[str]:
    lines = []
    for w in words:
        text = w.get("word", "").strip()
        if not text:
            continue
        start = _ts(w.get("start", 0.0))
        end = _ts(w.get("end", 0.0) + 0.05)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{effect}{text}")
    return lines


def _build_karaoke_lines(words: list[dict]) -> list[str]:
    """Group words into phrases and emit one ASS karaoke line per phrase.

    The \\k{N} tag sweeps the secondary colour (yellow) through each word
    over N centiseconds — timing comes from the word timestamps.
    """
    if not words:
        return []

    # Group: new group on > 0.4 s gap or > 5 words per group
    groups: list[list[dict]] = []
    current: list[dict] = []
    for w in words:
        if not w.get("word", "").strip():
            continue
        if current:
            gap = w.get("start", 0.0) - current[-1].get("end", 0.0)
            if gap > 0.4 or len(current) >= 5:
                groups.append(current)
                current = []
        current.append(w)
    if current:
        groups.append(current)

    lines = []
    for group in groups:
        if not group:
            continue
        group_start = _ts(group[0]["start"])
        group_end   = _ts(group[-1].get("end", group[-1]["start"]) + 0.1)
        parts = []
        for w in group:
            dur_cs = max(1, int(round((w.get("end", w["start"]) - w["start"]) * 100)))
            word = w.get("word", "").strip()
            if word:
                parts.append(f"{{\\k{dur_cs}}}{word}")
        if parts:
            lines.append(f"Dialogue: 0,{group_start},{group_end},Default,,0,0,0,," + " ".join(parts))
    return lines


def _escape_ass(text: str) -> str:
    # Strip characters that carry meaning inside ASS dialogue lines
    return text.replace("{", "").replace("}", "").replace("\n", " ").strip()


def build_ass_captions(
    words: list[dict],
    output_path: str,
    template: str = "minimal",
    aspect: str = "9:16",
    title: str | None = None,
) -> None:
    """Convert word-level timestamps to an ASS subtitle file.

    template: "minimal" | "bold" | "karaoke" | "neon" | "pop" | "slide"
    aspect:   "9:16" | "16:9" | "1:1"
    title:    optional hook text burned as a top title card for the first 3 s
    """
    tmpl = _TEMPLATES.get(template, _TEMPLATES["minimal"])
    res_w, res_h = _PLAY_RES.get(aspect, _PLAY_RES["9:16"])
    # Center-aligned templates (alignment 5) keep margin 0; bottom-aligned scale per aspect
    margin_v = 0 if tmpl["alignment"] == 5 else _MARGIN_V.get(aspect, 640)

    style = (
        f"Style: Default,Arial,{tmpl['fontsize']},"
        f"{tmpl['primary']},{tmpl['secondary']},{tmpl['outline']},{tmpl['back']},"
        f"{tmpl['bold']},0,0,0,100,100,0,0,"
        f"{tmpl['border']},{tmpl['outline_size']},{tmpl['shadow']},"
        f"{tmpl['alignment']},0,0,{margin_v},1"
    )
    # Title card style: top-center (alignment 8), slightly larger, always white/black
    title_size = int(tmpl["fontsize"] * 1.1)
    title_style = (
        f"Style: Title,Arial,{title_size},"
        f"&H00FFFFFF,&H00000000,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,"
        f"1,4,2,8,40,40,{int(res_h * 0.10)},1"
    )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {res_w}\n"
        f"PlayResY: {res_h}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style}\n"
        f"{title_style}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    # Resolve aspect-specific coordinates in animation effects (slide's \move)
    effect = tmpl.get("effect", "")
    if "__CX__" in effect:
        y_end = res_h - margin_v
        effect = (
            effect.replace("__CX__", str(res_w // 2))
                  .replace("__Y0__", str(y_end + 60))
                  .replace("__Y1__", str(y_end))
        )

    dialogue_lines = (
        _build_karaoke_lines(words)
        if tmpl["karaoke"]
        else _build_word_lines(words, effect)
    )

    # Hook title card: pops in on layer 1 for the first 3 seconds
    if title and _escape_ass(title):
        dialogue_lines.insert(0, (
            "Dialogue: 1,0:00:00.30,0:00:03.20,Title,,0,0,0,,"
            "{\\fad(250,400)\\t(0,150,\\fscx108\\fscy108)\\t(150,300,\\fscx100\\fscy100)}"
            + _escape_ass(title)
        ))

    Path(output_path).write_text(header + "\n".join(dialogue_lines), encoding="utf-8")
