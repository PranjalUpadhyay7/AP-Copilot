import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SessionSummary as SessionSummaryData } from "../api/types";
import { AuditLogPanel } from "./AuditLogPanel";
import { SafetySnapshotView } from "./SafetySnapshotView";

export function SessionSummary({ sessionId }: { sessionId: string }) {
  const [summary, setSummary] = useState<SessionSummaryData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    setSummary(null);
    api.sessionSummary(sessionId)
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [sessionId]);

  if (error) {
    return (
      <p className="px-6 py-4 text-[13px] text-danger">Couldn't load the session summary: {error}</p>
    );
  }
  if (!summary) return <p className="px-6 py-4 text-[13px] text-[#5B6275] dark:text-[#9198A8]">Loading summary...</p>;

  return (
    <div className="glass flex-shrink-0 border-t border-black/[0.12] px-6 py-5 dark:border-white/10">
      <h3 className="m-0 mb-3 text-[13px] font-bold uppercase tracking-wide text-[#5B6275] dark:text-[#9198A8]">Session summary</h3>
      <div className="mb-3 flex gap-3">
        <span className="rounded-full bg-success/10 px-3 py-1.5 text-[12px] font-semibold text-success">
          {summary.applied_count} applied
        </span>
        <span className="rounded-full bg-danger/10 px-3 py-1.5 text-[12px] font-semibold text-danger">
          {summary.rejected_count} rejected
        </span>
        <span className="rounded-full bg-black/[0.10] px-3 py-1.5 text-[12px] font-semibold text-[#4B5164] dark:bg-white/10 dark:text-[#B7BFCA]">
          {summary.pending_count} pending
        </span>
      </div>
      {summary.reboot_required_params.length > 0 && (
        <p className="m-0 mb-3 text-[12.5px] font-medium text-warn-text">
          Reboot required for: {summary.reboot_required_params.join(", ")}
        </p>
      )}
      <SafetySnapshotView params={summary.safety_snapshot_params} text={summary.safety_snapshot_text} />
      <AuditLogPanel sessionId={sessionId} />
    </div>
  );
}
