import { useState } from "react";
import type { TurnStep } from "../api/types";

const STAGE_LABELS: Record<string, string> = {
  thinking: "Thinking",
  tool_call: "Tool call",
  revalidation: "Re-validation",
  flight_state: "Flight-state check",
  rate_limit: "Rate limit check",
  write: "Write",
};

const STATUS_DOT: Record<TurnStep["status"], string> = {
  ok: "bg-success",
  blocked: "bg-warn-text",
  error: "bg-danger",
};

function summarize(detail: string, max = 90): string {
  const oneLine = detail.replace(/\s+/g, " ").trim();
  return oneLine.length > max ? `${oneLine.slice(0, max)}...` : oneLine;
}

function StepRow({ step }: { step: TurnStep }) {
  const [expanded, setExpanded] = useState(false);
  const label = step.tool_name ?? STAGE_LABELS[step.stage] ?? step.stage;

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 self-start rounded-[10px] border border-black/[0.12] bg-white px-3 py-1.5 text-[11.5px] text-[#5A6072] shadow-[0_2px_6px_rgba(31,36,48,0.14)] dark:border-white/10 dark:bg-white/5 dark:text-[#9AA1B1]"
      >
        <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${STATUS_DOT[step.status] ?? "bg-[#9198A8]"}`} />
        <span className="font-mono font-semibold">{label}</span>
        <span className="text-[#A2A8B8]">{summarize(step.detail)}</span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#A2A8B8"
          strokeWidth="2.5"
          className={`flex-shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {expanded && (
        <pre className="max-h-64 max-w-full overflow-auto rounded-xl bg-[#0B0E12] p-3 text-[11px] leading-relaxed text-[#DADFE6]">
          {step.detail}
        </pre>
      )}
    </div>
  );
}

export function TurnStepsView({
  steps,
  label = "Thinking",
  defaultOpen = false,
}: {
  steps: TurnStep[];
  label?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (steps.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 self-start text-[11.5px] font-semibold text-accent-1"
      >
        {open ? "Hide" : "Show"} {label.toLowerCase()} ({steps.length} step{steps.length === 1 ? "" : "s"})
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          className={`transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div className="flex flex-col gap-1.5">
          {steps.map((s, i) => (
            <StepRow key={i} step={s} />
          ))}
        </div>
      )}
    </div>
  );
}
