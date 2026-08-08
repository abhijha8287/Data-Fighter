import type { IncidentState, LineageAsset } from "@/types/incident";

function datasetShortName(urn: string): string {
  const match = urn.match(/,([^,]+),PROD\)$/);
  return match ? match[1] : urn;
}

function AssetNode({
  asset,
  directlyBroken,
}: {
  asset: LineageAsset;
  directlyBroken: boolean;
}) {
  return (
    <div
      className={
        "rounded-lg border px-3 py-2 text-center text-xs font-medium " +
        (directlyBroken
          ? "border-red-500/60 bg-red-950/40 text-red-300"
          : "border-amber-700/50 bg-amber-950/20 text-amber-300/90")
      }
      title={`${asset.entity_type} · owned by ${asset.owner}`}
    >
      {asset.name}
    </div>
  );
}

export function LineageGraph({ state }: { state: IncidentState }) {
  const assets = state.downstream_assets ?? [];
  const affectedFiles = new Set(state.affected_files ?? []);
  const pipelines = assets.filter((a) => a.asset_category === "pipeline");
  const consumers = assets.filter((a) => a.asset_category !== "pipeline");

  const isDirectlyBroken = (a: LineageAsset) => affectedFiles.has(`${a.name}.sql`);

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-950/60 p-6">
      <p className="text-sm font-medium text-zinc-400">Lineage</p>
      <div className="mt-4 flex flex-col items-center gap-3">
        <div className="rounded-lg border border-orange-500 bg-orange-950/40 px-4 py-2 text-center text-sm font-semibold text-orange-300">
          🚨 {datasetShortName(state.dataset_urn)}
        </div>
        {pipelines.length > 0 && (
          <>
            <div className="h-4 w-px bg-zinc-700" />
            <div className="flex flex-wrap justify-center gap-2">
              {pipelines.map((a) => (
                <AssetNode key={a.urn} asset={a} directlyBroken={isDirectlyBroken(a)} />
              ))}
            </div>
          </>
        )}
        {consumers.length > 0 && (
          <>
            <div className="h-4 w-px bg-zinc-700" />
            <div className="flex flex-wrap justify-center gap-2">
              {consumers.map((a) => (
                <AssetNode key={a.urn} asset={a} directlyBroken={isDirectlyBroken(a)} />
              ))}
            </div>
          </>
        )}
      </div>
      <div className="mt-4 flex items-center gap-4 text-xs text-zinc-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-red-500" /> directly references the deleted
          column
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-amber-600" /> affected transitively
        </span>
      </div>
    </div>
  );
}
