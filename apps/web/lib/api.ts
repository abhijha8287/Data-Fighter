import type { IncidentState } from "@/types/incident";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail ?? `${res.status} ${res.statusText}`, res.status);
  }
  return res.json();
}

export const api = {
  health: () =>
    request<{ status: string; datahub_mode: string; github_configured: boolean }>(
      "/api/health",
    ),
  createDemoIncident: () =>
    request<IncidentState>("/api/incidents/demo", { method: "POST" }),
  getIncident: (id: string) => request<IncidentState>(`/api/incidents/${id}`),
  investigate: (id: string) =>
    request<IncidentState>(`/api/incidents/${id}/investigate`, { method: "POST" }),
  remediate: (id: string) =>
    request<IncidentState>(`/api/incidents/${id}/remediate`, { method: "POST" }),
  createPr: (id: string) =>
    request<IncidentState>(`/api/incidents/${id}/create-pr`, { method: "POST" }),
};
