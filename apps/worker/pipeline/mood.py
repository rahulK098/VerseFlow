import json
import re

_PROMPT = """Analyze this song transcript and return ONLY a JSON object with exactly these keys:
- "genre": string (e.g. "pop", "rap", "rock", "r&b", "electronic")
- "mood": string (e.g. "uplifting", "melancholic", "energetic", "romantic", "chill")
- "energy": integer 1-10
- "keywords": list of 5 strings (visual/thematic for finding stock footage)

Transcript:
{transcript}

Return only valid JSON. No explanation."""


def detect_mood(transcript: str) -> dict:
    try:
        # Shared provider chain: LLM_PROVIDER env (ollama | openrouter | deepseek | anthropic)
        from pipeline.highlights import _ask_llm
        raw = _ask_llm(_PROMPT.format(transcript=transcript[:2000]))
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as exc:
        print(f"[mood] LLM unavailable: {exc} — using stub mood")

    return {
        "genre": "pop",
        "mood": "uplifting",
        "energy": 7,
        "keywords": ["music", "rhythm", "city lights", "motion", "energy"],
    }


def keywords_to_queries(mood: dict) -> list[str]:
    keywords = mood.get("keywords", [])
    genre = mood.get("genre", "music")
    mood_str = mood.get("mood", "")
    queries = list(keywords[:3]) if keywords else [genre]
    if mood_str:
        queries.append(f"{mood_str} {genre}")
    return queries
