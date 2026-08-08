import type { IncidentState } from "@/types/incident";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</p>
      <div className="mt-1 text-sm text-zinc-300">{children}</div>
    </div>
  );
}

const PENDING = <span className="text-zinc-600">— pending —</span>;

export function AIExplanationPanel({ state }: { state: IncidentState }) {
  const br = state.blast_radius;
  const rc = state.root_cause;
  const fix = state.proposed_fix;

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-950/60 p-6">
      <p className="text-sm font-medium text-zinc-400">AI Explanation</p>
      <div className="mt-4 space-y-4">
        <Section title="What happened?">{state.incident_description}</Section>
        <Section title="Why does it matter?">
          {br ? (
            (() => {
              const owners = state.affected_owners ?? br.owners;
              return (
                `${br.total_count} downstream asset${br.total_count === 1 ? "" : "s"} depend on this column, ` +
                `across ${owners.length} team${owners.length === 1 ? "" : "s"} (${owners.join(", ") || "none"}).`
              );
            })()
          ) : (
            PENDING
          )}
        </Section>
        <Section title="What is affected?">
          {state.affected_files && state.affected_files.length > 0 ? (
            <ul className="list-inside list-disc space-y-0.5">
              {state.affected_files.map((f) => (
                <li key={f} className="font-mono text-xs">
                  {f}
                </li>
              ))}
            </ul>
          ) : (
            PENDING
          )}
        </Section>
        <Section title="What is the likely root cause?">
          {rc ? (
            <>
              <p>{rc.summary}</p>
              <p className="mt-1 text-xs text-zinc-500">
                Confidence: {Math.round(rc.confidence * 100)}%
              </p>
            </>
          ) : (
            PENDING
          )}
        </Section>
        <Section title="What should we do?">
          {fix ? fix.explanation : PENDING}
        </Section>
        <Section title="What did I change?">
          {fix && Object.keys(fix.files).length > 0 ? (
            <ul className="list-inside list-disc space-y-0.5">
              {Object.keys(fix.files).map((f) => (
                <li key={f} className="font-mono text-xs">
                  {f} — removed {state.affected_column} and everything derived from it
                </li>
              ))}
            </ul>
          ) : (
            PENDING
          )}
        </Section>
      </div>
    </div>
  );
}
