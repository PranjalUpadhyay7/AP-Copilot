import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionProvider, useSession } from "./SessionStore";

vi.mock("../api/client", () => ({
  api: {
    vehicleStatus: vi.fn(),
    sessionTranscript: vi.fn(),
    confirmProposal: vi.fn(),
    rollbackChange: vi.fn(),
  },
}));

import { api } from "../api/client";
import type { ValidatedProposal } from "../api/types";

const STORAGE_KEY = "ap-copilot-session-id";

function Probe() {
  const { session, restoring, error, pendingProposal, confirmProposal, requestRollback, clearError } = useSession();
  return (
    <div>
      <span data-testid="restoring">{String(restoring)}</span>
      <span data-testid="session-id">{session?.session_id ?? "none"}</span>
      <span data-testid="error">{error ?? "none"}</span>
      <button onClick={() => void requestRollback(1)}>propose</button>
      <button onClick={() => void confirmProposal()}>confirm</button>
      <button onClick={clearError}>dismiss</button>
      <span data-testid="pending">{pendingProposal ? "yes" : "no"}</span>
    </div>
  );
}

function _fakeProposal(): ValidatedProposal {
  return {
    param_name: "ATC_ANG_RLL_P", current_value: 4.5, proposed_value: 6.0, reason: "t",
    accepted: true, rejection_reason: null, rejection_message: null, criticality: "critical",
    dependency_warnings: [], reboot_required: false, definition: null, proposal_id: "p1",
  };
}

function renderProbe() {
  return render(
    <SessionProvider>
      <Probe />
    </SessionProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.vehicleStatus).mockReset();
  vi.mocked(api.sessionTranscript).mockReset();
});

afterEach(() => {
  localStorage.clear();
});

describe("SessionStore reconnect-on-mount", () => {
  it("stays disconnected when nothing was saved", async () => {
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("restoring").textContent).toBe("false"));
    expect(screen.getByTestId("session-id").textContent).toBe("none");
    expect(api.vehicleStatus).not.toHaveBeenCalled();
  });

  it("reattaches to a still-live session found via GET /vehicle/status", async () => {
    localStorage.setItem(STORAGE_KEY, "old-session-123");
    vi.mocked(api.vehicleStatus).mockResolvedValue({
      session_id: "old-session-123",
      connected: true,
      vehicle_type: "ArduCopter",
      firmware_version: "4.6.0",
      read_only: false,
    });
    vi.mocked(api.sessionTranscript).mockResolvedValue({ session_id: "old-session-123", messages: [] });

    await act(async () => {
      renderProbe();
    });

    await waitFor(() => expect(screen.getByTestId("restoring").textContent).toBe("false"));
    expect(screen.getByTestId("session-id").textContent).toBe("old-session-123");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("old-session-123");
  });

  it("clears the stored id and stays disconnected when the session is actually gone", async () => {
    localStorage.setItem(STORAGE_KEY, "long-gone-session");
    vi.mocked(api.vehicleStatus).mockRejectedValue(new Error("POST -> 404"));

    await act(async () => {
      renderProbe();
    });

    await waitFor(() => expect(screen.getByTestId("restoring").textContent).toBe("false"));
    expect(screen.getByTestId("session-id").textContent).toBe("none");
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("still reattaches the session even if restoring the transcript fails", async () => {
    localStorage.setItem(STORAGE_KEY, "session-with-bad-transcript");
    vi.mocked(api.vehicleStatus).mockResolvedValue({
      session_id: "session-with-bad-transcript",
      connected: true,
      vehicle_type: "ArduCopter",
      firmware_version: "4.6.0",
      read_only: false,
    });
    vi.mocked(api.sessionTranscript).mockRejectedValue(new Error("boom"));

    await act(async () => {
      renderProbe();
    });

    await waitFor(() => expect(screen.getByTestId("restoring").textContent).toBe("false"));
    expect(screen.getByTestId("session-id").textContent).toBe("session-with-bad-transcript");
  });
});

describe("SessionStore error visibility", () => {
  async function connectedProbe() {
    localStorage.setItem(STORAGE_KEY, "connected-session");
    vi.mocked(api.vehicleStatus).mockResolvedValue({
      session_id: "connected-session", connected: true,
      vehicle_type: "ArduCopter", firmware_version: "4.6.0", read_only: false,
    });
    vi.mocked(api.sessionTranscript).mockResolvedValue({ session_id: "connected-session", messages: [] });

    await act(async () => {
      renderProbe();
    });
    await waitFor(() => expect(screen.getByTestId("restoring").textContent).toBe("false"));
  }

  it("a failed confirmProposal sets a visible error, not silence", async () => {
    vi.mocked(api.rollbackChange).mockResolvedValue(_fakeProposal());
    vi.mocked(api.confirmProposal).mockRejectedValue(new Error("POST -> 502: live-param refresh timed out"));
    await connectedProbe();

    await act(async () => {
      screen.getByText("propose").click();
    });
    await waitFor(() => expect(screen.getByTestId("pending").textContent).toBe("yes"));

    await act(async () => {
      screen.getByText("confirm").click();
    });
    await waitFor(() => expect(screen.getByTestId("error").textContent).toContain("live-param refresh timed out"));
    expect(screen.getByTestId("pending").textContent).toBe("yes");
  });

  it("clearError resets the visible error to none", async () => {
    vi.mocked(api.rollbackChange).mockResolvedValue(_fakeProposal());
    vi.mocked(api.confirmProposal).mockRejectedValue(new Error("boom"));
    await connectedProbe();

    await act(async () => {
      screen.getByText("propose").click();
    });
    await act(async () => {
      screen.getByText("confirm").click();
    });
    await waitFor(() => expect(screen.getByTestId("error").textContent).not.toBe("none"));

    await act(async () => {
      screen.getByText("dismiss").click();
    });
    expect(screen.getByTestId("error").textContent).toBe("none");
  });
});
