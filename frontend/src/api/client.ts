import type {
  AuditEvent,
  AuditVerifyResult,
  PortInfo,
  ChatResponse,
  ChatStreamEvent,
  ProcedureDecisionResponse,
  ProcedureProposal,
  ProposalDecisionResponse,
  SessionListEntry,
  RebootEvent,
  SessionStartEvent,
  SessionStartResponse,
  SessionSummary,
  SessionTranscript,
  SITLSettings,
  ValidatedProposal,
  VehicleStatus,
} from "./types";

const BASE_URL = import.meta.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8000";

async function request<T>(
  method: string,
  path: string,
  options: { params?: Record<string, string>; body?: unknown } = {},
): Promise<T> {
  const url = new URL(BASE_URL + path);
  for (const [k, v] of Object.entries(options.params ?? {})) {
    url.searchParams.set(k, v);
  }
  const res = await fetch(url.toString(), {
    method,
    headers: options.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${method} ${path} -> ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  startSession: (args: {
    mode: "hardware" | "simulation";
    connectionString?: string;
    sitlSettings?: SITLSettings;
  }) =>
    request<SessionStartResponse>("POST", "/session/start", {
      body: {
        mode: args.mode,
        connection_string: args.connectionString ?? "tcp:127.0.0.1:5760",
        sitl_settings: args.mode === "simulation" ? (args.sitlSettings ?? {}) : null,
        llm_config: null,
      },
    }),

  endSession: (sessionId: string) =>
    request<SessionSummary>("POST", "/session/end", { params: { session_id: sessionId } }),

  sessionSummary: (sessionId: string) =>
    request<SessionSummary>("GET", "/session/summary", { params: { session_id: sessionId } }),

  vehicleStatus: (sessionId: string) =>
    request<VehicleStatus>("GET", "/vehicle/status", { params: { session_id: sessionId } }),

  chat: (sessionId: string, message: string) =>
    request<ChatResponse>("POST", "/chat", { body: { session_id: sessionId, message } }),

  startSessionStream: async function* (args: {
    mode: "hardware" | "simulation";
    connectionString?: string;
    sitlSettings?: SITLSettings;
  }): AsyncGenerator<SessionStartEvent> {
    const res = await fetch(`${BASE_URL}/session/start/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: args.mode,
        connection_string: args.connectionString ?? "tcp:127.0.0.1:5760",
        sitl_settings: args.mode === "simulation" ? (args.sitlSettings ?? {}) : null,
        llm_config: null,
      }),
    });
    if (!res.ok || !res.body) {
      const detail = await res.text().catch(() => "");
      throw new Error(`POST /session/start/stream -> ${res.status}: ${detail}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary: number;
        // Server-sent events: one "data: {json}" frame per blank-line-terminated block
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data: "));
          if (dataLine) yield JSON.parse(dataLine.slice("data: ".length)) as SessionStartEvent;
        }
      }
    } finally {
      reader.releaseLock();
    }
  },

  rebootStream: async function* (sessionId: string): AsyncGenerator<RebootEvent> {
    const res = await fetch(`${BASE_URL}/session/reboot/stream?session_id=${encodeURIComponent(sessionId)}`, {
      method: "POST",
    });
    if (!res.ok || !res.body) {
      const detail = await res.text().catch(() => "");
      throw new Error(`POST /session/reboot/stream -> ${res.status}: ${detail}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data: "));
          if (dataLine) yield JSON.parse(dataLine.slice("data: ".length)) as RebootEvent;
        }
      }
    } finally {
      reader.releaseLock();
    }
  },

  chatStream: async function* (sessionId: string, message: string): AsyncGenerator<ChatStreamEvent> {
    const res = await fetch(`${BASE_URL}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    if (!res.ok || !res.body) {
      const detail = await res.text().catch(() => "");
      throw new Error(`POST /chat/stream -> ${res.status}: ${detail}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data: "));
          if (dataLine) {
            yield JSON.parse(dataLine.slice("data: ".length)) as ChatStreamEvent;
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },

  listProposals: (sessionId: string) =>
    request<ValidatedProposal[]>("GET", "/proposals", { params: { session_id: sessionId } }),

  confirmProposal: (sessionId: string, proposalId: string) =>
    request<ProposalDecisionResponse>("POST", `/proposals/${proposalId}/confirm`, {
      body: { session_id: sessionId },
    }),

  rejectProposal: (sessionId: string, proposalId: string, reason?: string) =>
    request<ProposalDecisionResponse>("POST", `/proposals/${proposalId}/reject`, {
      body: { session_id: sessionId, reason: reason || null },
    }),

  listPorts: () => request<PortInfo[]>("GET", "/ports"),

  submitEpisodeFeedback: (sessionId: string, episodeId: string, worked: boolean) =>
    request<{ recorded: boolean }>("POST", `/episodes/${episodeId}/feedback`, {
      body: { session_id: sessionId, worked },
    }),

  reviseProposal: (sessionId: string, proposalId: string, newValue: number) =>
    request<ValidatedProposal>("POST", `/proposals/${proposalId}/revise`, {
      body: { session_id: sessionId, new_value: newValue },
    }),

  startCompassCalibration: (sessionId: string) =>
    request<ProcedureProposal>("POST", "/procedures/compass-calibration/start", {
      params: { session_id: sessionId },
    }),

  listProcedures: (sessionId: string) =>
    request<ProcedureProposal[]>("GET", "/procedures", { params: { session_id: sessionId } }),

  confirmProcedure: (sessionId: string, procedureId: string) =>
    request<ProcedureDecisionResponse>("POST", `/procedures/${procedureId}/confirm`, {
      body: { session_id: sessionId },
    }),

  rejectProcedure: (sessionId: string, procedureId: string) =>
    request<ProcedureDecisionResponse>("POST", `/procedures/${procedureId}/reject`, {
      body: { session_id: sessionId },
    }),

  listSessions: () => request<SessionListEntry[]>("GET", "/sessions"),

  sessionTranscript: (sessionId: string) =>
    request<SessionTranscript>("GET", `/sessions/${sessionId}/transcript`),

  safetySnapshot: (sessionId: string) =>
    request<{ text: string; params: unknown[] }>("GET", "/safety-snapshot", {
      params: { session_id: sessionId },
    }),

  auditEvents: (sessionId: string) =>
    request<AuditEvent[]>("GET", "/audit", { params: { session_id: sessionId } }),

  verifyAuditChain: (sessionId: string) =>
    request<AuditVerifyResult>("GET", "/audit/verify", { params: { session_id: sessionId } }),

  rollbackChange: (sessionId: string, eventId: number) =>
    request<ValidatedProposal>("POST", `/audit/${eventId}/rollback`, { body: { session_id: sessionId } }),
};

export function telemetryWebSocketUrl(sessionId: string): string {
  const wsBase = BASE_URL.replace(/^http/, "ws");
  return `${wsBase}/telemetry?session_id=${encodeURIComponent(sessionId)}`;
}
