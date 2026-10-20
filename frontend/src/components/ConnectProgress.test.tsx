import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConnectProgress } from "./ConnectProgress";

describe("ConnectProgress", () => {
  it("shows the step, a progress bar value and the one-time download note", () => {
    render(<ConnectProgress label="Downloading ArduPilot source for ArduCopter 4.6.3 (40%)" percent={43} startedAt={Date.now()} />);
    expect(screen.getByText(/Downloading ArduPilot source/)).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("43");
    expect(screen.getByText(/First time with this firmware/)).toBeTruthy();
  });

  it("omits the download note for ordinary steps", () => {
    render(<ConnectProgress label="Reading the firmware version…" percent={20} startedAt={Date.now()} />);
    expect(screen.queryByText(/First time with this firmware/)).toBeNull();
  });
});
