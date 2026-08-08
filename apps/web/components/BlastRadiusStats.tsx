import type { BlastRadius } from "@/types/incident";

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 px-5 py-4">
      <div className="text-3xl font-bold tabular-nums text-zinc-50">{value}</div>
      <div className="mt-1 text-xs font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </div>
    </div>
  );
}

export function BlastRadiusStats({
  blastRadius,
  affectedOwners,
}: {
  blastRadius: BlastRadius;
  // blastRadius.owners only covers downstream asset owners; affectedOwners
  // (from the identify_owners node) also includes the owner of the
  // incident dataset itself — the complete, correct stakeholder count.
  affectedOwners: string[];
}) {
  return (
    <div>
      <p className="text-sm font-medium text-zinc-400">Blast Radius</p>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Stat value={blastRadius.total_count} label="Assets" />
        <Stat value={blastRadius.pipelines} label="Pipelines" />
        <Stat value={blastRadius.dashboards} label="Dashboards" />
        <Stat value={blastRadius.ml_models} label="ML Models" />
        <Stat value={affectedOwners.length} label="Owners" />
      </div>
      {blastRadius.total_count === 0 && (
        <p className="mt-3 text-sm text-zinc-500">
          No downstream dependents found for this dataset.
        </p>
      )}
    </div>
  );
}
