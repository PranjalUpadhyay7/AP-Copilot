import { render, screen } from "@testing-library/react";
import { it, expect } from "vitest";
import { Markdown } from "./Markdown";

it("renders a bare URL as a real clickable link opening in a new tab", () => {
  render(<Markdown text="Per https://ardupilot.org/copter/docs/parameters.html#RC9_OPTION this is the kill switch." />);
  const link = screen.getByRole("link");
  expect(link.getAttribute("href")).toBe("https://ardupilot.org/copter/docs/parameters.html#RC9_OPTION");
  expect(link.getAttribute("target")).toBe("_blank");
});

it("a markdown autolink (<url>) doesn't capture the trailing '>' into the href", () => {
  render(<Markdown text="See <https://ardupilot.org/copter/docs/compass-calibration.html> (official source)." />);
  expect(screen.getByRole("link").getAttribute("href")).toBe("https://ardupilot.org/copter/docs/compass-calibration.html");
});

it("renders headings, bold, lists, inline code and tables", () => {
  const md = "## Plan\n\n**Current state**\n\n| Parameter | Value |\n|---|---|\n| `FENCE_ENABLE` | 0 |\n\n1. Enable it\n2. Check radius\n";
  render(<Markdown text={md} />);
  expect(screen.getByText("Plan").tagName).toBe("H3");
  expect(screen.getByText("Current state").tagName).toBe("STRONG");
  expect(screen.getByRole("table")).toBeTruthy();
  expect(screen.getByText("FENCE_ENABLE").tagName).toBe("CODE");
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

it("does not render raw HTML from a reply", () => {
  const { container } = render(<Markdown text={'hello <img src=x onerror="alert(1)"> <script>alert(1)</script>'} />);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("script")).toBeNull();
});
