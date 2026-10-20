import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionSummary } from "./SessionSummary";
import type { SessionSummary as SessionSummaryData } from "../api/types";

vi.mock("../api/client", () => ({
  api: {
    sessionSummary: vi.fn(),
    auditEvents: vi.fn().mockResolvedValue([]),
    verifyAuditChain: vi.fn().mockResolvedValue({ intact: true, broken_at_event_id: null }),
  },
}));
vi.mock("../state/SessionStore", () => ({
  useSession: () => ({ requestRollback: vi.fn() }),
}));

import { api } from "../api/client";

afterEach(() => {
  vi.mocked(api.sessionSummary).mockReset();
});

it("a failed fetch shows a real error, not an indistinguishable permanent loading state", async () => {
  vi.mocked(api.sessionSummary).mockRejectedValue(new Error("GET /session/summary -> 500: boom"));
  render(<SessionSummary sessionId="s1" />);

  await waitFor(() => {
    expect(screen.getByText(/couldn't load the session summary/i)).toBeTruthy();
  });
  expect(screen.getByText(/boom/)).toBeTruthy();
  expect(screen.queryByText("Loading summary...")).toBeNull();
});

it("shows the loading state only before the fetch resolves, then the real summary on success", async () => {
  vi.mocked(api.sessionSummary).mockResolvedValue({
    session_id: "s1",
    started_at: "2026-10-18T00:00:00Z",
    ended_at: null,
    applied_count: 2,
    rejected_count: 1,
    pending_count: 0,
    reboot_required_params: [],
    safety_snapshot_text: "",
    safety_snapshot_params: [],
  });
  render(<SessionSummary sessionId="s1" />);

  expect(screen.getByText("Loading summary...")).toBeTruthy();
  await waitFor(() => {
    expect(screen.getByText("2 applied")).toBeTruthy();
  });
  expect(screen.queryByText("Loading summary...")).toBeNull();
});

describe("re-mounting with a different session_id", () => {
  it("resets a prior error before the new fetch resolves", async () => {
    vi.mocked(api.sessionSummary).mockRejectedValueOnce(new Error("boom"));
    const { rerender } = render(<SessionSummary sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByText(/boom/)).toBeTruthy();
    });

    let resolveSecond: (value: SessionSummaryData) => void = () => {};
    vi.mocked(api.sessionSummary).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveSecond = resolve;
      }),
    );
    rerender(<SessionSummary sessionId="s2" />);

    expect(screen.queryByText(/boom/)).toBeNull();
    expect(screen.getByText("Loading summary...")).toBeTruthy();

    resolveSecond({
      session_id: "s2",
      started_at: "2026-10-18T00:00:00Z",
      ended_at: null,
      applied_count: 0,
      rejected_count: 0,
      pending_count: 0,
      reboot_required_params: [],
      safety_snapshot_text: "",
      safety_snapshot_params: [],
    });
    await waitFor(() => {
      expect(screen.getByText("0 applied")).toBeTruthy();
    });
  });
});
