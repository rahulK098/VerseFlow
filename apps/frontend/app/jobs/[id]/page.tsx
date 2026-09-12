"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

type Render = {
  id: string;
  type: string;
  label: string | null;
  template: string | null;
  background: string | null;
  aspect: string | null;
  status: string;
  start_sec: number | null;
  end_sec: number | null;
  output_file: string | null;
  duration_sec: number | null;
  created_at: string;
};

type Segment = { start: number; end: number; text: string };

type Highlight = {
  start_sec: number;
  end_sec: number;
  score: number;
  hook: string;
  reason: string;
};

type Project = {
  id: string;
  status: string;
  title: string;
  source_type: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  renders: Render[];
  duration_sec: number | null;
  transcript: string | null;
  segments: Segment[];
  highlights: Highlight[];
};

const ASPECT_CSS: Record<string, string> = {
  "9:16": "9 / 16",
  "16:9": "16 / 9",
  "1:1": "1 / 1",
};

type Progress = { percent: number; stage: string; message: string };

// ── Helpers ────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  pending:     "text-gray-400",
  downloading: "text-purple-400",
  analyzing:   "text-blue-400",
  ready:       "text-green-400",
  failed:      "text-red-400",
};

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ── Video clip card ────────────────────────────────────────────────────────

function ClipCard({ render, onDelete }: { render: Render; onDelete: () => void }) {
  const [deleting, setDeleting] = useState(false);
  const src = `${API}/api/exports/${render.id}/download`;

  const handleDelete = async () => {
    if (!confirm(`Delete "${render.label ?? "this clip"}"?`)) return;
    setDeleting(true);
    await fetch(`${API}/api/renders/${render.id}`, { method: "DELETE" });
    onDelete();
  };

  if (render.status === "queued" || render.status === "rendering") {
    return (
      <div className="bg-gray-900 rounded-xl p-5 flex flex-col items-center justify-center min-h-[160px] gap-2">
        <div className="w-5 h-5 rounded-full border-2 border-purple-500 border-t-transparent animate-spin" />
        <p className="text-sm text-gray-400">{render.label ?? "Generating…"}</p>
        <p className="text-xs text-gray-600 capitalize">{render.status}</p>
      </div>
    );
  }

  if (render.status === "failed") {
    return (
      <div className="bg-gray-900 rounded-xl p-5 flex flex-col items-center justify-center min-h-[160px] gap-2">
        <p className="text-sm text-red-400">Render failed</p>
        <p className="text-xs text-gray-500">{render.label}</p>
        <button onClick={handleDelete} className="text-xs text-gray-600 hover:text-red-400 mt-1">
          Remove
        </button>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden flex flex-col">
      <div
        className="relative bg-black w-full"
        style={{ aspectRatio: ASPECT_CSS[render.aspect ?? "9:16"] ?? "9 / 16" }}
      >
        <video
          src={src}
          controls
          preload="metadata"
          className="absolute inset-0 w-full h-full object-contain"
        />
      </div>
      <div className="p-3 flex flex-col gap-2">
        <div>
          <p className="font-medium text-sm truncate">{render.label ?? "Clip"}</p>
          <p className="text-gray-600 text-xs">
            {render.duration_sec != null && `${fmt(render.duration_sec)} · `}
            {render.aspect ?? "9:16"} · {render.template ?? "minimal"}
          </p>
        </div>
        <div className="flex gap-2">
          <a
            href={src}
            download={`${render.label ?? "clip"}.mp4`}
            className="flex-1 text-center bg-purple-700 hover:bg-purple-600 text-white text-xs px-3 py-1.5 rounded-lg transition-colors"
          >
            Download
          </a>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="text-gray-500 hover:text-red-400 text-xs px-2 transition-colors"
            title="Delete clip"
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [project, setProject] = useState<Project | null>(null);
  const [progress, setProgress] = useState<Progress>({ percent: 0, stage: "loading", message: "Loading…" });
  const [pageError, setPageError] = useState<string | null>(null);

  // Trim controls
  const [startSec, setStartSec] = useState(0);
  const [endSec, setEndSec] = useState(0);
  const [label, setLabel] = useState("");
  const [template, setTemplate] = useState("minimal");
  const [background, setBackground] = useState("stock");
  const [aspect, setAspect] = useState("9:16");
  const [titleCard, setTitleCard] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchProject = useCallback(() =>
    fetch(`${API}/api/jobs/${id}`)
      .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); })
      .then((p: Project) => {
        setProject(p);
        if (p.duration_sec && endSec === 0) setEndSec(Math.floor(p.duration_sec));
      })
      .catch(e => setPageError(e.message)),
  [id, endSec]);

  // Initial fetch
  useEffect(() => { fetchProject(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Video projects default to their own footage as background
  useEffect(() => {
    if (project?.source_type === "video") setBackground("source");
  }, [project?.source_type]);

  // SSE during download/analysis phase
  useEffect(() => {
    if (!project) return;
    if (!["pending", "downloading", "analyzing"].includes(project.status)) return;

    const es = new EventSource(`${API}/api/jobs/${id}/stream`);
    es.onmessage = e => {
      try {
        const data: Progress = JSON.parse(e.data);
        setProgress(data);
        if (data.stage === "ready" || data.stage === "failed") {
          es.close();
          fetchProject();
        }
      } catch { /* ignore */ }
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [id, project?.status, fetchProject]);

  // Poll when any render is in-progress
  useEffect(() => {
    const hasActive = project?.renders.some(r => r.status === "queued" || r.status === "rendering");
    if (hasActive && !pollRef.current) {
      pollRef.current = setInterval(fetchProject, 2000);
    } else if (!hasActive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [project?.renders, fetchProject]);

  // ── Generate clip ────────────────────────────────────────────────────────

  const postClip = async (body: {
    start_sec: number;
    end_sec: number;
    label?: string;
    title_card?: boolean;
  }) => {
    setGenError(null);
    setGenerating(true);
    try {
      const res = await fetch(`${API}/api/jobs/${id}/clips`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title_card: titleCard,
          ...body,
          template,
          background,
          aspect,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? res.statusText);
      }
      await fetchProject();
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setGenerating(false);
    }
  };

  const generate = () =>
    postClip({ start_sec: startSec, end_sec: endSec, label: label.trim() || undefined });

  // Suggested clips always burn their hook as a title card — it's the retention hook
  const generateHighlight = (h: Highlight) =>
    postClip({ start_sec: h.start_sec, end_sec: h.end_sec, label: h.hook, title_card: true });

  const generateAllHighlights = async () => {
    for (const h of project?.highlights ?? []) {
      await postClip({ start_sec: h.start_sec, end_sec: h.end_sec, label: h.hook, title_card: true });
    }
  };

  const generateFull = () => {
    const dur = project?.duration_sec ?? 0;
    setStartSec(0);
    setEndSec(Math.floor(dur));
    setLabel("Full audio");
  };

  const seekAudio = (sec: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = sec;
      audioRef.current.play().catch(() => {});
    }
  };

  // ── Render ───────────────────────────────────────────────────────────────

  if (pageError) return (
    <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
      <div className="text-center">
        <p className="text-red-400 mb-4">{pageError}</p>
        <Link href="/jobs" className="text-purple-400 underline">← Back to projects</Link>
      </div>
    </main>
  );

  if (!project) return (
    <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
      <p className="text-gray-500">Loading…</p>
    </main>
  );

  const dur = project.duration_sec ?? 0;
  const isAnalyzing = ["pending", "downloading", "analyzing"].includes(project.status);
  const isReady = project.status === "ready";
  const clipDuration = endSec - startSec;

  return (
    <main className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-5xl mx-auto">

        {/* Header */}
        <Link href="/jobs" className="text-gray-500 hover:text-gray-300 text-sm mb-6 inline-block">
          ← All projects
        </Link>
        <h1 className="text-2xl font-bold mb-1">{project.title || "Untitled"}</h1>
        <p className={`text-sm font-medium capitalize mb-6 ${STATUS_COLOR[project.status] ?? "text-gray-400"}`}>
          {project.status === "ready" ? "Ready to generate" : project.status}
        </p>

        {/* Analysis progress */}
        {isAnalyzing && (
          <div className="mb-8">
            <div className="flex justify-between text-sm text-gray-400 mb-2">
              <span>{progress.message}</span>
              <span>{progress.percent}%</span>
            </div>
            <div className="w-full bg-gray-800 rounded-full h-2">
              <div
                className="bg-purple-500 h-2 rounded-full transition-all duration-500"
                style={{ width: `${progress.percent}%` }}
              />
            </div>
            <p className="text-xs text-gray-600 mt-2">
              Transcription running in the background — this page updates automatically.
            </p>
          </div>
        )}

        {/* Pending hint */}
        {project.status === "pending" && (
          <div className="bg-gray-900 rounded-xl p-5 text-sm text-gray-400 mb-8">
            <p className="font-medium mb-1">Job is queued</p>
            <pre className="bg-gray-800 rounded p-3 text-xs text-green-400 overflow-x-auto mt-2">
              docker compose up worker
            </pre>
          </div>
        )}

        {/* Error */}
        {project.status === "failed" && project.error && (
          <div className="bg-red-900/40 border border-red-700 rounded-xl p-4 text-red-300 text-sm mb-8">
            {project.error}
          </div>
        )}

        {/* ── Ready: audio player + trim + generate ── */}
        {isReady && dur > 0 && (
          <div className="bg-gray-900 rounded-2xl p-6 mb-8 space-y-5">
            <h2 className="font-semibold text-lg">Generate a clip</h2>

            {/* Audio player */}
            <audio
              ref={audioRef}
              src={`${API}/api/jobs/${id}/audio`}
              controls
              className="w-full accent-purple-500"
              style={{ colorScheme: "dark" }}
            />

            {/* Transcript segments (collapsible) */}
            {project.segments.length > 0 && (
              <details className="text-sm text-gray-400">
                <summary className="cursor-pointer select-none hover:text-gray-200 transition-colors">
                  Transcript ({project.segments.length} segments)
                </summary>
                <div className="mt-3 space-y-1 max-h-48 overflow-y-auto pr-1">
                  {project.segments.map((seg, i) => (
                    <button
                      key={i}
                      onClick={() => seekAudio(seg.start)}
                      className="w-full text-left hover:bg-gray-800 rounded px-2 py-1 transition-colors"
                    >
                      <span className="text-purple-400 text-xs mr-2">{fmt(seg.start)}</span>
                      {seg.text}
                    </button>
                  ))}
                </div>
              </details>
            )}

            {/* AI suggested clips */}
            {project.highlights.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-300">✨ Suggested clips</h3>
                  <button
                    onClick={generateAllHighlights}
                    disabled={generating}
                    className="text-xs text-purple-400 hover:text-purple-300 disabled:opacity-40 transition-colors"
                  >
                    Generate all ({project.highlights.length})
                  </button>
                </div>
                <div className="space-y-2">
                  {project.highlights.map((h, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-3 bg-gray-800/60 rounded-xl px-4 py-3"
                    >
                      <span
                        className={`text-xs font-bold px-2 py-1 rounded-lg shrink-0 ${
                          h.score >= 80 ? "bg-green-900 text-green-300"
                          : h.score >= 60 ? "bg-yellow-900 text-yellow-300"
                          : "bg-gray-700 text-gray-300"
                        }`}
                        title={h.reason}
                      >
                        {h.score}
                      </span>
                      <button
                        onClick={() => seekAudio(h.start_sec)}
                        className="flex-1 text-left min-w-0 hover:text-purple-300 transition-colors"
                        title="Play from here"
                      >
                        <p className="text-sm font-medium truncate">{h.hook}</p>
                        <p className="text-xs text-gray-500">
                          {fmt(h.start_sec)} → {fmt(h.end_sec)} ({fmt(h.end_sec - h.start_sec)})
                        </p>
                      </button>
                      <button
                        onClick={() => generateHighlight(h)}
                        disabled={generating}
                        className="bg-purple-700 hover:bg-purple-600 disabled:opacity-40 text-white text-xs px-3 py-1.5 rounded-lg transition-colors shrink-0"
                      >
                        Generate
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Range slider */}
            <div className="space-y-3">
              <div className="flex justify-between text-xs text-gray-500">
                <span>0:00</span>
                <span className="text-gray-300 font-medium">
                  Selected: {fmt(startSec)} → {fmt(endSec)}
                  {clipDuration > 0 && (
                    <span className="text-gray-500 ml-2">({fmt(clipDuration)})</span>
                  )}
                </span>
                <span>{fmt(dur)}</span>
              </div>

              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <label className="text-xs text-gray-500 w-12 shrink-0">Start</label>
                  <input
                    type="range" min={0} max={Math.max(0, Math.floor(dur) - 1)}
                    value={startSec}
                    onChange={e => {
                      const v = Number(e.target.value);
                      setStartSec(v);
                      if (v >= endSec) setEndSec(Math.min(v + 1, Math.floor(dur)));
                    }}
                    className="flex-1 accent-purple-500"
                  />
                  <input
                    type="number" min={0} max={Math.floor(dur)}
                    value={startSec}
                    onChange={e => setStartSec(Math.max(0, Number(e.target.value)))}
                    className="w-16 bg-gray-800 text-white text-xs rounded px-2 py-1 text-right"
                  />
                  <span className="text-xs text-gray-600">s</span>
                </div>

                <div className="flex items-center gap-3">
                  <label className="text-xs text-gray-500 w-12 shrink-0">End</label>
                  <input
                    type="range" min={1} max={Math.floor(dur)}
                    value={endSec}
                    onChange={e => {
                      const v = Number(e.target.value);
                      setEndSec(v);
                      if (v <= startSec) setStartSec(Math.max(0, v - 1));
                    }}
                    className="flex-1 accent-purple-500"
                  />
                  <input
                    type="number" min={1} max={Math.floor(dur)}
                    value={endSec}
                    onChange={e => setEndSec(Math.min(Math.floor(dur), Number(e.target.value)))}
                    className="w-16 bg-gray-800 text-white text-xs rounded px-2 py-1 text-right"
                  />
                  <span className="text-xs text-gray-600">s</span>
                </div>
              </div>

              {/* Optional label */}
              <input
                type="text"
                placeholder="Clip name (optional)"
                value={label}
                onChange={e => setLabel(e.target.value)}
                className="w-full bg-gray-800 text-white text-sm rounded-lg px-3 py-2 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-purple-500"
              />

              {/* Caption template */}
              <div className="flex items-center gap-3">
                <label className="text-xs text-gray-500 shrink-0">Caption style</label>
                <select
                  value={template}
                  onChange={e => setTemplate(e.target.value)}
                  className="flex-1 bg-gray-800 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-purple-500"
                >
                  <option value="minimal">Minimal — white text, soft fade</option>
                  <option value="bold">Bold — large yellow text, pop-in</option>
                  <option value="karaoke">Karaoke — word-by-word highlight</option>
                  <option value="neon">Neon — cyan glow, slow zoom</option>
                  <option value="pop">Pop — bouncy word pop-in</option>
                  <option value="slide">Slide — words slide up + fade</option>
                </select>
              </div>

              {/* Format */}
              <div className="flex items-center gap-3">
                <label className="text-xs text-gray-500 shrink-0">Format</label>
                <select
                  value={aspect}
                  onChange={e => setAspect(e.target.value)}
                  className="flex-1 bg-gray-800 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-purple-500"
                >
                  <option value="9:16">9:16 — Shorts / Reels / TikTok</option>
                  <option value="16:9">16:9 — YouTube (lyric video)</option>
                  <option value="1:1">1:1 — Square</option>
                </select>
              </div>

              {/* Background */}
              <div className="flex items-center gap-3">
                <label className="text-xs text-gray-500 shrink-0">Background</label>
                <select
                  value={background}
                  onChange={e => setBackground(e.target.value)}
                  className="flex-1 bg-gray-800 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-purple-500"
                >
                  {project.source_type === "video" && (
                    <option value="source">Source video — your uploaded footage</option>
                  )}
                  <option value="stock">Stock footage (when available)</option>
                  <option value="visualizer">Spectrum — audio-reactive fire</option>
                  <option value="waves">Waves — purple waveform lines</option>
                  <option value="scope">Scope — lissajous oscilloscope</option>
                  <option value="blank">Blank — clean black, captions only</option>
                </select>
              </div>

              {/* Title card */}
              <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={titleCard}
                  onChange={e => setTitleCard(e.target.checked)}
                  className="accent-purple-500"
                />
                Burn clip name as a title card (first 3 s)
              </label>

              {genError && (
                <p className="text-red-400 text-xs">{genError}</p>
              )}

              <div className="flex gap-3">
                <button
                  onClick={generate}
                  disabled={generating || clipDuration <= 0}
                  className="flex-1 bg-purple-700 hover:bg-purple-600 disabled:opacity-40 text-white text-sm font-medium px-4 py-2.5 rounded-xl transition-colors"
                >
                  {generating ? "Queuing…" : `Generate clip (${fmt(clipDuration)})`}
                </button>
                <button
                  onClick={generateFull}
                  className="bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm px-4 py-2.5 rounded-xl transition-colors"
                  title="Reset to full audio"
                >
                  Full audio
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Clips grid ── */}
        {project.renders.length > 0 && (
          <div>
            <h2 className="font-semibold text-lg mb-4">
              Your clips
              <span className="text-gray-500 text-sm font-normal ml-2">
                ({project.renders.length})
              </span>
            </h2>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
              {project.renders.map(r => (
                <ClipCard key={r.id} render={r} onDelete={fetchProject} />
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
