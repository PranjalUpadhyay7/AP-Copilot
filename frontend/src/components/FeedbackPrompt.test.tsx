import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FeedbackPrompt } from "./FeedbackPrompt";

const submitFeedback = vi.fn();
vi.mock("../state/SessionStore", () => ({ useSession: () => ({ submitFeedback }) }));

describe("FeedbackPrompt", () => {
  it("sends the explicit answer once and then thanks the user", () => {
    render(<FeedbackPrompt episodeId="ep1" />);
    fireEvent.click(screen.getByText("Yes"));
    expect(submitFeedback).toHaveBeenCalledWith("ep1", true);
    expect(screen.getByText(/Thanks/)).toBeTruthy();
    expect(screen.queryByText("No")).toBeNull();
  });
});
