import type { IncidentState, ValidationResult } from "@/types/incident";

function CheckItem({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className={"flex items-center gap-2 " + (ok ? "text-emerald-400" : "text-red-400")}>
      <span>{ok ? "✓" : "✗"}</span>
      <span className="text-zinc-300">{label}</span>
    </li>
  );
}

function ValidationChecklist({ v }: { v: ValidationResult }) {
  return (
    <ul className="mt-3 space-y-1 text-sm">
      <CheckItem ok={v.sql_parses} label="SQL syntax valid" />
      <CheckItem ok={v.schema_check_passed} label="Deleted column no longer referenced" />
      <CheckItem ok={v.file_scope_check_passed} label="Fix scoped to affected files only" />
      {v.errors.length > 0 && (
        <li className="mt-2 space-y-1 text-xs text-red-400">
          {v.errors.map((e, i) => (
            <div key={i}>{e}</div>
          ))}
        </li>
      )}
    </ul>
  );
}

export function FixDiffView({ state }: { state: IncidentState }) {
  const fix = state.proposed_fix;
  if (!fix) return null;

  if (fix.branch_taken === "no_fix_needed") {
    return (
      <div className="rounded-2xl border border-zinc-800 bg-zinc-950/60 p-6">
        <p className="text-sm font-medium text-zinc-400">Remediation</p>
        <p className="mt-2 text-sm text-zinc-300">{fix.explanation}</p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-950/60 p-6">
      <p className="text-sm font-medium text-zinc-400">Remediation</p>
      <div className="mt-4 space-y-5">
        {Object.keys(fix.files).map((path) => (
          <div key={path}>
            <p className="font-mono text-xs text-zinc-500">{path}</p>
            <div className="mt-1.5 grid grid-cols-1 gap-2 md:grid-cols-2">
              <div className="rounded-lg border border-red-900/40 bg-red-950/20 p-3">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-red-400">
                  Before
                </p>
                <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-xs text-red-200/80">
                  {fix.files_before[path]}
                </pre>
              </div>
              <div className="rounded-lg border border-emerald-900/40 bg-emerald-950/20 p-3">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-400">
                  After
                </p>
                <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-xs text-emerald-200/80">
                  {fix.files[path]}
                </pre>
              </div>
            </div>
          </div>
        ))}
      </div>
      {state.validation_result && (
        <>
          <p className="mt-5 text-sm font-medium text-zinc-400">Validation</p>
          <ValidationChecklist v={state.validation_result} />
        </>
      )}
    </div>
  );
}
