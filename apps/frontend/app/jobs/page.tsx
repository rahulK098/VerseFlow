"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type JobSummary = {
  id: string;
  title: string;
  status: string;
  source_type: string;
  created_at: string;
  render_count: number;
};

const STATUS_COLOR: Record<string, string> = {
  pending:     "bg-gray-700 text-gray-300",
  downloading: "bg-purple-900 text-purple-200",
  analyzing:   "bg-blue-800 text-blue-200",
  ready:       "bg-green-800 text-green-200",
  failed:      "bg-red-800 text-red-300",
};

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/jobs`)
      .then((r) => r.json())
      .then((data) => { setJobs(data); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  }, []);

  return (
    <main className="min-h-screen bg-gray-950 text-white p-8">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold">Projects</h1>
          <Link href="/" className="bg-purple-700 hover:bg-purple-600 text-white px-4 py-2 rounded-lg text-sm transition-colors">
            + Upload song
          </Link>
        </div>

        {loading && <p className="text-gray-500">Loading…</p>}
        {error && <p className="text-red-400">API error: {error}</p>}

        {!loading && !error && jobs.length === 0 && (
          <div className="text-center py-24 text-gray-600">
            <div className="text-5xl mb-4">🎵</div>
            <p>No projects yet — upload a song to get started.</p>
          </div>
        )}

        <ul className="space-y-3">
          {jobs.map((job) => (
            <li key={job.id}>
              <Link
                href={`/jobs/${job.id}`}
                className="flex items-center justify-between bg-gray-900 hover:bg-gray-800 rounded-xl px-5 py-4 transition-colors"
              >
                <div>
                  <p className="font-medium">
                    <span className="mr-2" title={job.source_type === "video" ? "Video project" : "Audio project"}>
                      {job.source_type === "video" ? "🎬" : "🎵"}
                    </span>
                    {job.title || "Untitled"}
                  </p>
                  <p className="text-gray-500 text-xs mt-0.5">
                    {new Date(job.created_at).toLocaleString()}
                    {job.render_count > 0 && ` · ${job.render_count} clip${job.render_count !== 1 ? "s" : ""}`}
                  </p>
                </div>
                <span className={`text-xs font-semibold px-2.5 py-1 rounded-full capitalize ${STATUS_COLOR[job.status] ?? "bg-gray-700 text-gray-300"}`}>
                  {job.status}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}
