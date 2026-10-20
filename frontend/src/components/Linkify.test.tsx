import { render, screen } from "@testing-library/react";
import { it, expect } from "vitest";
import { Linkify } from "./Linkify";

it("renders a bare URL in a reply as a real clickable link", () => {
  render(
    <Linkify text="Per https://ardupilot.org/copter/docs/parameters.html#RC9_OPTION this is the kill switch." />,
  );
  const link = screen.getByRole("link");
  expect(link.getAttribute("href")).toBe("https://ardupilot.org/copter/docs/parameters.html#RC9_OPTION");
  expect(link.getAttribute("target")).toBe("_blank");
});

it("renders multiple URLs as separate links and keeps the surrounding text", () => {
  render(<Linkify text="See https://a.example/one and also https://b.example/two for details." />);
  const links = screen.getAllByRole("link");
  expect(links.map((l) => l.getAttribute("href"))).toEqual(["https://a.example/one", "https://b.example/two"]);
  expect(screen.getByText(/for details/)).toBeTruthy();
});

it("plain text with no URL renders unchanged, with no link", () => {
  render(<Linkify text="No citation here." />);
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.getByText("No citation here.")).toBeTruthy();
});

it("a markdown autolink (<url>) doesn't capture the trailing '>' into the href", () => {
  render(<Linkify text="See <https://ardupilot.org/copter/docs/compass-calibration.html> (official source)." />);
  const link = screen.getByRole("link");
  expect(link.getAttribute("href")).toBe("https://ardupilot.org/copter/docs/compass-calibration.html");
  expect(screen.getByText(/\(official source\)/)).toBeTruthy();
});
