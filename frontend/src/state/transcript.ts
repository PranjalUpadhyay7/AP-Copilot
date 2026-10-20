import type { ChatMessage, TranscriptMessage } from "../api/types";

export function transcriptToChatMessages(messages: TranscriptMessage[]): ChatMessage[] {
  const chat: ChatMessage[] = [];
  for (const m of messages) {
    if (m.role === "user") {
      chat.push({ role: "user", text: m.content });
    // Only a turn's final reply (the one carrying turn_steps) becomes a bubble; tool-call messages live in its thinking block
    } else if (m.role === "assistant" && m.turn_steps != null && m.content !== "") {
      chat.push({
        role: "assistant",
        text: m.content,
        turnSteps: m.turn_steps.length > 0 ? m.turn_steps : undefined,
        rejectedProposals: m.rejected_proposals && m.rejected_proposals.length > 0 ? m.rejected_proposals : undefined,
      });
    }
  }
  return chat;
}
