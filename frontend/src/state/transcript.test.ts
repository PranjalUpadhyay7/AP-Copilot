import { describe, expect, it } from "vitest";
import type { TranscriptMessage, TurnStep } from "../api/types";
import { transcriptToChatMessages } from "./transcript";

const step: TurnStep = { stage: "tool_call", tool_name: "get_current_param", status: "ok", detail: "value 1500" };
const msg = (m: Partial<TranscriptMessage> & Pick<TranscriptMessage, "role" | "content">): TranscriptMessage => ({
  tool_name: null,
  ...m,
});

describe("transcriptToChatMessages", () => {
  it("restores each turn's thinking block on its final reply, like the live view", () => {
    const chat = transcriptToChatMessages([
      msg({ role: "user", content: "what is RTL_ALT_M?" }),
      msg({ role: "assistant", content: "" }),
      msg({ role: "tool", content: "value 1500", tool_name: "get_current_param" }),
      msg({ role: "assistant", content: "It is 1500 cm.", turn_steps: [step], rejected_proposals: [] }),
    ]);
    expect(chat).toHaveLength(2);
    expect(chat[0]).toEqual({ role: "user", text: "what is RTL_ALT_M?" });
    expect(chat[1]).toMatchObject({ role: "assistant", text: "It is 1500 cm.", turnSteps: [step] });
  });

  it("restores rejected-proposal blocks too and never shows intermediate prose as extra bubbles", () => {
    const rejected = { param_name: "X", accepted: false } as never;
    const chat = transcriptToChatMessages([
      msg({ role: "user", content: "set X" }),
      msg({ role: "assistant", content: "let me check" }),
      msg({ role: "assistant", content: "Nope.", turn_steps: [], rejected_proposals: [rejected] }),
    ]);
    expect(chat).toHaveLength(2);
    expect(chat[1]).toMatchObject({ text: "Nope.", rejectedProposals: [rejected] });
    expect((chat[1] as { turnSteps?: unknown }).turnSteps).toBeUndefined();
  });
});
