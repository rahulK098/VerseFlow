import json
import os
import re

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
# Primary provider; every other provider with a key set becomes a fallback,
# then local Ollama, then the caller's heuristic.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # ollama | azure | openrouter | groq | gemini | deepseek | anthropic
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
# :free variants run on a $0 balance (rate-limited). Paid variants need credits (402 otherwise).
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_KEY2 = os.getenv("AZURE_OPENAI_KEY2", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "chat")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

_PROMPT = """You are a short-form video editor picking the most engaging moments from a transcript.

Transcript with [mm:ss] timestamps:
{transcript}

Total duration: {duration:.0f} seconds.

Pick the 3 to 6 BEST moments for viral short clips. Rules:
- Each moment must be 15-60 seconds long
- Prefer hooks, strong emotions, surprising statements, punchlines, key insights
- Moments must not overlap

Return ONLY a JSON array, each item exactly:
{{"start_sec": <number>, "end_sec": <number>, "score": <0-100>, "hook": "<one punchy line to title this clip>", "reason": "<why this moment works>"}}

No explanation, JSON only."""


def _fmt_transcript(segments: list[dict], max_chars: int = 6000) -> str:
    lines = []
    for seg in segments:
        m, s = divmod(int(seg.get("start", 0)), 60)
        lines.append(f"[{m:02d}:{s:02d}] {seg.get('text', '').strip()}")
    text = "\n".join(lines)
    return text[:max_chars]


def _extract_json_array(raw: str) -> list[dict] | None:
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def _ask_ollama(prompt: str) -> str:
    import requests
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=120,  # local models on CPU can be slow, especially thinking models
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def _ask_openrouter(prompt: str) -> str:
    import requests
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://github.com/verseflow",
            "X-Title": "VerseFlow",
        },
        json={
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _ask_groq(prompt: str) -> str:
    import requests
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _ask_gemini(prompt: str) -> str:
    import requests
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _ask_azure(prompt: str) -> str:
    import requests
    url = (
        f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT}"
        f"/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
    )
    last_exc: Exception = RuntimeError("no Azure key configured")
    for key in (AZURE_OPENAI_KEY, AZURE_OPENAI_KEY2):
        if not key:
            continue
        try:
            resp = requests.post(
                url,
                headers={"api-key": key},
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            last_exc = exc  # key rotation: try the secondary key
    raise last_exc


def _ask_deepseek(prompt: str) -> str:
    import requests
    resp = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _ask_anthropic(prompt: str) -> str:
    import requests
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": "claude-haiku-4-5",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


# name -> (ask function, api key). A provider joins the chain only when its key is set.
_CLOUD_PROVIDERS: dict = {
    "azure":      (_ask_azure,      lambda: AZURE_OPENAI_KEY or AZURE_OPENAI_KEY2),
    "openrouter": (_ask_openrouter, lambda: OPENROUTER_API_KEY),
    "groq":       (_ask_groq,       lambda: GROQ_API_KEY),
    "gemini":     (_ask_gemini,     lambda: GEMINI_API_KEY),
    "deepseek":   (_ask_deepseek,   lambda: DEEPSEEK_API_KEY),
    "anthropic":  (_ask_anthropic,  lambda: ANTHROPIC_API_KEY),
}


def _ask_llm(prompt: str) -> str:
    """Walk the provider chain: primary first, then every other cloud provider
    with a key configured, then local Ollama. Caller handles the final fallback."""
    order = [LLM_PROVIDER] + [p for p in _CLOUD_PROVIDERS if p != LLM_PROVIDER]
    for name in order:
        entry = _CLOUD_PROVIDERS.get(name)
        if not entry or not entry[1]():
            continue
        try:
            return entry[0](prompt)
        except Exception as exc:
            print(f"[llm] {name} failed ({exc}) — trying next provider")
    return _ask_ollama(prompt)


def _heuristic_highlights(segments: list[dict], duration: float) -> list[dict]:
    """No-LLM fallback: rank 30 s windows by speech density (words/sec)."""
    if duration <= 0 or not segments:
        return []
    window = 30.0
    step = 15.0
    scored: list[tuple[float, float]] = []  # (density, window_start)
    t = 0.0
    while t + window <= duration + step:
        end = min(t + window, duration)
        words = sum(
            len(seg.get("text", "").split())
            for seg in segments
            if seg.get("start", 0) < end and seg.get("end", 0) > t
        )
        span = max(end - t, 1.0)
        scored.append((words / span, t))
        t += step
    scored.sort(reverse=True)

    highlights = []
    used: list[tuple[float, float]] = []
    for density, start in scored:
        end = min(start + window, duration)
        if any(start < ue and end > us for us, ue in used):
            continue
        used.append((start, end))
        highlights.append({
            "start_sec": round(start, 1),
            "end_sec": round(end, 1),
            "score": min(95, int(density * 25)),
            "hook": "High-energy moment",
            "reason": "Densest speech section (heuristic — no LLM available)",
        })
        if len(highlights) >= 3:
            break
    return highlights


def _snap_to_segments(h: dict, segments: list[dict]) -> dict:
    """Snap start/end to the nearest segment boundary so clips don't cut mid-word."""
    if not segments:
        return h
    starts = [s.get("start", 0.0) for s in segments]
    ends = [s.get("end", 0.0) for s in segments]
    h["start_sec"] = min(starts, key=lambda x: abs(x - h["start_sec"]))
    h["end_sec"] = min(ends, key=lambda x: abs(x - h["end_sec"]))
    return h


def detect_highlights(segments: list[dict], duration: float) -> list[dict]:
    """Find the most engaging moments in a transcript for short clips.

    Provider chain: LLM_PROVIDER env (ollama default, deepseek/anthropic optional)
    → word-density heuristic when no LLM is reachable.
    """
    raw_items: list[dict] | None = None
    try:
        raw = _ask_llm(_PROMPT.format(transcript=_fmt_transcript(segments), duration=duration))
        raw_items = _extract_json_array(raw)
    except Exception as exc:
        print(f"[highlights] LLM unavailable ({LLM_PROVIDER}): {exc} — using heuristic")

    if not raw_items:
        return _heuristic_highlights(segments, duration)

    cleaned: list[dict] = []
    used: list[tuple[float, float]] = []
    for item in raw_items:
        try:
            start = max(0.0, float(item["start_sec"]))
            end = min(float(item["end_sec"]), duration)
        except (KeyError, TypeError, ValueError):
            continue
        if end - start < 5.0:
            continue
        h = _snap_to_segments(
            {
                "start_sec": start,
                "end_sec": end,
                "score": max(0, min(100, int(item.get("score", 50)))),
                "hook": str(item.get("hook", ""))[:200] or "Highlight",
                "reason": str(item.get("reason", ""))[:300],
            },
            segments,
        )
        if h["end_sec"] - h["start_sec"] < 5.0:
            continue
        if any(h["start_sec"] < ue and h["end_sec"] > us for us, ue in used):
            continue
        used.append((h["start_sec"], h["end_sec"]))
        cleaned.append(h)

    cleaned.sort(key=lambda x: -x["score"])
    return cleaned[:6] or _heuristic_highlights(segments, duration)
