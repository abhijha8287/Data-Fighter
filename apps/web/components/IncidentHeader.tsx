import type { IncidentState } from "@/types/incident";

function datasetShortName(urn: string): string {
  const match = urn.match(/,([^,]+),PROD\)$/);
  return match ? match[1] : urn;
}

export function IncidentHeader({ state }: { state: IncidentState }) {
  if (state.status === "resolved") {
    return (
      <div className="rounded-2xl border border-emerald-700/50 bg-emerald-950/30 p-6">
        <p className="text-lg font-bold text-emerald-300">🔥 INCIDENT RESOLVED</p>
        <ul className="mt-3 space-y-1 text-sm text-emerald-200/90">
          <li>✓ Investigation</li>
          <li>✓ Root cause</li>
          <li>✓ Fix generated</li>
          <li>✓ PR created — {" "}
            <a
              href={state.github_pr_url ?? "#"}
              target="_blank"
              rel="noreferrer"
              className="underline decoration-emerald-500 underline-offset-2 hover:text-emerald-100"
            >
              {state.github_pr_url}
            </a>
          </li>
          <li>
            {state.datahub_write_back?.succeeded ? "✓" : "○"} DataHub updated
            {!state.datahub_write_back?.succeeded && (
              <span className="text-emerald-400/60">
                {" "}
                (mutation disabled — see DATAHUB_MUTATION_ENABLED)
              </span>
            )}
          </li>
        </ul>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-red-700/50 bg-red-950/30 p-6">
      <p className="text-sm font-semibold text-red-400">🚨 Active Incident</p>
      <p className="mt-2 text-xl font-bold text-zinc-50">{datasetShortName(state.dataset_urn)}</p>
      <p className="text-sm text-zinc-300">
        {state.affected_column ? `${state.affected_column} deleted` : state.incident_description}
      </p>
      <span className="mt-3 inline-block rounded-full bg-red-600/20 px-2.5 py-1 text-xs font-bold uppercase tracking-wide text-red-300">
        HIGH
      </span>
    </div>
  );
}
