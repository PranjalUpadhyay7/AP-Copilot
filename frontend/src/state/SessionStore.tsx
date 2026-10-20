import { transcriptToChatMessages } from "./transcript";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { ChatMessage, ProcedureProposal, SessionStartResponse, SITLSettings, ValidatedProposal } from "../api/types";

const SESSION_ID_STORAGE_KEY = "ap-copilot-session-id";

function readStoredSessionId(): string | null {
  try {
    return localStorage.getItem(SESSION_ID_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeSessionId(id: string | null) {
  try {
    if (id) localStorage.setItem(SESSION_ID_STORAGE_KEY, id);
    else localStorage.removeItem(SESSION_ID_STORAGE_KEY);
  } catch {
  }
}

interface SessionState {
  session: SessionStartResponse | null;
  messages: ChatMessage[];
  pendingProposal: ValidatedProposal | null;
  pendingProcedure: ProcedureProposal | null;
  connecting: boolean;
  rebootProgress: { label: string; percent: number; link: "up" | "down"; startedAt: number } | null;
  rebootError: string | null;
  connectProgress: { label: string; percent: number; startedAt: number } | null;
  restoring: boolean;
  sending: boolean;
  resolvingProposal: boolean;
  error: string | null;
}

interface SessionStore extends SessionState {
  connect: (args: { mode: "hardware" | "simulation"; connectionString?: string; sitlSettings?: SITLSettings }) => Promise<void>;
  sendMessage: (text: string) => Promise<void>;
  rebootVehicle: () => Promise<void>;
  submitFeedback: (episodeId: string, worked: boolean) => Promise<void>;
  confirmProposal: () => Promise<void>;
  rejectProposal: (reason?: string) => Promise<void>;
  reviseProposal: (newValue: number) => Promise<void>;
  requestRollback: (auditEventId: number) => Promise<void>;
  startCompassCalibration: () => Promise<void>;
  confirmProcedure: () => Promise<void>;
  rejectProcedure: () => Promise<void>;
  clearError: () => void;
}

const SessionContext = createContext<SessionStore | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionStartResponse | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingProposal, setPendingProposal] = useState<ValidatedProposal | null>(null);
  const [pendingProcedure, setPendingProcedure] = useState<ProcedureProposal | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [rebootProgress, setRebootProgress] = useState<SessionState["rebootProgress"]>(null);
  const [rebootError, setRebootError] = useState<string | null>(null);
  const [connectProgress, setConnectProgress] = useState<{ label: string; percent: number; startedAt: number } | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [sending, setSending] = useState(false);
  const [resolvingProposal, setResolvingProposal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef<SessionStartResponse | null>(null);

  useEffect(() => {
    const storedId = readStoredSessionId();
    if (!storedId) {
      setRestoring(false);
      return;
    }
    void (async () => {
      try {
        const status = await api.vehicleStatus(storedId);
        const restored: SessionStartResponse = {
          session_id: status.session_id,
          vehicle_type: status.vehicle_type,
          firmware_version: status.firmware_version,
          param_count: 0,
          undocumented_param_count: 0,
          read_only: status.read_only,
          frame_label: status.frame_label,
          board_label: status.board_label,
        };
        sessionRef.current = restored;
        setSession(restored);
        try {
          const transcript = await api.sessionTranscript(storedId);
          setMessages(transcriptToChatMessages(transcript.messages));
        } catch {
        }
      } catch {
        // The session no longer exists on the backend; stop trying to reattach
        storeSessionId(null);
      } finally {
        setRestoring(false);
      }
    })();
  }, []);

  const connect = useCallback(
    async (args: { mode: "hardware" | "simulation"; connectionString?: string; sitlSettings?: SITLSettings }) => {
      setConnecting(true);
      setError(null);
      const startedAt = Date.now();
      setConnectProgress({ label: "Starting…", percent: 1, startedAt });
      try {
        for await (const event of api.startSessionStream(args)) {
          if (event.type === "progress") {
            setConnectProgress({ label: event.label, percent: event.percent, startedAt });
          } else if (event.type === "final") {
            const { type: _type, ...result } = event;
            sessionRef.current = result;
            setSession(result);
            storeSessionId(result.session_id);
          } else {
            setError(event.detail);
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setConnecting(false);
        setConnectProgress(null);
      }
    },
    [],
  );

  const rebootVehicle = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return;
    setRebootError(null);
    const startedAt = Date.now();
    setRebootProgress({ label: "Starting…", percent: 1, link: "up", startedAt });
    try {
      for await (const event of api.rebootStream(current.session_id)) {
        if (event.type === "progress") {
          setRebootProgress({ label: event.label, percent: event.percent, link: event.link, startedAt });
        } else if (event.type === "final") {
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              text: `The vehicle rebooted and reconnected to this session (${event.param_count} parameters re-read). Parameters that needed a reboot are now in effect.`,
            },
          ]);
        } else {
          setRebootError(event.detail);
        }
      }
    } catch (e) {
      setRebootError(e instanceof Error ? e.message : String(e));
    } finally {
      setRebootProgress(null);
    }
  }, []);

  const sendMessage = useCallback(async (text: string) => {
    const current = sessionRef.current;
    if (!current) return;
    setError(null);
    setSending(true);

    let index = -1;
    setMessages((prev) => {
      index = prev.length + 1;
      return [...prev, { role: "user", text }, { role: "assistant", text: "", turnSteps: [] }];
    });

    const replaceAt = (msg: ChatMessage) =>
      setMessages((prev) => prev.map((m, i) => (i === index ? msg : m)));
    const removeAt = () => setMessages((prev) => prev.filter((_, i) => i !== index));

    try {
      for await (const event of api.chatStream(current.session_id, text)) {
        if (event.type === "step") {
          setMessages((prev) =>
            prev.map((m, i) =>
              i === index && m.role === "assistant"
                ? { ...m, turnSteps: [...(m.turnSteps ?? []), event.step] }
                : m,
            ),
          );
        } else if (event.type === "final") {
          if (event.pending_proposal) {
            removeAt();
            setPendingProposal(event.pending_proposal);
          } else if (event.reply) {
            replaceAt({
              role: "assistant",
              text: event.reply,
              rejectedProposals: event.rejected_proposals.length > 0 ? event.rejected_proposals : undefined,
              turnSteps: event.turn_steps.length > 0 ? event.turn_steps : undefined,
              episodeId: event.episode_id ?? undefined,
            });
          } else {
            removeAt();
          }
        } else if (event.type === "error") {
          setError(event.detail);
          removeAt();
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      removeAt();
    } finally {
      setSending(false);
    }
  }, []);

  const submitFeedback = useCallback(async (episodeId: string, worked: boolean) => {
    const current = sessionRef.current;
    if (!current) return;
    try {
      await api.submitEpisodeFeedback(current.session_id, episodeId, worked);
    } catch {
    }
  }, []);

  const confirmProposal = useCallback(async () => {
    const current = sessionRef.current;
    if (!current || !pendingProposal?.proposal_id) return;
    setError(null);
    setResolvingProposal(true);
    try {
      const result = await api.confirmProposal(current.session_id, pendingProposal.proposal_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `[${result.outcome}] ${result.detail}`,
          turnSteps: result.steps.length > 0 ? result.steps : undefined,
          episodeId: result.outcome === "applied" ? (result.episode_id ?? undefined) : undefined,
        },
      ]);
      setPendingProposal(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResolvingProposal(false);
    }
  }, [pendingProposal]);

  const rejectProposal = useCallback(async (reason?: string) => {
    const current = sessionRef.current;
    if (!current || !pendingProposal?.proposal_id) return;
    setError(null);
    setResolvingProposal(true);
    try {
      const result = await api.rejectProposal(current.session_id, pendingProposal.proposal_id, reason);
      setMessages((prev) => [...prev, { role: "assistant", text: `[${result.outcome}] ${result.detail}` }]);
      setPendingProposal(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResolvingProposal(false);
    }
  }, [pendingProposal]);

  const reviseProposal = useCallback(async (newValue: number) => {
    const current = sessionRef.current;
    if (!current || !pendingProposal?.proposal_id) return;
    setError(null);
    try {
      const revised = await api.reviseProposal(current.session_id, pendingProposal.proposal_id, newValue);
      setPendingProposal(revised);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [pendingProposal]);

  const requestRollback = useCallback(async (auditEventId: number) => {
    const current = sessionRef.current;
    if (!current) return;
    setError(null);
    try {
      const proposal = await api.rollbackChange(current.session_id, auditEventId);
      setPendingProposal(proposal);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const startCompassCalibration = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return;
    setError(null);
    try {
      const procedure = await api.startCompassCalibration(current.session_id);
      setPendingProcedure(procedure);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const confirmProcedure = useCallback(async () => {
    const current = sessionRef.current;
    if (!current || !pendingProcedure) return;
    setError(null);
    try {
      const result = await api.confirmProcedure(current.session_id, pendingProcedure.procedure_id);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: `[${result.outcome}] ${JSON.stringify(result.detail)}` },
      ]);
      setPendingProcedure(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [pendingProcedure]);

  const rejectProcedure = useCallback(async () => {
    const current = sessionRef.current;
    if (!current || !pendingProcedure) return;
    setError(null);
    try {
      const result = await api.rejectProcedure(current.session_id, pendingProcedure.procedure_id);
      setMessages((prev) => [...prev, { role: "assistant", text: `[${result.outcome}]` }]);
      setPendingProcedure(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [pendingProcedure]);

  const value: SessionStore = {
    session,
    messages,
    pendingProposal,
    pendingProcedure,
    connecting,
    connectProgress,
    rebootProgress,
    rebootError,
    restoring,
    sending,
    resolvingProposal,
    error,
    connect,
    sendMessage,
    rebootVehicle,
    submitFeedback,
    confirmProposal,
    rejectProposal,
    reviseProposal,
    requestRollback,
    startCompassCalibration,
    confirmProcedure,
    rejectProcedure,
    clearError: () => setError(null),
  };

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionStore {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within a SessionProvider");
  return ctx;
}
