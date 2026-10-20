import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RebootDialog } from "./RebootDialog";

const state = {
  rebootVehicle: vi.fn(),
  rebootProgress: null as null | { label: string; percent: number; link: "up" | "down"; startedAt: number },
  rebootError: null as string | null,
};
vi.mock("../state/SessionStore", () => ({ useSession: () => state }));

describe("RebootDialog", () => {
  beforeEach(() => {
    state.rebootVehicle.mockReset();
    state.rebootProgress = null;
    state.rebootError = null;
  });

  it("asks for confirmation first and only reboots on the explicit button", () => {
    const onClose = vi.fn();
    render(<RebootDialog onClose={onClose} />);
    expect(screen.getByText(/disarmed/)).toBeTruthy();
    expect(state.rebootVehicle).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Reboot now"));
    expect(state.rebootVehicle).toHaveBeenCalledTimes(1);
  });

  it("cancel closes without rebooting", () => {
    const onClose = vi.fn();
    render(<RebootDialog onClose={onClose} />);
    fireEvent.click(screen.getByText("Cancel"));
    expect(onClose).toHaveBeenCalled();
    expect(state.rebootVehicle).not.toHaveBeenCalled();
  });

  it("shows the live link state and progress while rebooting", () => {
    state.rebootProgress = { label: "Waiting for the vehicle to come back (5 s)…", percent: 40, link: "down", startedAt: Date.now() };
    const { rerender } = render(<RebootDialog onClose={() => {}} />);
    fireEvent.click(screen.getByText("Reboot now"));
    rerender(<RebootDialog onClose={() => {}} />);
    expect(screen.getByTestId("link-badge").textContent).toMatch(/down/);
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("40");
  });

  it("shows a refusal (e.g. armed) verbatim", () => {
    state.rebootError = "the vehicle is armed -- disarm it before rebooting";
    render(<RebootDialog onClose={() => {}} />);
    expect(screen.getByText(/vehicle is armed/)).toBeTruthy();
  });
});
