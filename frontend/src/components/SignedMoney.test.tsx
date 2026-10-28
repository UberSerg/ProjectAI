import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SignedMoney, formatSignedRub, signedMoneyTone } from "./SignedMoney";

describe("SignedMoney", () => {
  it("tones and formats gains/losses", () => {
    expect(signedMoneyTone(12_450)).toBe("positive");
    expect(signedMoneyTone(-8_120)).toBe("negative");
    expect(signedMoneyTone(0)).toBe("neutral");
    expect(signedMoneyTone(null)).toBe("neutral");
    expect(signedMoneyTone(100, true)).toBe("partial");
    expect(formatSignedRub(12450)).toMatch(/^\+12/);
    expect(formatSignedRub(-8120)).toMatch(/^−8/);
  });

  it("renders with semantic classes", () => {
    const { rerender } = render(<SignedMoney value={100} data-testid="sm" />);
    expect(screen.getByTestId("sm")).toHaveAttribute("data-tone", "positive");
    rerender(<SignedMoney value={-50} data-testid="sm" />);
    expect(screen.getByTestId("sm")).toHaveAttribute("data-tone", "negative");
    rerender(<SignedMoney value={10} partial data-testid="sm" />);
    expect(screen.getByTestId("sm")).toHaveAttribute("data-tone", "partial");
    expect(screen.getByTestId("sm").textContent).toMatch(/частично/);
  });
});
