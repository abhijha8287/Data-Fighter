import type { IncidentState } from "@/types/incident";

interface Stage {
  label: string;
  done: (s: IncidentState) => boolean;
}

// Field-presence-based, not status-string-based: each stage reflects real
// data actually present in the API response, so the timeline can never
// show a checkmark for something that didn't really happen — including on
// the failure path, where later stages simply never turn true.
const STAGES: Stage[] = [
  { label: "Incident detected", done: (s) => !!s.incident_id },
  { label: "DataHub context loaded", done: (s) => !!s.dataset_metadata },
  { label: "Downstream lineage traced", done: (s) => !!s.downstream_assets },
  { label: "Blast radius calculated", done: (s) => !!s.blast_radius },
  { label: "Owners identified", done: (s) => !!s.affected_owners },
  { label: "Root cause analyzed", done: (s) => !!s.root_cause },
  { label: "Fix generated", done: (s) => !!s.proposed_fix },
  { label: "Fix validated", done: (s) => !!s.validation_result?.passed },
  { label: "GitHub PR created", done: (s) => !!s.github_pr_url },
  { label: "Incident report written", done: (s) => !!s.incident_report },
  { label: "DataHub write-back attempted", done: (s) => !!s.datahub_write_back },
];

export function InvestigationTimeline({ state }: { state: IncidentState }) {
  const failed = state.status === "failed";
  const currentIndex = STAGES.findIndex((stage) => !stage.done(state));

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-950/60 p-6">
      <p className="text-sm font-medium text-zinc-400">Investigation</p>
      <ul className="mt-3 space-y-2">
        {STAGES.map((stage, index) => {
          const isDone = stage.done(state);
          const isCurrent = index === currentIndex;
          const isErrored = failed && isCurrent;

          return (
            <li key={stage.label} className="flex items-center gap-2.5 text-sm">
              <span
                className={
                  isDone
                    ? "text-emerald-400"
                    : isErrored
                      ? "text-red-400"
                      : isCurrent
                        ? "text-orange-400"
                        : "text-zinc-700"
                }
              >
                {isDone ? "✓" : isErrored ? "✗" : isCurrent ? "●" : "○"}
              </span>
              <span
                className={
                  isDone
                    ? "text-zinc-300"
                    : isErrored
                      ? "text-red-300"
                      : isCurrent
                        ? "text-zinc-100"
                        : "text-zinc-600"
                }
              >
                {stage.label}
              </span>
            </li>
          );
        })}
      </ul>
      {failed && state.error && (
        <p className="mt-4 rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {state.error}
        </p>
      )}
    </div>
  );
}
