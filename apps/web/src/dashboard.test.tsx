import { describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach } from "vitest";
import { IssueView, PortfolioView, RuleView, TelemetryValue } from "./main";

const response = (body: unknown) => ({ ok: true, json: async () => body, text: async () => "" });
afterEach(cleanup);

describe("operations dashboard", () => {
  it("renders a loaded portfolio and telemetry units/timestamps", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(response(url.endsWith("/portfolio") ? { operations: { api_status: "ok", ingestion: {}, evaluation: {} }, properties: [{ source_id: "building-a", display_name: "Building A", ahu_count: 1, active_issues: 1, recent_issues: 0, floors: [] }] } : []))));
    render(<><PortfolioView /><TelemetryValue reading={{ measurement: "SAT", value: 18, unit: "degC", observed_at: "2026-01-01T10:00:00Z", quality: "GOOD", age_seconds: 0 }} /></>);
    await waitFor(() => expect(screen.getByText(/Building A/)).toBeTruthy());
    expect(screen.getByText(/18 degC/)).toBeTruthy(); expect(screen.getByText(/quality GOOD/)).toBeTruthy();
  });
  it("shows loading, error, and insufficient telemetry states", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {}))); render(<PortfolioView />); expect(screen.getByText(/Loading operational data/)).toBeTruthy();
    render(<TelemetryValue />); expect(screen.getByText(/Insufficient telemetry/)).toBeTruthy();
  });
  it("renders issue opening version, evidence, and distinct installation/affected spaces", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response({ id: "issue", severity: "Critical", status: "CLOSED", equipment_source_id: "ahu-a-f02-east", rule_id: "rule", rule_key: "ahu-sat-deviation", rule_version: 1, threshold: 3, duration_seconds: 900, qualifying_started_at: "2026-01-01T10:00:00Z", opened_at: "2026-01-01T10:15:00Z", closed_at: "2026-01-01T10:21:00Z", evidence: { samples: [{ observed_at: "2026-01-01T10:00:00Z", absolute_difference: 4, readings: { RUN: { value: "ON" }, SAT: { value: 20, quality: "GOOD" }, SAT_SP: { value: 16, quality: "GOOD" } } }], topology: { installation_location: { source_id: "building-a-plant-room" }, served_zone: { source_id: "building-a-f02-east" }, potentially_affected_rooms: [{ source_id: "building-a-f02-east-r01" }, { source_id: "building-a-f02-east-r02" }] } } }))));
    render(<IssueView issueId="issue" />); await waitFor(() => expect(document.body.textContent).toContain("Rule version 1"));
    expect(screen.getByText(/building-a-plant-room/)).toBeTruthy(); expect(screen.getByText(/building-a-f02-east-r01/)).toBeTruthy(); expect(screen.getByText(/threshold 3/)).toBeTruthy();
  });
  it("renders preview exclusions and local override", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(response(url.includes("/preview") ? { matched: [{ equipment_id: "ahu-b", property_id: "building-b", floor_id: "f01", served_zone: "zone", effective_threshold: 2, effective_duration_seconds: 900, effective_override: { threshold: 2 } }], excluded: [{ equipment_id: "ahu-c", reason: "REQUIRED_POINT_MISSING" }] } : url.includes("/versions/") ? { severity: "Critical", logic_config: { threshold: 3, duration_seconds: 900, freshness_seconds: 120 }, scope_config: {}, overrides: [{ property_id: "building-b", threshold: 2, duration_seconds: 900 }] } : { display_name: "SAT deviation", rule_key: "ahu-sat-deviation", enabled: true, active_version: 1, versions: [{ version: 1 }] }))));
    render(<RuleView ruleId="rule" />); await waitFor(() => expect(document.body.textContent).toContain("local override")); expect(document.body.textContent).toContain("REQUIRED_POINT_MISSING");
  });
});
