import { act, render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmationModal } from "./ConfirmationModal";
import type { ParamDefinition, ValidatedProposal } from "../api/types";

function makeDefinition(overrides: Partial<ParamDefinition> = {}): ParamDefinition {
  return {
    name: "ATC_ANG_RLL_P",
    vehicle_types: ["ArduCopter"],
    firmware_version: "4.6.0",
    description: "Roll axis angle controller P gain.",
    unit: null,
    min_value: null,
    max_value: null,
    increment: null,
    bitmask: null,
    reboot_required: false,
    values: null,
    doc_url: null,
    github_source_url: null,
    ...overrides,
  };
}

function makeProposal(overrides: Partial<ValidatedProposal> = {}): ValidatedProposal {
  return {
    param_name: "ATC_ANG_RLL_P",
    current_value: 4.5,
    proposed_value: 6.0,
    reason: "tighten roll response",
    accepted: true,
    rejection_reason: null,
    rejection_message: null,
    criticality: "low",
    dependency_warnings: [],
    reboot_required: false,
    definition: null,
    proposal_id: "abc123",
    ...overrides,
  };
}

describe("ConfirmationModal", () => {
  it("allows confirming a low-criticality proposal immediately", () => {
    const onConfirm = vi.fn();
    render(<ConfirmationModal proposal={makeProposal()} onConfirm={onConfirm} onReject={vi.fn()} />);

    fireEvent.click(screen.getByText("Confirm"));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("blocks confirming a critical-tier proposal until the param name is typed in and the cooldown has elapsed", () => {
    vi.useFakeTimers();
    const onConfirm = vi.fn();
    render(
      <ConfirmationModal
        proposal={makeProposal({ criticality: "critical" })}
        onConfirm={onConfirm}
        onReject={vi.fn()}
      />,
    );

    const confirmButton = screen.getByText("Confirm") as HTMLButtonElement;
    expect(confirmButton.disabled).toBe(true);

    fireEvent.click(confirmButton);
    expect(onConfirm).not.toHaveBeenCalled();

    const input = screen.getByPlaceholderText("ATC_ANG_RLL_P");
    fireEvent.change(input, { target: { value: "ATC_ANG_RLL_P" } });

    expect(confirmButton.disabled).toBe(true);
    fireEvent.click(confirmButton);
    expect(onConfirm).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(confirmButton.disabled).toBe(false);
    fireEvent.click(confirmButton);
    expect(onConfirm).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  it("does not apply the confirmation cooldown to a low-criticality proposal", () => {
    vi.useFakeTimers();
    const onConfirm = vi.fn();
    render(<ConfirmationModal proposal={makeProposal()} onConfirm={onConfirm} onReject={vi.fn()} />);

    fireEvent.click(screen.getByText("Confirm"));
    expect(onConfirm).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  it("details section defaults collapsed for low criticality", () => {
    render(
      <ConfirmationModal proposal={makeProposal({ criticality: "low" })} onConfirm={vi.fn()} onReject={vi.fn()} />,
    );
    expect(screen.getByText("Show why / details")).toBeTruthy();
  });

  it("details section defaults expanded for critical tier", () => {
    render(
      <ConfirmationModal
        proposal={makeProposal({ criticality: "critical" })}
        onConfirm={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.getByText("Hide why / details")).toBeTruthy();
  });

  it("a rejected proposal shows the rejection reason and only an OK button", () => {
    render(
      <ConfirmationModal
        proposal={makeProposal({ accepted: false, rejection_message: "does not exist" })}
        onConfirm={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.getByText(/does not exist/)).toBeTruthy();
    expect(screen.queryByText("Confirm")).toBeNull();
  });

  it("reject is always available regardless of criticality, and prompts for a reason first", () => {
    const onReject = vi.fn();
    render(
      <ConfirmationModal
        proposal={makeProposal({ criticality: "critical" })}
        onConfirm={vi.fn()}
        onReject={onReject}
      />,
    );
    fireEvent.click(screen.getByText("Reject"));
    expect(onReject).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Confirm Reject"));
    expect(onReject).toHaveBeenCalledWith("");
  });

  it("a typed rejection reason is passed through to onReject", () => {
    const onReject = vi.fn();
    render(
      <ConfirmationModal proposal={makeProposal()} onConfirm={vi.fn()} onReject={onReject} />,
    );
    fireEvent.click(screen.getByText("Reject"));
    fireEvent.change(screen.getByRole("textbox", { name: /why are you rejecting/i }), {
      target: { value: "value seems wrong for this frame" },
    });
    fireEvent.click(screen.getByText("Confirm Reject"));
    expect(onReject).toHaveBeenCalledWith("value seems wrong for this frame");
  });

  it("shows a loading state and hides Confirm/Reject while resolving", () => {
    render(
      <ConfirmationModal proposal={makeProposal()} resolving onConfirm={vi.fn()} onReject={vi.fn()} />,
    );
    expect(screen.queryByText("Confirm")).toBeNull();
    expect(screen.queryByText("Reject")).toBeNull();
    expect(screen.getByText("Submitting…")).toBeTruthy();
  });

  it("shows a doc link when the definition has one", () => {
    render(
      <ConfirmationModal
        proposal={makeProposal({ definition: makeDefinition({ doc_url: "https://ardupilot.org/copter/docs/parameters.html#ATC_ANG_RLL_P" }) })}
        onConfirm={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Show why / details"));
    const link = screen.getByText(/ArduPilot documentation for ATC_ANG_RLL_P/) as HTMLAnchorElement;
    expect(link.href).toBe("https://ardupilot.org/copter/docs/parameters.html#ATC_ANG_RLL_P");
  });

  it("shows a GitHub source link when the definition has one", () => {
    render(
      <ConfirmationModal
        proposal={makeProposal({
          definition: makeDefinition({
            github_source_url: "https://github.com/ArduPilot/ardupilot/blob/deadbeef/libraries/AC_AttitudeControl/AC_AttitudeControl.cpp#L62",
          }),
        })}
        onConfirm={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Show why / details"));
    const link = screen.getByText(/View ATC_ANG_RLL_P's source on GitHub/) as HTMLAnchorElement;
    expect(link.href).toBe(
      "https://github.com/ArduPilot/ardupilot/blob/deadbeef/libraries/AC_AttitudeControl/AC_AttitudeControl.cpp#L62",
    );
  });

  it("renders a value dropdown for enum params and calls onRevise on change", () => {
    const onRevise = vi.fn();
    render(
      <ConfirmationModal
        proposal={makeProposal({
          proposed_value: 1,
          definition: makeDefinition({ values: { "0": "Disabled", "1": "Enabled", "2": "Auto" } }),
        })}
        onConfirm={vi.fn()}
        onReject={vi.fn()}
        onRevise={onRevise}
      />,
    );
    const select = screen.getByLabelText(/Other valid values/) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "2" } });
    expect(onRevise).toHaveBeenCalledWith(2);
  });

  it("does not render a value dropdown when the param has no enum values", () => {
    render(<ConfirmationModal proposal={makeProposal()} onConfirm={vi.fn()} onReject={vi.fn()} onRevise={vi.fn()} />);
    expect(screen.queryByText(/Other valid values/)).toBeNull();
  });
});
