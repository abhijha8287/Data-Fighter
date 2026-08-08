"use client";

import type { DemoIncidentType } from "@/types/incident";

const OPTIONS: { type: DemoIncidentType; label: string; enabled: boolean }[] = [
  { type: "column_deleted", label: "Column Deleted", enabled: true },
  { type: "column_renamed", label: "Column Renamed", enabled: false },
  { type: "type_changed", label: "Type Changed", enabled: false },
  { type: "freshness_breach", label: "Freshness Breach", enabled: false },
];

export function DemoModeSelector({
  onSimulate,
  loading,
}: {
  onSimulate: () => void;
  loading: boolean;
}) {
  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-950/60 p-6">
      <p className="text-sm font-medium text-zinc-400">Simulate Incident</p>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {OPTIONS.map((opt) =>
          opt.enabled ? (
            <button
              key={opt.type}
              onClick={onSimulate}
              disabled={loading}
              className="rounded-lg bg-orange-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? "Starting…" : opt.label}
            </button>
          ) : (
            <button
              key={opt.type}
              disabled
              title="Not wired in this build"
              className="cursor-not-allowed rounded-lg border border-zinc-800 px-4 py-2.5 text-sm font-medium text-zinc-600"
            >
              {opt.label}
            </button>
          ),
        )}
      </div>
    </div>
  );
}
