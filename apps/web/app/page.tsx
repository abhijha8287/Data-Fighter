"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { IncidentState } from "@/types/incident";
import { DemoModeSelector } from "@/components/DemoModeSelector";
import { IncidentHeader } from "@/components/IncidentHeader";
import { BlastRadiusStats } from "@/components/BlastRadiusStats";
import { LineageGraph } from "@/components/LineageGraph";
import { AIExplanationPanel } from "@/components/AIExplanationPanel";
import { InvestigationTimeline } from "@/components/InvestigationTimeline";
import { FixDiffView } from "@/components/FixDiffView";

type Phase = "idle" | "starting" | "investigating" | "remediating" | "creating_pr";

export default function Home() {
  const [incident, setIncident] = useState<IncidentState | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [apiError, setApiError] = useState<string | null>(null);

  async function handleSimulate() {
    setApiError(null);
    setPhase("starting");
    try {
      const created = await api.createDemoIncident();
      setIncident(created);
      // Investigation is read-only (no GitHub/DataHub writes) — safe to
      // auto-advance. Remediation and PR creation stay human-gated below.
      setPhase("investigating");
      const investigated = await api.investigate(created.incident_id);
      setIncident(investigated);
      setPhase("idle");
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "Failed to start incident");
      setPhase("idle");
    }
  }

  async function handleRemediate() {
    if (!incident) return;
    setApiError(null);
    setPhase("remediating");
    try {
      const remediated = await api.remediate(incident.incident_id);
      setIncident(remediated);
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "Failed to generate fix");
    } finally {
      setPhase("idle");
    }
  }

  async function handleCreatePr() {
    if (!incident) return;
    setApiError(null);
    setPhase("creating_pr");
    try {
      const resolved = await api.createPr(incident.incident_id);
      setIncident(resolved);
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "Failed to create PR");
    } finally {
      setPhase("idle");
    }
  }

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-12">
      <header className="mb-10">
        <p className="text-sm font-semibold uppercase tracking-widest text-orange-500">
          DATA FIREFIGHTER
        </p>
        <h1 className="mt-1 text-3xl font-bold text-zinc-50">
          Autonomous Data Incident Response
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-zinc-400">
          Investigates data incidents automatically using DataHub&rsquo;s live metadata
          graph, then proposes a fix — pausing for your approval before it touches GitHub.
        </p>
      </header>

      {!incident && (
        <DemoModeSelector onSimulate={handleSimulate} loading={phase === "starting"} />
      )}

      {apiError && (
        <div className="mt-4 rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-300">
          {apiError}
        </div>
      )}

      {incident && (
        <div className="mt-6 space-y-6">
          <IncidentHeader state={incident} />

          {incident.blast_radius && (
            <BlastRadiusStats
              blastRadius={incident.blast_radius}
              affectedOwners={incident.affected_owners ?? incident.blast_radius.owners}
            />
          )}

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <InvestigationTimeline state={incident} />
            <LineageGraph state={incident} />
          </div>

          <AIExplanationPanel state={incident} />

          {incident.status === "investigated" && (
            <button
              onClick={handleRemediate}
              disabled={phase === "remediating"}
              className="rounded-lg bg-orange-500 px-5 py-2.5 text-sm font-semibold text-zinc-950 transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {phase === "remediating" ? "Generating fix…" : "Generate Fix"}
            </button>
          )}

          {incident.proposed_fix && <FixDiffView state={incident} />}

          {incident.status === "remediated" && (
            <button
              onClick={handleCreatePr}
              disabled={phase === "creating_pr"}
              className="rounded-lg bg-orange-500 px-5 py-2.5 text-sm font-semibold text-zinc-950 transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {phase === "creating_pr" ? "Creating PR…" : "Approve & Create PR"}
            </button>
          )}
        </div>
      )}
    </main>
  );
}
