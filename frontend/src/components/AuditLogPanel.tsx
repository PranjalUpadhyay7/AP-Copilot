import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useSession } from "../state/SessionStore";
import type { AuditEvent } from "../api/types";

export function AuditLogPanel({ sessionId }: { sessionId: string }) {
  const { requestRollback } = useSession();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [chainIntact, setChainIntact] = useState<boolean | null>(null);

  const refresh = () => {
    api.auditEvents(sessionId).then(setEvents).catch(() => setEvents([]));
    api.verifyAuditChain(sessionId).then((r) => setChainIntact(r.intact)).catch(() => setChainIntact(null));
  };

  useEffect(refresh, [sessionId]);

  const applied = (events ?? []).filter((e) => e.event_type === "apply");

  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="m-0 text-[12px] font-bold uppercase tracking-wide text-[#5B6275] dark:text-[#9198A8]">Applied changes</h4>
        <div className="flex items-center gap-2">
          {chainIntact === false && (
            <span className="rounded-full bg-danger/15 px-2.5 py-1 text-[11px] font-semibold text-danger">
              Audit log integrity check failed
            </span>
          )}
          <button
            type="button"
            onClick={refresh}
            className="text-[11px] font-semibold text-accent-1"
            aria-label="Refresh applied changes"
          >
            Refresh
          </button>
        </div>
      </div>

      {events === null ? (
        <p className="m-0 text-[12.5px] text-[#5B6275] dark:text-[#9198A8]">Loading…</p>
      ) : applied.length === 0 ? (
        <p className="m-0 text-[12.5px] text-[#5B6275] dark:text-[#9198A8]">No changes applied yet.</p>
      ) : (
        <ul className="m-0 flex flex-col gap-1.5 p-0">
          {applied.map((e) => (
            <li
              key={e.id}
              className="flex items-center justify-between gap-3 rounded-xl border border-black/[0.12] bg-white/60 px-3 py-2 font-mono text-[12px] dark:border-white/10 dark:bg-white/5"
            >
              <span>
                {e.param_name}: {e.before_value ?? "?"} &rarr; {e.after_value ?? "?"}
              </span>
              <button
                type="button"
                onClick={() => void requestRollback(e.id)}
                className="flex-shrink-0 rounded-lg border border-black/20 bg-white px-2.5 py-1 text-[11px] font-semibold text-[#4B5164] hover:bg-[#F5F6FA] dark:border-white/10 dark:bg-white/10 dark:text-[#B7BFCA]"
              >
                Revert
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
