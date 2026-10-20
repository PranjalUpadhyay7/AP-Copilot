import { useEffect, useState } from "react";
import type { ValidatedProposal } from "../api/types";

// Critical changes cannot be confirmed instantly, so a reflexive double-click cannot apply one
const CRITICAL_CONFIRM_COOLDOWN_MS = 3000;
export function ConfirmationModal({
  proposal,
  resolving = false,
  onConfirm,
  onReject,
  onRevise,
}: {
  proposal: ValidatedProposal;
  resolving?: boolean;
  onConfirm: () => void;
  onReject: (reason: string) => void;
  onRevise?: (newValue: number) => void;
}) {
  const isCritical = proposal.criticality === "critical";
  const [detailsOpen, setDetailsOpen] = useState(isCritical);
  const [confirmTypeIn, setConfirmTypeIn] = useState("");
  const [cooldownElapsed, setCooldownElapsed] = useState(!isCritical);
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  useEffect(() => {
    if (!isCritical) return;
    setCooldownElapsed(false);
    const timer = setTimeout(() => setCooldownElapsed(true), CRITICAL_CONFIRM_COOLDOWN_MS);
    return () => clearTimeout(timer);
  }, [isCritical, proposal.proposal_id]);

  const canConfirm =
    proposal.accepted && cooldownElapsed && (!isCritical || confirmTypeIn.trim() === proposal.param_name);

  const badgeClass =
    proposal.criticality === "critical"
      ? "bg-danger/15 text-danger dark:bg-danger/20"
      : proposal.criticality === "medium"
        ? "bg-warn-text/15 text-warn-text"
        : "bg-black/[0.10] text-[#4B5164] dark:bg-white/10 dark:text-[#B7BFCA]";
  const badgeLabel =
    proposal.criticality === "critical" ? "Flight-safety critical" : proposal.criticality === "medium" ? "Medium" : "Low";

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-6" role="dialog" aria-modal="true">
      <div className="glass w-full max-w-lg rounded-[22px] p-7 shadow-[0_30px_70px_rgba(31,36,90,0.25)] text-[#1F2430] dark:text-[#E8EAED]">
        <div className="mb-4 flex items-center justify-between gap-3">
          {isCritical && (
            <div className="flex h-[34px] w-[34px] flex-shrink-0 items-center justify-center rounded-[11px] bg-gradient-to-br from-[#FFE4BE] to-[#FFD199] shadow-[0_4px_12px_rgba(230,158,60,0.25)]">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#B8791A" strokeWidth="2">
                <path d="M12 9v4M12 17h.01M10.3 3.9L2.5 17.1a1.5 1.5 0 001.3 2.4h16.4a1.5 1.5 0 001.3-2.4L13.7 3.9a1.5 1.5 0 00-2.6 0z" />
              </svg>
            </div>
          )}
          <span className="font-mono flex-grow text-[15px] font-bold">
            {proposal.param_name}: {proposal.current_value ?? "?"} &rarr; {proposal.proposed_value}
          </span>
          {proposal.criticality && (
            <span className={`flex-shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${badgeClass}`}>
              {badgeLabel}
            </span>
          )}
        </div>

        {!proposal.accepted ? (
          <p className="m-0 mb-3 text-[13.5px] text-danger">
            Rejected: {proposal.rejection_message ?? proposal.rejection_reason}
          </p>
        ) : (
          <p className="m-0 mb-3 text-[13.5px] leading-relaxed text-[#4B5164] dark:text-[#B7BFCA]">{proposal.reason}</p>
        )}

        {proposal.accepted && (
          <>
            <button
              className="mb-1 flex items-center gap-1.5 bg-transparent p-0 text-[12.5px] font-semibold text-accent-1"
              onClick={() => setDetailsOpen((v) => !v)}
            >
              {detailsOpen ? "Hide" : "Show"} why / details
            </button>
            {detailsOpen && (
              <div className="mb-3 rounded-2xl bg-white p-4 text-[12.5px] leading-relaxed text-[#4B5164] shadow-[0_4px_14px_rgba(31,36,90,0.14)] dark:bg-white/5 dark:text-[#B7BFCA]">
                {proposal.definition?.description && <p className="m-0 mb-1.5">{proposal.definition.description}</p>}
                {proposal.definition?.unit && <p className="m-0 mb-1.5">Unit: {proposal.definition.unit}</p>}
                {(proposal.definition?.min_value != null || proposal.definition?.max_value != null) && (
                  <p className="m-0 mb-1.5">
                    Range: {proposal.definition?.min_value ?? "-"} to {proposal.definition?.max_value ?? "-"}
                  </p>
                )}
                {proposal.reboot_required && (
                  <p className="m-0 mb-1.5 font-medium text-warn-text">Reboot required to take effect.</p>
                )}
                {proposal.dependency_warnings.map((w, i) => (
                  <p key={i} className="m-0 mb-1.5 font-medium text-warn-text">
                    {w.message} (related: {w.related_params.join(", ")})
                  </p>
                ))}
                {proposal.definition?.doc_url && (
                  <p className="m-0">
                    <a href={proposal.definition.doc_url} target="_blank" rel="noreferrer" className="font-semibold text-accent-1">
                      ArduPilot documentation for {proposal.param_name}
                    </a>
                  </p>
                )}
                {}
                {proposal.definition?.github_source_url && (
                  <p className="m-0 mt-1">
                    <a href={proposal.definition.github_source_url} target="_blank" rel="noreferrer" className="font-semibold text-accent-1">
                      View {proposal.param_name}'s source on GitHub
                    </a>
                  </p>
                )}
              </div>
            )}
          </>
        )}

        {proposal.accepted && onRevise && proposal.definition?.values && (
          <div className="mb-3">
            <label className="flex flex-col gap-1.5 text-[12.5px] text-[#4B5164] dark:text-[#B7BFCA]">
              Other valid values for {proposal.param_name}:
              <select
                value={String(proposal.proposed_value)}
                onChange={(e) => onRevise(Number(e.target.value))}
                className="rounded-lg border border-[#C3C9D6] bg-white px-2.5 py-2 font-mono text-[13px] text-[#1F2430] outline-none dark:border-white/10 dark:bg-white/5 dark:text-[#E8EAED]"
              >
                {Object.entries(proposal.definition.values).map(([value, label]) => (
                  <option key={value} value={value}>
                    {value} — {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {proposal.accepted && isCritical && (
          <div className="mb-1 rounded-2xl bg-gradient-to-br from-[#FFF9F0] to-[#FFF5EA] p-4 dark:from-warn-text/10 dark:to-warn-text/5">
            <label className="flex flex-col gap-1.5 text-[11.5px] font-semibold text-warn-text">
              Type <strong>{proposal.param_name}</strong> to confirm this critical change:
              <input
                value={confirmTypeIn}
                onChange={(e) => setConfirmTypeIn(e.target.value)}
                placeholder={proposal.param_name}
                className="rounded-lg border border-[#F0DAB2] bg-white px-3 py-2.5 font-mono text-[13px] text-[#1F2430] outline-none dark:bg-white/10 dark:text-[#E8EAED]"
              />
            </label>
            {!cooldownElapsed && (
              <p className="m-0 mt-2 text-[11px] text-warn-text">
                Take a moment to review this before confirming.
              </p>
            )}
          </div>
        )}

        {}
        {rejecting ? (
          <div className="mt-4">
            <label className="flex flex-col gap-1.5 text-[12.5px] text-[#4B5164] dark:text-[#B7BFCA]">
              Why are you rejecting this? (optional)
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                autoFocus
                rows={2}
                className="rounded-lg border border-[#C3C9D6] bg-white px-2.5 py-2 text-[13px] text-[#1F2430] outline-none dark:border-white/10 dark:bg-white/5 dark:text-[#E8EAED]"
              />
            </label>
            <div className="mt-2.5 flex gap-2.5">
              <button
                disabled={resolving}
                onClick={() => onReject(rejectReason.trim())}
                className="flex-1 rounded-xl bg-danger py-3 text-[13.5px] font-bold text-white disabled:cursor-not-allowed disabled:opacity-45"
              >
                {resolving ? "Rejecting…" : "Confirm Reject"}
              </button>
              <button
                disabled={resolving}
                onClick={() => setRejecting(false)}
                className="flex-1 rounded-xl border border-black/20 bg-white py-3 text-[13.5px] font-semibold text-[#4B5164] hover:bg-[#F5F6FA] disabled:cursor-not-allowed disabled:opacity-45 dark:border-white/10 dark:bg-white/5 dark:text-[#B7BFCA]"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : resolving ? (
          <div className="mt-4 flex items-center justify-center gap-2.5 py-3 text-[13.5px] font-semibold text-[#4B5164] dark:text-[#B7BFCA]">
            <span className="h-4 w-4 flex-shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent" />
            Submitting…
          </div>
        ) : (
          <div className="mt-4 flex gap-2.5">
            {proposal.accepted ? (
              <>
                <button
                  disabled={!canConfirm}
                  onClick={onConfirm}
                  className="flex-1 rounded-xl bg-gradient-to-br from-warn-1 to-warn-2 py-3 text-[13.5px] font-bold text-white shadow-[0_8px_20px_rgba(230,146,60,0.35)] disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none"
                >
                  Confirm
                </button>
                <button
                  onClick={() => setRejecting(true)}
                  className="flex-1 rounded-xl border border-black/20 bg-white py-3 text-[13.5px] font-semibold text-[#4B5164] hover:bg-[#F5F6FA] dark:border-white/10 dark:bg-white/5 dark:text-[#B7BFCA]"
                >
                  Reject
                </button>
              </>
            ) : (
              <button
                onClick={() => onReject("")}
                className="flex-1 rounded-xl border border-black/20 bg-white py-3 text-[13.5px] font-semibold text-[#4B5164] hover:bg-[#F5F6FA] dark:border-white/10 dark:bg-white/5 dark:text-[#B7BFCA]"
              >
                OK
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
