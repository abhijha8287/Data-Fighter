// Mirrors apps/api/app/incidents/state.py's IncidentState. Kept as plain
// types (not generated) since the backend has no OpenAPI-client codegen
// step in this build — see the design doc's scope cuts for why.

export type IncidentStatus =
  | "detected"
  | "investigating"
  | "investigated"
  | "remediating"
  | "remediated"
  | "creating_pr"
  | "resolved"
  | "failed";

export interface LineageAsset {
  urn: string;
  name: string;
  platform: string;
  entity_type: string;
  asset_category: "pipeline" | "dashboard" | "ml_model" | null;
  owner: string;
}

export interface BlastRadius {
  downstream_assets: LineageAsset[];
  total_count: number;
  pipelines: number;
  dashboards: number;
  ml_models: number;
  owners: string[];
}

export interface RootCause {
  summary: string;
  affected_files: string[];
  confidence: number;
}

export interface ProposedFix {
  branch_taken: "removal" | "no_fix_needed";
  files: Record<string, string>;
  files_before: Record<string, string>;
  explanation: string;
}

export interface ValidationResult {
  sql_parses: boolean;
  schema_check_passed: boolean;
  file_scope_check_passed: boolean;
  passed: boolean;
  errors: string[];
}

export interface IncidentReport {
  incident_id: string;
  dataset: string;
  incident_type: string;
  description: string;
  blast_radius: BlastRadius | null;
  root_cause: RootCause | null;
  remediation: ProposedFix | null;
  validation: ValidationResult | null;
  github_pr_url: string | null;
  resolved_at: string | null;
}

export interface IncidentState {
  incident_id: string;
  dataset_urn: string;
  incident_type: string;
  incident_description: string;
  affected_column: string | null;
  status: IncidentStatus;
  error: string | null;

  dataset_metadata?: Record<string, unknown>;
  schema_before?: unknown[];
  schema_after?: unknown[];

  downstream_assets?: LineageAsset[];
  affected_owners?: string[];

  blast_radius?: BlastRadius;
  root_cause?: RootCause;
  affected_files?: string[];

  proposed_fix?: ProposedFix;
  validation_result?: ValidationResult;

  github_pr_url?: string | null;
  incident_report?: IncidentReport;
  datahub_write_back?: { attempted: boolean; succeeded: boolean; note: string };
}

export type DemoIncidentType =
  | "column_deleted"
  | "column_renamed"
  | "type_changed"
  | "freshness_breach";
