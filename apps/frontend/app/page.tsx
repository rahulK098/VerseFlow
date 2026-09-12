"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function UploadPage() {
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [importUrl, setImportUrl] = useState("");
  const [importing, setImporting] = useState(false);

  const handleImport = useCallback(async () => {
    const url = importUrl.trim();
    if (!url) return;
    setError(null);
    setImporting(true);
    try {
      const res = await fetch(`${API}/api/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail ?? res.statusText);
      }
      const job = await res.json();
      router.push(`/jobs/${job.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setImporting(false);
    }
  }, [importUrl, router]);

  const handleFile = useCallback(
    async (file: File) => {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!["mp3", "wav", "m4a", "flac", "ogg", "mp4", "mov", "webm", "mkv"].includes(ext)) {
        setError(`Unsupported format .${ext} — use MP3/WAV/M4A/FLAC/OGG audio or MP4/MOV/WebM/MKV video`);
        return;
      }
      setError(null);
      setUploading(true);
      try {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(`${API}/api/upload`, { method: "POST", body: form });
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(body.detail ?? res.statusText);
        }
        const job = await res.json();
        router.push(`/jobs/${job.id}`);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
        setUploading(false);
      }
    },
    [router]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-center p-8">
      <div className="w-full max-w-lg">
        <h1 className="text-4xl font-bold mb-2 text-center tracking-tight">VerseFlow</h1>
        <p className="text-gray-400 text-center mb-10">
          Upload a song or video → viral clips &amp; lyric videos in minutes
        </p>

        <label
          className={`flex flex-col items-center justify-center border-2 border-dashed rounded-2xl p-16 cursor-pointer transition-colors ${
            dragging ? "border-purple-400 bg-purple-950/30" : "border-gray-700 hover:border-purple-500"
          } ${uploading ? "opacity-50 pointer-events-none" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <input
            type="file"
            accept=".mp3,.wav,.m4a,.flac,.ogg,.mp4,.mov,.webm,.mkv"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
          />
          <div className="text-5xl mb-4">{uploading ? "⏳" : "🎬"}</div>
          <p className="font-semibold text-lg">
            {uploading ? "Uploading…" : "Drop your song or video here"}
          </p>
          <p className="text-gray-500 text-sm mt-1">MP3 · WAV · M4A · FLAC · OGG · MP4 · MOV · WebM · MKV</p>
        </label>

        {/* URL import */}
        <div className="mt-6">
          <div className="flex items-center gap-3 text-gray-600 text-xs mb-3">
            <div className="flex-1 h-px bg-gray-800" />
            or paste a link
            <div className="flex-1 h-px bg-gray-800" />
          </div>
          <div className="flex gap-2">
            <input
              type="url"
              placeholder="YouTube / Twitch / podcast URL…"
              value={importUrl}
              onChange={(e) => setImportUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleImport(); }}
              disabled={importing}
              className="flex-1 bg-gray-900 border border-gray-800 text-white text-sm rounded-xl px-4 py-3 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-purple-500"
            />
            <button
              onClick={handleImport}
              disabled={importing || !importUrl.trim()}
              className="bg-purple-700 hover:bg-purple-600 disabled:opacity-40 text-white text-sm font-medium px-5 py-3 rounded-xl transition-colors"
            >
              {importing ? "Importing…" : "Import"}
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 bg-red-900/40 border border-red-700 rounded-xl p-4 text-red-300 text-sm">
            {error}
          </div>
        )}

        <div className="mt-8 text-center">
          <a href="/jobs" className="text-purple-400 hover:text-purple-300 text-sm underline">
            View all jobs →
          </a>
        </div>
      </div>
    </main>
  );
}
