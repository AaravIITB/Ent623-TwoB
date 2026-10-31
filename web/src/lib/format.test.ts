import { describe, expect, it } from "vitest";
import { count, fmtDate, tw, fmtNum, groupIndian, inr, inr0, inrCompact, timeAgo, waNumber } from "./format";
import { daysText, daysUntil, isPeriod, periodLabel, previousPeriod, shiftPeriod } from "./period";

describe("groupIndian", () => {
  it("groups the last three digits, then pairs", () => {
    expect(groupIndian("1")).toBe("1");
    expect(groupIndian("999")).toBe("999");
    expect(groupIndian("1000")).toBe("1,000");
    expect(groupIndian("100000")).toBe("1,00,000");
    expect(groupIndian("1234567")).toBe("12,34,567");
    expect(groupIndian("123456789")).toBe("12,34,56,789");
    expect(groupIndian("1000000000")).toBe("1,00,00,00,000");
  });
});

describe("inr", () => {
  it("formats rupees with paise and lakh grouping", () => {
    expect(inr(123456)).toBe("₹1,23,456.00");
    expect(inr(0)).toBe("₹0.00");
    expect(inr(12.5)).toBe("₹12.50");
    expect(inr(18184083.456)).toBe("₹1,81,84,083.46");
  });
  it("puts the minus before the rupee sign", () => {
    expect(inr(-4500)).toBe("-₹4,500.00");
  });
  it("never shows a negative zero", () => {
    expect(inr(-0.001)).toBe("₹0.00");
    expect(fmtNum(-0.004)).toBe("0.00");
  });
  it("handles missing values", () => {
    expect(inr(null)).toBe("–");
    expect(inr(undefined)).toBe("–");
    expect(inr(Number.NaN)).toBe("–");
  });
  it("rounds to whole rupees with inr0", () => {
    expect(inr0(412000.4)).toBe("₹4,12,000");
    expect(inr0(999.5)).toBe("₹1,000");
  });
});

describe("inrCompact", () => {
  it("uses L and Cr", () => {
    expect(inrCompact(420000)).toBe("₹4.2 L");
    expect(inrCompact(18000000)).toBe("₹1.8 Cr");
    expect(inrCompact(100000)).toBe("₹1 L");
    expect(inrCompact(12345678)).toBe("₹1.23 Cr");
    expect(inrCompact(989000000)).toBe("₹98.9 Cr");
    expect(inrCompact(1250000000)).toBe("₹125 Cr");
  });
  it("shows full grouping below a lakh", () => {
    expect(inrCompact(85400)).toBe("₹85,400");
    expect(inrCompact(0)).toBe("₹0");
  });
  it("keeps the sign", () => {
    expect(inrCompact(-250000)).toBe("-₹2.5 L");
  });
});

describe("count and dates", () => {
  it("counts with grouping", () => {
    expect(count(1500)).toBe("1,500");
    expect(count(123456)).toBe("1,23,456");
  });
  it("formats ISO dates", () => {
    expect(fmtDate("2026-07-20")).toBe("20 Jul 2026");
    expect(fmtDate(null)).toBe("–");
  });
  it("says how long ago", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    expect(timeAgo("2026-07-15T11:58:00Z", now)).toBe("2 min ago");
    expect(timeAgo("2026-07-15T09:00:00Z", now)).toBe("3 h ago");
  });
  it("normalises WhatsApp numbers", () => {
    expect(waNumber("98200 12345")).toBe("919820012345");
    expect(waNumber("+91-98200-12345")).toBe("919820012345");
    expect(waNumber("098200 12345")).toBe("919820012345");
  });
});

describe("periods", () => {
  it("validates and labels", () => {
    expect(isPeriod("062026")).toBe(true);
    expect(isPeriod("132026")).toBe(false);
    expect(periodLabel("062026")).toBe("Jun 2026");
  });
  it("shifts across years", () => {
    expect(shiftPeriod("012026", -1)).toBe("122025");
    expect(shiftPeriod("122026", 1)).toBe("012027");
  });
  it("defaults to the previous month", () => {
    expect(previousPeriod(new Date(2026, 10, 1))).toBe("102026");
    expect(previousPeriod(new Date(2026, 0, 5))).toBe("122025");
  });
  it("counts days to a deadline", () => {
    const today = new Date(2026, 6, 15);
    expect(daysUntil("2026-07-20", today)).toBe(5);
    expect(daysUntil("2026-07-14", today)).toBe(-1);
    expect(daysText(5)).toBe("5 days left");
    expect(daysText(-1)).toBe("1 day overdue");
    expect(daysText(0)).toBe("due today");
  });
});

describe("tw", () => {
  it("lets later classes in a group win", () => {
    expect(tw("w-full h-8 text-base text-ink", "w-auto h-7 text-sm")).toBe("text-ink w-auto h-7 text-sm");
    expect(tw("px-2.5", "pl-7")).toBe("px-2.5 pl-7");
    expect(tw("block line-clamp-2", "flex")).toBe("line-clamp-2 flex");
  });
});
