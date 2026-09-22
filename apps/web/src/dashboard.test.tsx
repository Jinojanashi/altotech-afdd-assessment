import { describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach } from "vitest";
import { AiAuthoringView, IssueView, PortfolioView, RuleView, TelemetryValue } from "./main";

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
  it("runs and labels a read-only historical backtest", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(response(url.includes("/backtest") ? { simulation: true, persistence: "READ_ONLY", matched_target_count: 16, excluded_target_count: 8, triggered_count: 1, results: [{ equipment_id: "ahu-a-f02-east", would_trigger: true, qualifying_started_at: "2026-01-15T10:00:00Z", would_open_at: "2026-01-15T10:15:00Z", would_recover_at: "2026-01-15T10:21:00Z", effective_threshold: 3, effective_duration_seconds: 900 }, { equipment_id: "ahu-a-f03-west", would_trigger: false, non_trigger_reason: "DURATION_NOT_MET" }] } : url.includes("/preview") ? { matched: [], excluded: [] } : url.includes("/versions/") ? { severity: "Critical", logic_config: { threshold: 3, duration_seconds: 900, freshness_seconds: 120 }, scope_config: {}, overrides: [] } : { display_name: "SAT deviation", rule_key: "ahu-sat-deviation", enabled: true, active_version: 1, versions: [{ version: 1 }] }))));
    render(<RuleView ruleId="rule" />); await waitFor(() => expect(screen.getByText("Run Backtest")).toBeTruthy());
    expect(document.body.textContent).toContain("does not activate the rule or create issues");
    fireEvent.click(screen.getByText("Run Backtest"));
    await waitFor(() => expect(document.body.textContent).toContain("1 would trigger"));
    expect(document.body.textContent).toContain("ahu-a-f02-east");
    expect(document.body.textContent).toContain("DURATION_NOT_MET");
  });
  it("requires an explicit confirmation on the AI review screen", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response({ id: "request", state: "READY_FOR_REVIEW", provider: "fake", model: "test", model_calls: 1, retry_count: 0, original_prompt: "Create rule", reviewed_draft: { severity: "Critical", logic: { threshold: 3, duration_seconds: 900 }, scope: { required_points: ["RUN", "SAT", "SAT_SP"] } }, target_preview: { matched_count: 1, excluded_count: 1, matched: [{ equipment_id: "ahu-a", property_id: "building-a", floor_id: "building-a-f01", effective_threshold: 3 }], excluded: [{ equipment_id: "ahu-c", exclusion_reasons: ["OUTSIDE_SELECTED_SCOPE"] }] }, warnings: [], state_trace: [], tool_trace: [] }))));
    render(<AiAuthoringView />); fireEvent.click(screen.getByText("Start safe authoring workflow"));
    await waitFor(() => expect(screen.getByText("Confirm and activate rule")).toBeTruthy());
    expect(document.body.textContent).toContain("This rule is not active");
    expect(document.body.textContent).toContain("OUTSIDE_SELECTED_SCOPE");
  });
});
