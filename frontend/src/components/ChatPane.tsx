import { useState } from "react";
import { useSession } from "../state/SessionStore";
import { FeedbackPrompt } from "./FeedbackPrompt";
import { Markdown } from "./Markdown";
import { TurnStepsView } from "./TurnStepsView";

export function ChatPane() {
  const { messages, sendMessage, pendingProposal, sending, rebootProgress } = useSession();
  const rebooting = rebootProgress !== null;
  const [draft, setDraft] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    void sendMessage(text);
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="flex flex-grow flex-col items-center overflow-y-auto py-7">
        <div className="flex w-full max-w-[640px] flex-col gap-4 px-6">
          {messages.length === 0 && (
            <p className="text-center text-[13.5px] text-[#5B6275] dark:text-[#9198A8]">Ask a tuning question to get started.</p>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div
                key={i}
                className="self-end max-w-[80%] rounded-[18px] rounded-br-[4px] bg-gradient-to-br from-accent-1 to-accent-2 px-4 py-3 text-[14px] leading-relaxed text-white shadow-[0_6px_16px_rgba(99,102,241,0.25)]"
              >
                {m.text}
              </div>
            ) : (
              <div key={i} className="flex max-w-[88%] flex-col gap-2 self-start">
                {}
                {m.turnSteps && <TurnStepsView steps={m.turnSteps} defaultOpen={m.text === ""} />}
                {m.text !== "" && (
                  <div className="glass rounded-[18px] rounded-bl-[4px] min-w-0 break-words px-4 py-3 text-[14px] leading-relaxed text-[#2B2F3A] shadow-[0_4px_14px_rgba(31,36,90,0.14)] dark:text-[#DADFE6]">
                    <Markdown text={m.text} />
                  </div>
                )}
                {m.episodeId && <FeedbackPrompt episodeId={m.episodeId} />}
                {}
                {m.rejectedProposals?.map((p, pi) => (
                  <div
                    key={pi}
                    className="rounded-[14px] border border-danger/20 bg-danger/[0.06] px-3.5 py-2.5 text-[12.5px] leading-relaxed text-danger"
                  >
                    <div className="font-mono font-semibold">
                      {p.param_name}: {p.current_value ?? "?"} &rarr; {p.proposed_value} -- rejected
                    </div>
                    <div className="mt-1 text-[#8a2a2a] dark:text-danger/90">
                      {p.rejection_message ?? p.rejection_reason ?? "rejected by the Validation Layer"}
                    </div>
                  </div>
                ))}
              </div>
            ),
          )}
        </div>
      </div>
      <form className="flex flex-shrink-0 justify-center px-6 pb-[22px] pt-4" onSubmit={submit}>
        <div className="glass flex w-full max-w-[640px] items-center gap-2.5 rounded-2xl py-1.5 pl-[18px] pr-1.5 shadow-[0_8px_24px_rgba(31,36,90,0.08)]">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={
              rebooting
                ? "The vehicle is rebooting..."
                : pendingProposal
                ? "Resolve the pending proposal first"
                : sending
                  ? "Waiting for a response..."
                  : "Ask about a parameter, or describe what you want to change..."
            }
            disabled={pendingProposal !== null || sending || rebooting}
            className="flex-grow bg-transparent text-[14px] text-[#1F2430] outline-none placeholder:text-[#9198A8] dark:text-[#E8EAED]"
          />
          <button
            type="submit"
            disabled={pendingProposal !== null || sending || rebooting || draft.trim() === ""}
            className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[11px] bg-gradient-to-br from-accent-1 to-accent-2 shadow-[0_4px_12px_rgba(99,102,241,0.35)] transition-transform hover:-translate-y-px disabled:opacity-50"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5">
              <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
            </svg>
          </button>
        </div>
      </form>
    </div>
  );
}
