import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { SessionListEntry, TranscriptMessage } from "../api/types";

function summarizeToolResult(toolName: string | null, content: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    return content.length > 140 ? `${content.slice(0, 140)}...` : content;
  }

  if (Array.isArray(parsed)) {
    if (parsed.length === 0) return "no results";
    const first = parsed[0];
    if (first && typeof first === "object" && "name" in first) {
      const names = parsed.slice(0, 3).map((p) => (p as { name: string }).name);
      const suffix = parsed.length > 3 ? `, +${parsed.length - 3} more` : "";
      return `${parsed.length} match(es): ${names.join(", ")}${suffix}`;
    }
    if (first && typeof first === "object" && "source" in first) {
      return `${parsed.length} result(s)`;
    }
    return `${parsed.length} item(s)`;
  }

  if (parsed && typeof parsed === "object") {
    const obj = parsed as Record<string, unknown>;
    if (toolName === "get_current_param" && "name" in obj) {
      return `${obj.name} = ${obj.current_value}`;
    }
    if ("name" in obj && "current_value" in obj) {
      return `${obj.name} = ${obj.current_value}`;
    }
    const keys = Object.keys(obj);
    return keys.length > 0 ? `{ ${keys.slice(0, 4).join(", ")}${keys.length > 4 ? ", ..." : ""} }` : "{}";
  }

  return String(parsed);
}

function ToolCallChip({ message }: { message: TranscriptMessage }) {
  const [expanded, setExpanded] = useState(false);
  let pretty = message.content;
  try {
    pretty = JSON.stringify(JSON.parse(message.content), null, 2);
  } catch {
  }

  return (
    <div className="flex flex-col gap-1.5 self-start">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1.5 self-start rounded-[10px] border border-black/[0.12] bg-white px-3 py-1.5 text-[11.5px] text-[#5A6072] shadow-[0_2px_6px_rgba(31,36,48,0.14)] dark:border-white/10 dark:bg-white/5 dark:text-[#9AA1B1]"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#6366F1" strokeWidth="2">
          <circle cx="11" cy="11" r="7" />
          <path d="M21 21l-4.3-4.3" />
        </svg>
        <span className="font-mono">{message.tool_name ?? "tool"}</span>
        <span className="text-[#A2A8B8]">→ {summarizeToolResult(message.tool_name, message.content)}</span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#A2A8B8"
          strokeWidth="2.5"
          className={`transition-transform ${expanded ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {expanded && (
        <pre className="max-h-64 max-w-full overflow-auto rounded-xl bg-[#0B0E12] p-3 text-[11px] leading-relaxed text-[#DADFE6]">
          {pretty}
        </pre>
      )}
    </div>
  );
}

function groupTranscript(messages: TranscriptMessage[]): TranscriptMessage[][] {
  const groups: TranscriptMessage[][] = [];
  for (const m of messages) {
    const last = groups[groups.length - 1];
    if (last && last[0].role === m.role && (m.role === "tool" || m.role === "assistant")) {
      last.push(m);
    } else {
      groups.push([m]);
    }
  }
  return groups;
}

function TranscriptView({ messages }: { messages: TranscriptMessage[] }) {
  const groups = useMemo(() => groupTranscript(messages), [messages]);

  return (
    <div className="flex w-full max-w-[620px] flex-col gap-4 px-6">
      {groups.map((group, gi) => {
        const role = group[0].role;
        if (role === "user") {
          return (
            <div
              key={gi}
              className="self-end max-w-[78%] rounded-[18px] rounded-br-[4px] bg-gradient-to-br from-accent-1 to-accent-2 px-4 py-2.5 text-[13.5px] leading-relaxed text-white shadow-[0_6px_16px_rgba(99,102,241,0.2)]"
            >
              {group[0].content}
            </div>
          );
        }
        return (
          <div key={gi} className="flex max-w-[88%] flex-col gap-2 self-start">
            {group.map((m, mi) =>
              m.role === "tool" ? (
                <ToolCallChip key={mi} message={m} />
              ) : (
                <div
                  key={mi}
                  className="glass rounded-[18px] rounded-bl-[4px] px-4 py-2.5 text-[13.5px] leading-relaxed text-[#2B2F3A] shadow-[0_4px_14px_rgba(31,36,90,0.14)] dark:text-[#DADFE6]"
                >
                  {m.content}
                </div>
              ),
            )}
          </div>
        );
      })}
    </div>
  );
}

export function SessionHistoryPanel({ onClose }: { onClose: () => void }) {
  const [sessions, setSessions] = useState<SessionListEntry[] | null>(null);
  const [openSessionId, setOpenSessionId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptMessage[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.listSessions().then(setSessions).catch(() => setSessions([]));
  }, []);

  useEffect(() => {
    if (!openSessionId) {
      setTranscript(null);
      return;
    }
    api.sessionTranscript(openSessionId).then((t) => setTranscript(t.messages)).catch(() => setTranscript([]));
  }, [openSessionId]);

  const filtered = useMemo(() => {
    if (!sessions) return null;
    const q = query.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter(
      (s) => s.vehicle_type.toLowerCase().includes(q) || s.firmware_version.toLowerCase().includes(q),
    );
  }, [sessions, query]);

  const openSession = sessions?.find((s) => s.session_id === openSessionId) ?? null;

  return (
    <div className="fixed inset-0 z-[100] flex flex-col bg-app" role="dialog" aria-modal="true">
      <div className="glass flex flex-shrink-0 items-center justify-between px-6 py-4 shadow-[0_1px_0_rgba(31,36,48,0.05)]">
        <div className="flex items-center gap-2.5">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-[#1F2430] dark:text-[#E8EAED]">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
          <span className="text-[15px] font-semibold text-[#1F2430] dark:text-[#E8EAED]">Session history</span>
        </div>
        <button
          onClick={onClose}
          className="rounded-[9px] border border-black/[0.12] bg-white px-4 py-2 text-[12.5px] text-[#5A6072] dark:border-white/10 dark:bg-white/5 dark:text-[#9AA1B1]"
        >
          Close
        </button>
      </div>

      <div className="flex min-h-0 flex-grow">
        <div className="flex w-[340px] flex-shrink-0 flex-col border-r border-black/[0.12] dark:border-white/10">
          <div className="p-4 pb-2.5">
            <div className="flex items-center gap-2 rounded-[11px] border border-black/[0.12] bg-white px-3.5 py-2.5 shadow-[0_2px_8px_rgba(31,36,90,0.14)] dark:border-white/10 dark:bg-white/5">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#9198A8" strokeWidth="2">
                <circle cx="11" cy="11" r="7" />
                <path d="M21 21l-4.3-4.3" />
              </svg>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by vehicle or firmware..."
                className="flex-grow bg-transparent text-[12.5px] text-[#1F2430] outline-none placeholder:text-[#9198A8] dark:text-[#E8EAED]"
              />
            </div>
          </div>

          <div className="flex flex-grow flex-col gap-1 overflow-y-auto p-3 pt-1">
            {filtered === null && <p className="px-2 text-[13px] text-[#5B6275] dark:text-[#9198A8]">Loading sessions...</p>}
            {filtered !== null && filtered.length === 0 && (
              <p className="px-2 text-[13px] text-[#5B6275] dark:text-[#9198A8]">No sessions match.</p>
            )}
            {filtered?.map((s) => (
              <button
                key={s.session_id}
                onClick={() => setOpenSessionId(s.session_id)}
                className={`flex flex-col gap-1 rounded-xl px-3.5 py-3 text-left transition-colors ${
                  s.session_id === openSessionId
                    ? "bg-white shadow-[0_4px_14px_rgba(31,36,90,0.08)] dark:bg-white/10"
                    : "hover:bg-white dark:hover:bg-white/5"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-semibold text-[#1F2430] dark:text-[#E8EAED]">{s.vehicle_type}</span>
                  {s.read_only && (
                    <span className="rounded-md bg-[#FFF1DE] px-1.5 py-0.5 text-[9.5px] font-semibold text-warn-text dark:bg-warn-text/15">
                      read-only
                    </span>
                  )}
                </div>
                <div className="text-[11.5px] text-[#565D70] dark:text-[#9198A8]">
                  {s.firmware_version} · {new Date(s.started_at).toLocaleString()}
                  {!s.ended_at && " · still open"}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="flex min-h-0 flex-grow flex-col">
          {!openSession ? (
            <div className="flex flex-grow items-center justify-center text-[13.5px] text-[#5B6275] dark:text-[#9198A8]">
              Select a session to view its transcript.
            </div>
          ) : (
            <>
              <div className="flex flex-shrink-0 items-center justify-between border-b border-black/[0.12] px-7 py-3.5 dark:border-white/10">
                <div>
                  <div className="text-[14px] font-semibold text-[#1F2430] dark:text-[#E8EAED]">
                    {openSession.vehicle_type} · {openSession.firmware_version}
                  </div>
                  <div className="text-[11.5px] text-[#5B6275] dark:text-[#9198A8]">
                    {new Date(openSession.started_at).toLocaleString()}
                    {openSession.ended_at ? ` – ${new Date(openSession.ended_at).toLocaleString()}` : " (still open)"}
                    {" · read-only replay"}
                  </div>
                </div>
                <span className="flex items-center gap-1.5 rounded-full border border-black/[0.12] bg-white px-2.5 py-1 text-[10.5px] text-[#565D70] dark:border-white/10 dark:bg-white/5 dark:text-[#9198A8]">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#9198A8" strokeWidth="2.5">
                    <rect x="4" y="10" width="16" height="10" rx="2" />
                    <path d="M8 10V7a4 4 0 018 0v3" />
                  </svg>
                  past session, can't be resumed
                </span>
              </div>

              <div className="flex flex-grow flex-col items-center overflow-y-auto py-6">
                {transcript === null && <p className="text-[13.5px] text-[#5B6275] dark:text-[#9198A8]">Loading transcript...</p>}
                {transcript !== null && transcript.length === 0 && (
                  <p className="text-[13.5px] text-[#5B6275] dark:text-[#9198A8]">No messages recorded for this session.</p>
                )}
                {transcript !== null && transcript.length > 0 && <TranscriptView messages={transcript} />}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
