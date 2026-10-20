
export type Criticality = "low" | "medium" | "critical";

export type RejectionReason =
  | "not_found"
  | "undocumented"
  | "type_mismatch"
  | "out_of_range"
  | "invalid_bitmask_value"
  | "invalid_enum_value";

export interface ParamDefinition {
  name: string;
  vehicle_types: string[];
  firmware_version: string;
  description: string;
  unit: string | null;
  min_value: number | null;
  max_value: number | null;
  increment: number | null;
  bitmask: Record<number, string> | null;
  reboot_required: boolean;
  values: Record<string, string> | null;
  doc_url: string | null;
  github_source_url: string | null;
}

export interface DependencyWarning {
  related_params: string[];
  message: string;
}

export interface TurnStep {
  stage: string;
  tool_name: string | null;
  status: "ok" | "blocked" | "error";
  detail: string;
}

export interface ValidatedProposal {
  param_name: string;
  current_value: number | null;
  proposed_value: number;
  reason: string;
  accepted: boolean;
  rejection_reason: RejectionReason | null;
  rejection_message: string | null;
  criticality: Criticality | null;
  dependency_warnings: DependencyWarning[];
  reboot_required: boolean;
  definition: ParamDefinition | null;
  proposal_id: string | null;
}

export interface SITLSettings {
  vehicle: "copter" | "plane";
  frame: string | null;
  instance: number;
  wipe_eeprom: boolean;
  speedup: number;
}

export interface SessionStartResponse {
  session_id: string;
  vehicle_type: string;
  firmware_version: string;
  param_count: number;
  undocumented_param_count: number;
  read_only: boolean;
  frame_label?: string | null;
  board_label?: string | null;
}

export interface ChatResponse {
  session_id: string;
  reply: string | null;
  pending_proposal: ValidatedProposal | null;
  rejected_proposals: ValidatedProposal[];
  turn_steps: TurnStep[];
  episode_id?: string | null;
}

export type ChatStreamEvent =
  | { type: "step"; step: TurnStep }
  | {
      type: "final";
      reply: string | null;
      pending_proposal: ValidatedProposal | null;
      rejected_proposals: ValidatedProposal[];
      turn_steps: TurnStep[];
      episode_id?: string | null;
    }
  | { type: "error"; status: number; detail: string };

export type SessionStartEvent =
  | { type: "progress"; stage: string; label: string; percent: number }
  | ({ type: "final" } & SessionStartResponse)
  | { type: "error"; status: number; detail: string };

export type RebootEvent =
  | { type: "progress"; stage: string; label: string; percent: number; link: "up" | "down" }
  | { type: "final"; param_count: number; armed: boolean | null }
  | { type: "error"; status: number; detail: string };

export interface ProposalDecisionResponse {
  proposal_id: string;
  outcome: "applied" | "rejected" | "blocked_at_write_time";
  detail: string;
  steps: TurnStep[];
  episode_id?: string | null;
}

export interface PortInfo {
  path: string;
  label: string;
  likely_fc: boolean;
}

export interface SafetyParamEntry {
  name: string;
  current_value: number;
  documented: boolean;
}

export interface SessionSummary {
  session_id: string;
  started_at: string;
  ended_at: string | null;
  applied_count: number;
  rejected_count: number;
  pending_count: number;
  reboot_required_params: string[];
  safety_snapshot_text: string;
  safety_snapshot_params: SafetyParamEntry[];
}

export interface VehicleStatus {
  session_id: string;
  connected: boolean;
  vehicle_type: string;
  firmware_version: string;
  read_only: boolean;
  frame_label?: string | null;
  board_label?: string | null;
}

export interface ProcedureStep {
  description: string;
  manual: boolean;
}

export interface ProcedureProposal {
  procedure_id: string;
  title: string;
  steps: ProcedureStep[];
}

export interface ProcedureDecisionResponse {
  procedure_id: string;
  outcome: "triggered" | "trigger_not_acknowledged" | "acknowledged" | "rejected";
  detail: unknown;
}

export interface TelemetryEventMessage {
  field: string;
  value: Record<string, unknown>;
}

export type ChatMessage =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      text: string;
      rejectedProposals?: ValidatedProposal[];
      turnSteps?: TurnStep[];
      episodeId?: string;
    };

export interface SessionListEntry {
  session_id: string;
  started_at: string;
  ended_at: string | null;
  vehicle_type: string;
  firmware_version: string;
  read_only: boolean;
}

export interface AuditEvent {
  id: number;
  timestamp: string;
  event_type: "proposal" | "confirm" | "reject" | "apply";
  param_name: string;
  before_value: number | null;
  after_value: number | null;
  reason: string | null;
  criticality: string | null;
  reboot_required: boolean;
  prev_hash: string;
  hash: string;
}

export interface AuditVerifyResult {
  intact: boolean;
  broken_at_event_id: number | null;
}

export interface TranscriptMessage {
  role: "user" | "assistant" | "tool" | "unknown";
  content: string;
  tool_name: string | null;
  turn_steps?: TurnStep[] | null;
  rejected_proposals?: ValidatedProposal[] | null;
}

export interface SessionTranscript {
  session_id: string;
  messages: TranscriptMessage[];
}
