"""Smoke test: generate an ASS file for every template and print dialogue lines."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipeline.captions import _TEMPLATES, build_ass_captions

words = [
    {"word": "Hello", "start": 0.0, "end": 0.4},
    {"word": "world", "start": 0.45, "end": 0.9},
    {"word": "again", "start": 1.5, "end": 2.0},
]

for aspect in ("9:16", "16:9", "1:1"):
    for t in _TEMPLATES:
        p = Path(tempfile.gettempdir()) / f"test_{t}_{aspect.replace(':', 'x')}.ass"
        build_ass_captions(words, str(p), template=t, aspect=aspect)
        content = p.read_text(encoding="utf-8")
        dialogue = [line for line in content.splitlines() if line.startswith("Dialogue")]
        assert dialogue, f"{t}/{aspect}: no dialogue lines"
        assert "[V4+ Styles]" in content, f"{t}/{aspect}: missing styles section"
        assert "__CX__" not in content, f"{t}/{aspect}: unresolved coordinate token"
        if aspect == "16:9":
            assert "PlayResX: 1920" in content, f"{t}/{aspect}: wrong PlayRes"
    print(f"OK aspect {aspect}: {len(_TEMPLATES)} templates")

print("OK: all templates x aspects generated")
