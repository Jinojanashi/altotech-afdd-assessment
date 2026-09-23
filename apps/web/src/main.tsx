import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";

const base = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
type Data = Record<string, any>;

const pretty = (value?: string) => value ? new Date(value).toLocaleString() : "Not available";
const formatNumber = (value: unknown, digits = 1) => {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString(undefined, { maximumFractionDigits: digits }) : "—";
};
const formatDuration = (seconds?: number) => seconds && seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds ?? "—"} sec`;
const humanizeId = (value?: string) => value
  ? value.split("-").map(part => /^(ahu|iaq)$/i.test(part) ? part.toUpperCase() : /^f\d+$/i.test(part) ? part.toUpperCase() : part.charAt(0).toUpperCase() + part.slice(1)).join(" ")
  : "Not available";
const entityName = (value?: Data | string) => typeof value === "string"
  ? humanizeId(value)
  : value ? value.display_name || humanizeId(value.source_id) : "Not available";
const entityId = (value?: Data | string) => typeof value === "string" ? value : value?.source_id;
const list = (values?: string[]) => values?.length ? values.join(", ") : "All eligible";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(base + path, init);
  if (!response.ok) throw Error(`${response.status}: ${await response.text()}`);
  return response.json();
}

function useData<T>(path: string | null) {
  const [state, setState] = useState<{data?: T; loading: boolean; error?: string}>({loading: !!path});
  useEffect(() => {
    if (!path) return;
    let live = true;
    setState({loading: true});
    api<T>(path)
      .then(data => live && setState({data, loading: false}))
      .catch((error: Error) => live && setState({loading: false, error: error.message}));
    return () => { live = false; };
  }, [path]);
  return state;
}

function StatusBadge({children, tone = "neutral"}:{children: React.ReactNode; tone?: "success" | "warning" | "critical" | "info" | "neutral"}) {
  return <span className={`status-badge status-${tone}`}>{children}</span>;
}

function EntityId({children}:{children?: React.ReactNode}) {
  return <code className="entity-id">{children || "Not available"}</code>;
}

function SectionCard({title, subtitle, className = "", children}:{title?: React.ReactNode; subtitle?: React.ReactNode; className?: string; children: React.ReactNode}) {
  return <section className={`panel ${className}`}>
    {(title || subtitle) && <div className="section-heading"><div>{title && <h2>{title}</h2>}{subtitle && <p>{subtitle}</p>}</div></div>}
    {children}
  </section>;
}

function MetricCard({label, value, detail, tone}:{label: string; value: React.ReactNode; detail?: React.ReactNode; tone?: string}) {
  return <div className={`metric-card ${tone ? `metric-${tone}` : ""}`}>
    <span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}
  </div>;
}

function State({loading, error, empty, children}:{loading: boolean; error?: string; empty?: boolean; children: React.ReactNode}) {
  if (loading) return <div className="state loading"><span className="loading-dot"/>Loading operational data…</div>;
  if (error) return <div className="state error"><b>Unable to load data</b><span>{error}</span></div>;
  if (empty) return <div className="state empty">No data is available yet. Missing telemetry is not treated as normal.</div>;
  return <>{children}</>;
}

export function TelemetryValue({reading}:{reading?: Data}) {
  if (!reading) return <span className="data-state data-missing">Insufficient telemetry</span>;
  const stale = Number(reading.age_seconds ?? Infinity) > 120;
  return <div className="telemetry">
    <div><b>{reading.measurement}</b><strong>{String(reading.value ?? "missing")} {reading.unit || ""}</strong></div>
    <small>{pretty(reading.observed_at)} · {stale ? "STALE / historical" : "fresh"} · quality {reading.quality || "unknown"}</small>
  </div>;
}

function Header() {
  const path = location.pathname;
  const items = [
    {href: "/portfolio", label: "Portfolio", active: path === "/portfolio" || path.startsWith("/issues/")},
    {href: "/rules", label: "Rules", active: path === "/rules" || (/^\/rules\/[^/]+$/.test(path))},
    {href: "/rules/new/ai", label: "AI authoring", active: path === "/rules/new/ai"},
  ];
  return <header className="app-header"><div className="header-inner">
    <a className="brand" href="/portfolio"><span className="brand-mark">A</span><span>AFDD Operations</span></a>
    <nav aria-label="Primary navigation">{items.map(item => <a key={item.href} href={item.href} className={item.active ? "active" : ""} aria-current={item.active ? "page" : undefined}>{item.label}</a>)}</nav>
  </div></header>;
}

function PageTitle({eyebrow, title, description, actions}:{eyebrow?: string; title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode}) {
  return <div className="page-heading"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1>{description && <p className="page-description">{description}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</div>;
}

function Operations({data}:{data: Data}) {
  const ingestion = data.ingestion || {}, evaluation = data.evaluation || {};
  const healthy = String(data.api_status || "unknown").toLowerCase() === "ok";
  return <SectionCard title="System health" subtitle="Live platform and pipeline status" className="operations-card">
    <div className="operations-grid">
      <MetricCard label="API" value={<StatusBadge tone={healthy ? "success" : "warning"}>{healthy ? "Healthy" : data.api_status || "Unknown"}</StatusBadge>}/>
      <MetricCard label="Accepted" value={formatNumber(ingestion.accepted, 0)} detail="telemetry events"/>
      <MetricCard label="Duplicates" value={formatNumber(ingestion.duplicates, 0)} tone={Number(ingestion.duplicates) ? "warning" : undefined}/>
      <MetricCard label="Rejected" value={formatNumber(ingestion.rejected, 0)} tone={Number(ingestion.rejected) ? "critical" : undefined}/>
      <MetricCard label="Last ingestion" value={pretty(ingestion.last_ingestion_at)} />
      <MetricCard label="Last AFDD evaluation" value={pretty(evaluation.last_evaluation_at)} detail={`${evaluation.evaluation_states ?? 0} persisted states`}/>
    </div>
  </SectionCard>;
}

export function PortfolioView() {
  const portfolio = useData<Data>("/portfolio"), issues = useData<Data[]>("/issues");
  const [selected, setSelected] = useState<string>();
  if (!portfolio.data) return <State {...portfolio}> </State>;
  return <State {...portfolio} empty={!portfolio.data.properties?.length}><main>
    <PageTitle eyebrow="Operations overview" title="Portfolio" description="Navigate canonical properties, floors, HVAC zones, and equipment."/>
    <Operations data={portfolio.data.operations || {}}/>
    <div className="portfolio-grid">
      <SectionCard title="Building hierarchy" subtitle="Explicit ontology relationships from property to served equipment">
        <div className="property-list">{(portfolio.data.properties || []).map((property: Data) => <article className="property" key={property.source_id}>
          <div className="entity-heading"><div><h3>{entityName(property)}</h3><EntityId>{property.source_id}</EntityId></div><div className="property-stats"><span>{property.ahu_count} AHUs</span><StatusBadge tone={property.active_issues ? "critical" : "success"}>{property.active_issues} active</StatusBadge><span>{property.recent_issues} recovered</span></div></div>
          {(property.floors || []).map((floor: Data) => <details className="floor" key={floor.source_id} open>
            <summary><span><b>{entityName(floor)}</b><EntityId>{floor.source_id}</EntityId></span><span>{floor.zones?.length || 0} zones</span></summary>
            <div className="floor-content">{(floor.zones || []).map((zone: Data) => <div className="zone" key={zone.source_id}>
              <div className="zone-heading"><span className="hierarchy-label">HVAC zone</span><b>{entityName(zone)}</b><EntityId>{zone.source_id}</EntityId></div>
              <div className="served-rooms"><span>Served rooms</span><p>{(zone.rooms || []).map((room: Data) => entityName(room)).join(" · ") || "No occupied rooms recorded"}</p></div>
              <div className="equipment-list">{(zone.equipment || []).map((ahu: Data) => <button className={`equipment-button ${selected === ahu.source_id ? "selected" : ""}`} key={ahu.source_id} onClick={() => setSelected(ahu.source_id)}><span>{entityName(ahu)}</span><EntityId>{ahu.source_id}</EntityId></button>)}</div>
            </div>)}</div>
          </details>)}
        </article>)}</div>
      </SectionCard>
      <SectionCard title="Recent issues" subtitle="Latest detected and recovered faults" className="recent-issues">
        <State {...issues} empty={!!issues.data && !issues.data.length}>{issues.data?.map(issue => <a className="issue-link" key={issue.id} href={`/issues/${issue.id}`}>
          <div><StatusBadge tone={String(issue.severity).toLowerCase() === "critical" ? "critical" : "warning"}>{issue.severity}</StatusBadge><StatusBadge tone={String(issue.status).toUpperCase() === "CLOSED" ? "neutral" : "critical"}>{issue.status}</StatusBadge></div>
          <strong>{entityName(issue.equipment_id)}</strong><EntityId>{issue.equipment_id}</EntityId>
          <small>Opened {pretty(issue.opened_at)}{issue.closed_at ? ` · Recovered ${pretty(issue.closed_at)}` : ""}</small>
          <span className="row-action">Investigate →</span>
        </a>)}</State>
      </SectionCard>
    </div>
    {selected && <Equipment sourceId={selected}/>}
  </main></State>;
}

function Devices({items, empty}:{items?: Data[]; empty: string}) {
  return !items?.length ? <p className="data-state data-missing">{empty}</p> : <div className="context-devices">{items.map(item => <div className="device-card" key={item.source_id}>
    <b>{entityName(item)}</b><EntityId>{item.source_id}</EntityId><small>{item.room_id ? `Room scope: ${item.room_id}` : `Floor scope: ${item.floor_id}`}</small>
    {item.readings?.map((reading: Data) => <TelemetryValue reading={reading} key={reading.point_id}/>)}</div>)}</div>;
}

function Equipment({sourceId}:{sourceId: string}) {
  const topology = useData<Data>(`/equipment/${sourceId}/topology`), readings = useData<Data[]>(`/telemetry/equipment/${sourceId}/latest`), context = useData<Data>(`/equipment/${sourceId}/context`);
  if (!topology.data || !readings.data || !context.data) return <State loading={topology.loading || readings.loading || context.loading} error={topology.error || readings.error || context.error}> </State>;
  const find = (measurement: string) => readings.data!.find(value => value.measurement === measurement);
  return <SectionCard title={<>Selected equipment <span className="title-divider">/</span> {humanizeId(sourceId)}</>} subtitle={<EntityId>{sourceId}</EntityId>} className="selected-equipment">
    <div className="topology topology-compact">
      <TopologyCard label="Installed at" value={topology.data.installation_location}/>
      <TopologyCard label="Serves HVAC zone" value={topology.data.served_zone}/>
      <TopologyCard label="Potentially affected spaces" values={topology.data.occupied_rooms}/>
    </div>
    <div className="measurements"><div><h3>Trigger measurements</h3>{["RUN", "SAT", "SAT_SP"].map(item => <TelemetryValue reading={find(item)} key={item}/>)}</div><div><h3>Contextual AHU measurements</h3>{["RAT", "ALARM"].map(item => <TelemetryValue reading={find(item)} key={item}/>)}</div></div>
    <div className="context-section"><h3>Room IAQ context</h3><Devices items={context.data.room_iaq} empty="No room IAQ device is explicitly scoped to the served rooms."/></div>
    <div className="context-section"><h3>Floor electricity context</h3><p className="note">These meters measure floor scope; they are not AHU datapoints.</p><Devices items={context.data.floor_meters} empty="No floor meter is explicitly scoped to this floor."/></div>
  </SectionCard>;
}

function TopologyCard({label, value, values}:{label: string; value?: Data | string; values?: Array<Data | string>}) {
  return <div className="topology-card"><span>{label}</span>{values ? <ul>{values.length ? values.map(item => <li key={entityId(item)}><b>{entityName(item)}</b><EntityId>{entityId(item)}</EntityId></li>) : <li>No occupied rooms recorded</li>}</ul> : <><b>{entityName(value)}</b><EntityId>{entityId(value)}</EntityId></>}</div>;
}

function Trend({samples}:{samples?: Data[]}) {
  const all = samples || [];
  const valid = (sample: Data) => sample.absolute_difference !== null && sample.readings?.SAT?.value !== undefined && sample.readings?.SAT_SP?.value !== undefined;
  if (all.filter(valid).length < 2) return <p className="data-state data-missing">Insufficient contiguous evidence for a trend; gaps are not connected.</p>;
  const values = all.filter(valid).flatMap(sample => [Number(sample.readings.SAT.value), Number(sample.readings.SAT_SP.value)]);
  const min = Math.min(...values), max = Math.max(...values), width = 600, height = 130;
  const point = (value: number, index: number) => `${20 + index * (width - 40) / Math.max(all.length - 1, 1)},${height - 20 - (value - min) / (max - min || 1) * (height - 40)}`;
  const segments: Data[][] = [];
  all.forEach((sample, index) => {
    if (!valid(sample)) return;
    if (!index || !valid(all[index - 1])) segments.push([]);
    segments[segments.length - 1].push({...sample, _index: index});
  });
  const start = all[0]?.observed_at, end = all[all.length - 1]?.observed_at;
  return <div className="trend-wrap">
    <div className="chart-legend"><span><i className="legend-sat"/>SAT</span><span><i className="legend-setpoint"/>SAT setpoint</span><small>Observed evidence only; gaps are not connected</small></div>
    <svg className="trend" viewBox={`0 0 ${width} ${height + 24}`} role="img" aria-label="Supply air temperature and setpoint evidence trend">
      <line className="chart-grid" x1="20" y1={height - 20} x2={width - 20} y2={height - 20}/>
      {segments.map((segment, index) => <React.Fragment key={index}>
        <polyline className="sat" points={segment.map(sample => point(Number(sample.readings.SAT.value), sample._index)).join(" ")}/>
        <polyline className="setpoint" points={segment.map(sample => point(Number(sample.readings.SAT_SP.value), sample._index)).join(" ")}/>
      </React.Fragment>)}
      <text x="20" y={height + 10}>{start ? new Date(start).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) : ""}</text>
      <text textAnchor="end" x={width - 20} y={height + 10}>{end ? new Date(end).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) : ""}</text>
    </svg>
  </div>;
}

function EvidenceTable({samples, threshold}:{samples?: Data[]; threshold: number}) {
  if (!samples?.length) return <p className="data-state data-missing">No telemetry evidence was persisted for this issue.</p>;
  return <div className="table-scroll evidence-scroll"><table><thead><tr><th>Observed</th><th>SAT</th><th>SAT setpoint</th><th>Δ</th><th>Threshold</th><th>RUN</th><th>Quality</th></tr></thead><tbody>
    {samples.map((sample: Data, index: number) => <tr key={`${sample.observed_at}-${index}`}><td>{pretty(sample.observed_at)}</td><td>{sample.readings?.SAT?.value == null ? "—" : `${formatNumber(sample.readings.SAT.value)} °C`}</td><td>{sample.readings?.SAT_SP?.value == null ? "—" : `${formatNumber(sample.readings.SAT_SP.value)} °C`}</td><td className="numeric"><b>{sample.absolute_difference == null ? "—" : `${formatNumber(sample.absolute_difference)} °C`}</b></td><td className="numeric">&gt; {formatNumber(threshold)} °C</td><td><StatusBadge tone={sample.readings?.RUN?.value === "ON" ? "success" : "neutral"}>{String(sample.readings?.RUN?.value ?? "missing")}</StatusBadge></td><td>{sample.readings?.SAT?.quality || sample.readings?.SAT_SP?.quality || "missing"}</td></tr>)}
  </tbody></table></div>;
}

export function IssueView({issueId}:{issueId: string}) {
  const query = useData<Data>(`/issues/${issueId}`);
  if (!query.data) return <State {...query}> </State>;
  const issue = query.data, evidence = issue.evidence || {}, topology = evidence.topology || {};
  const representative = (evidence.samples || []).filter((sample: Data) => sample.absolute_difference != null).sort((a: Data, b: Data) => Number(b.absolute_difference) - Number(a.absolute_difference))[0];
  const statusTone = String(issue.status).toUpperCase() === "CLOSED" ? "neutral" : "critical";
  return <State {...query}><main>
    <a className="back-link" href="/portfolio">← Portfolio</a>
    <PageTitle eyebrow="Issue investigation" title={entityName(issue.equipment_source_id)} description={<EntityId>{issue.equipment_source_id}</EntityId>} actions={<div className="badge-group"><StatusBadge tone="critical">{issue.severity}</StatusBadge><StatusBadge tone={statusTone}>{issue.status}</StatusBadge></div>}/>
    <SectionCard className="issue-overview">
      <div className="issue-rule"><div><span>Detection rule</span><a href={`/rules/${issue.rule_id}`}>{humanizeId(issue.rule_key)}</a><small>Rule version {issue.rule_version} · immutable opening configuration</small></div><EntityId>{issue.id}</EntityId></div>
      <p className="sr-only">Rule version {issue.rule_version}, threshold {issue.threshold}, duration {issue.duration_seconds} seconds</p>
      <div className="timeline-grid">
        <MetricCard label="Qualifying" value={pretty(issue.qualifying_started_at)} detail="Condition first sustained"/>
        <MetricCard label="Opened" value={pretty(issue.opened_at)} detail={`After ${formatDuration(issue.duration_seconds)}`}/>
        <MetricCard label="Recovered" value={pretty(issue.closed_at)} detail="Condition returned to normal"/>
      </div>
      <p className="timezone-note">Times shown in browser local time ({Intl.DateTimeFormat().resolvedOptions().timeZone || "local timezone"}); source evaluation uses device timestamps.</p>
    </SectionCard>
    <SectionCard title="Trigger summary" subtitle="Persisted evidence explaining why this issue opened">
      <div className="trigger-summary">
        <MetricCard label="SAT" value={representative?.readings?.SAT?.value == null ? "—" : `${formatNumber(representative.readings.SAT.value)} °C`}/>
        <MetricCard label="SAT setpoint" value={representative?.readings?.SAT_SP?.value == null ? "—" : `${formatNumber(representative.readings.SAT_SP.value)} °C`}/>
        <MetricCard label="Difference" value={representative?.absolute_difference == null ? "—" : `${formatNumber(representative.absolute_difference)} °C`} tone="critical"/>
        <MetricCard label="Threshold" value={`> ${formatNumber(issue.threshold)} °C`}/>
        <MetricCard label="RUN" value={<StatusBadge tone={representative?.readings?.RUN?.value === "ON" ? "success" : "neutral"}>{String(representative?.readings?.RUN?.value ?? "missing")}</StatusBadge>}/>
        <MetricCard label="Quality" value={representative?.readings?.SAT?.quality || "missing"}/>
        <MetricCard label="Duration" value={formatDuration(issue.duration_seconds)}/>
      </div>
    </SectionCard>
    <SectionCard title="Fault evidence" subtitle="SAT and SAT setpoint during the persisted qualification window">
      <Trend samples={evidence.samples}/>
      <h3 className="subsection-title">Evidence samples</h3>
      <EvidenceTable samples={evidence.samples} threshold={issue.threshold}/>
    </SectionCard>
    <SectionCard title="Location and impact" subtitle="Installation location remains intentionally distinct from served and affected spaces">
      <div className="topology">
        <TopologyCard label="Installed at" value={topology.installation_location}/>
        <TopologyCard label="Serves" value={topology.served_zone}/>
        <TopologyCard label="Potentially affected spaces" values={topology.potentially_affected_rooms}/>
      </div>
    </SectionCard>
    <details className="technical-details"><summary>Technical details</summary><div><h3>Effective override</h3><pre>{JSON.stringify(issue.effective_override || {}, null, 2)}</pre><h3>Raw evidence samples</h3><pre>{JSON.stringify(evidence.samples || [], null, 2)}</pre></div></details>
  </main></State>;
}

export function BacktestView({ruleId, version, threshold: initialThreshold, duration: initialDuration}:{ruleId: string; version: number; threshold: number; duration: number}) {
  const [start, setStart] = useState("2026-01-15T08:00"), [end, setEnd] = useState("2026-01-15T14:00"), [threshold, setThreshold] = useState(String(initialThreshold)), [duration, setDuration] = useState(String(initialDuration));
  const [result, setResult] = useState<Data>(), [busy, setBusy] = useState(false), [error, setError] = useState<string>();
  const run = async () => {
    setBusy(true); setError(undefined);
    try { setResult(await api<Data>(`/rules/${ruleId}/versions/${version}/backtest`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({start: `${start}:00Z`, end: `${end}:00Z`, threshold: Number(threshold), duration_seconds: Number(duration)})})); }
    catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  };
  const triggered = result?.results?.filter((item: Data) => item.would_trigger) || [], notTriggered = result?.results?.filter((item: Data) => !item.would_trigger).slice(0, 5) || [];
  return <section className="backtest-section">
    <div className="section-heading"><div><h2>Historical backtest</h2><p>What would this rule have done against historical telemetry?</p></div><StatusBadge tone="info">Simulation only</StatusBadge></div>
    <p className="safety-note">Historical simulation only — does not activate the rule or create issues.</p>
    <div className="form-grid">
      <label>Start <small>UTC</small><input type="datetime-local" value={start} onChange={event => setStart(event.target.value)}/></label>
      <label>End <small>UTC</small><input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)}/></label>
      <label>Threshold <small>°C</small><input type="number" min="0.1" step="0.1" value={threshold} onChange={event => setThreshold(event.target.value)}/></label>
      <label>Duration <small>seconds</small><input type="number" min="1" value={duration} onChange={event => setDuration(event.target.value)}/></label>
      <button className="button primary" disabled={busy || !start || !end || !threshold || !duration} onClick={run}>{busy ? "Running…" : "Run Backtest"}</button>
    </div>
    {error && <div className="state error">Backtest failed: {error}</div>}
    {result && <div className="backtest-results">
      <p className="result-sentence"><b>Hypothetical result:</b> {result.triggered_count} would trigger from {result.matched_target_count} matched targets; {result.excluded_target_count} excluded.</p>
      <div className="result-summary"><MetricCard label="Matched targets" value={result.matched_target_count}/><MetricCard label="Excluded" value={result.excluded_target_count}/><MetricCard label="Would trigger" value={result.triggered_count} tone="critical"/></div>
      <div className="split-results"><div><h3>Would trigger</h3>{triggered.length ? triggered.map((item: Data) => <div className="result-row" key={item.equipment_id}><div><b>{humanizeId(item.equipment_id)}</b><EntityId>{item.equipment_id}</EntityId></div><small>Qualifying {pretty(item.qualifying_started_at)} · Open {pretty(item.would_open_at)} · Recovery {pretty(item.would_recover_at)}</small><span>{formatNumber(item.effective_threshold)} °C · {formatDuration(item.effective_duration_seconds)}</span></div>) : <p className="data-state data-missing">No equipment would trigger.</p>}</div>
      <div><h3>Would not trigger <small>(examples)</small></h3>{notTriggered.length ? notTriggered.map((item: Data) => <div className="result-row" key={item.equipment_id}><div><b>{humanizeId(item.equipment_id)}</b><EntityId>{item.equipment_id}</EntityId></div><span>{item.non_trigger_reason || "No reason supplied"}</span></div>) : <p className="data-state data-missing">No non-trigger examples.</p>}</div></div>
    </div>}
  </section>;
}

function ScopeSummary({scope}:{scope: Data}) {
  return <div className="scope-summary">
    <div><span>Properties</span><b>{list(scope.property_ids)}</b></div><div><span>Floors</span><b>{list(scope.floor_ids)}</b></div>
    <div><span>Equipment</span><b>{scope.equipment_type || "AHU"}</b></div><div><span>Property type</span><b>{scope.property_type || "—"}</b></div>
    <div><span>Served usage</span><b>{list(scope.served_zone_usage_types)}</b></div><div><span>Occupied room usage</span><b>{list(scope.occupied_room_usage_types)}</b></div>
  </div>;
}

export function RuleView({ruleId}:{ruleId: string}) {
  const rule = useData<Data>(`/rules/${ruleId}`), [version, setVersion] = useState<number>();
  const active = version ?? rule.data?.active_version, detail = useData<Data>(active ? `/rules/${ruleId}/versions/${active}` : null), preview = useData<Data>(active ? `/rules/${ruleId}/versions/${active}/preview` : null);
  if (!rule.data || !detail.data || !preview.data) return <State loading={rule.loading || detail.loading || preview.loading} error={rule.error || detail.error || preview.error}> </State>;
  const activate = (path: string) => api(path, {method: "POST"}).then(() => location.reload());
  const config = detail.data, scope = config.scope_config || {}, logic = config.logic_config || {};
  return <main>
    <a className="back-link" href="/rules">← Rules</a>
    <PageTitle eyebrow="Rule detail" title={rule.data.display_name} description={<><EntityId>{rule.data.rule_key}</EntityId><span className="version-label">Version {active}</span></>} actions={<StatusBadge tone={rule.data.enabled ? "success" : "neutral"}>{rule.data.enabled ? "Active" : "Disabled"}</StatusBadge>}/>
    <SectionCard className="rule-summary-card">
      <div className="rule-metrics"><MetricCard label="Severity" value={<StatusBadge tone="critical">{config.severity}</StatusBadge>}/><MetricCard label="Threshold" value={`> ${formatNumber(logic.threshold)} °C`}/><MetricCard label="Duration" value={formatDuration(logic.duration_seconds)}/><MetricCard label="Freshness" value={`${logic.freshness_seconds} sec`}/></div>
      <div className="rule-toolbar"><div className="versions" aria-label="Rule versions">{(rule.data.versions || []).map((item: Data) => <button key={item.version} className={item.version === active ? "active" : ""} onClick={() => setVersion(item.version)}>v{item.version}</button>)}</div><div className="actions"><button className="button secondary" onClick={() => activate(`/rules/${ruleId}/versions/${active}/activate`)}>Activate selected version</button><button className="button danger" onClick={() => activate(`/rules/${ruleId}/disable`)}>Disable rule</button></div></div>
    </SectionCard>
    <SectionCard title="Rule configuration" subtitle="Human-readable scope and deterministic fault logic">
      <h3 className="subsection-title">Scope</h3><ScopeSummary scope={scope}/>
      <h3 className="subsection-title">Required points</h3><div className="chip-row">{(scope.required_points || []).map((point: string) => <StatusBadge key={point} tone="info">{point}</StatusBadge>)}</div>
      <h3 className="subsection-title">Fault logic</h3><p className="logic-statement">|SAT − SAT setpoint| <b>&gt; {formatNumber(logic.threshold)} °C</b> continuously for <b>{formatDuration(logic.duration_seconds)}</b> while <b>RUN = ON</b></p>
      <details className="inline-details"><summary>Raw rule configuration</summary><pre>{JSON.stringify(scope, null, 2)}</pre></details>
    </SectionCard>
    <SectionCard title="Property-specific overrides" subtitle="Effective values replace defaults only within the named property">
      {config.overrides?.length ? <div className="override-list">{config.overrides.map((item: Data) => <div className="override-row" key={item.property_id}><div><b>{humanizeId(item.property_id)}</b><EntityId>{item.property_id}</EntityId></div><span>Threshold {item.threshold == null ? "default" : `${formatNumber(item.threshold)} °C`} · Duration {item.duration_seconds == null ? "default" : formatDuration(item.duration_seconds)}</span><StatusBadge tone="warning">Local override</StatusBadge><span className="sr-only">local override</span></div>)}</div> : <p className="data-state data-missing">No local overrides.</p>}
    </SectionCard>
    <SectionCard title="Target preview" subtitle={`${preview.data.matched_count ?? preview.data.matched?.length ?? 0} matched · ${preview.data.excluded_count ?? preview.data.excluded?.length ?? 0} excluded`}>
      <h3 className="subsection-title">Matched targets</h3>
      {preview.data.matched?.length ? <div className="table-scroll"><table><thead><tr><th>Equipment</th><th>Building / floor</th><th>Threshold</th><th>Duration</th><th>Override</th></tr></thead><tbody>{preview.data.matched.map((item: Data) => <tr key={item.equipment_id}><td><b>{humanizeId(item.equipment_id)}</b><EntityId>{item.equipment_id}</EntityId></td><td>{humanizeId(item.property_id)}<small>{humanizeId(item.floor_id)}</small></td><td className="numeric">{formatNumber(item.effective_threshold)} °C</td><td className="numeric">{formatDuration(item.effective_duration_seconds)}</td><td>{item.effective_override ? <StatusBadge tone="warning">Local override</StatusBadge> : "—"}</td></tr>)}</tbody></table></div> : <p className="data-state data-missing">No matched targets.</p>}
      <h3 className="subsection-title">Exclusions</h3>
      {preview.data.excluded?.length ? <div className="table-scroll exclusions-table"><table><thead><tr><th>Equipment</th><th>Reason</th></tr></thead><tbody>{preview.data.excluded.map((item: Data, index: number) => <tr key={`${item.equipment_id || "candidate"}-${index}`}><td>{item.equipment_id ? <><b>{humanizeId(item.equipment_id)}</b><EntityId>{item.equipment_id}</EntityId></> : "Candidate"}</td><td>{item.reason || item.exclusion_reasons?.join(", ") || "—"}</td></tr>)}</tbody></table></div> : <p className="data-state data-missing">No exclusions.</p>}
      <BacktestView key={active} ruleId={ruleId} version={active} threshold={logic.threshold} duration={logic.duration_seconds}/>
    </SectionCard>
  </main>;
}

function Rules() {
  const rules = useData<Data[]>("/rules");
  return <State {...rules}>{rules.data ? <main><PageTitle eyebrow="Configuration" title="Rules" description="Versioned deterministic AFDD definitions and activation state." actions={<a className="button primary" href="/rules/new/ai">Author with AI</a>}/><SectionCard>{rules.data.map(item => <a className="rule-list-row" href={`/rules/${item.id}`} key={item.id}><div><strong>{item.display_name}</strong><EntityId>{item.rule_key}</EntityId></div><StatusBadge tone={item.enabled ? "success" : "neutral"}>{item.enabled ? "Active" : "Disabled"}</StatusBadge><span>Open →</span></a>)}</SectionCard></main> : null}</State>;
}

const workflowSteps = [
  {label: "Request", state: "RECEIVED"}, {label: "Interpret", state: "INTERPRETING"}, {label: "Discover", state: "DISCOVERING"}, {label: "Validate", state: "VALIDATING"}, {label: "Preview", state: "PREVIEWING"}, {label: "Review", state: "READY_FOR_REVIEW"}, {label: "Confirm", state: "CONFIRMED"}, {label: "Activate", state: "ACTIVATED"},
];
const stateRank: Record<string, number> = {RECEIVED: 0, INTERPRETING: 1, DISCOVERING: 2, VALIDATING: 3, PREVIEWING: 4, READY_FOR_REVIEW: 5, CONFIRMED: 6, ACTIVATED: 7};

function Workflow({state}:{state: string}) {
  const rank = stateRank[state] ?? -1;
  return <ol className="workflow" aria-label="AI authoring workflow">{workflowSteps.map((step, index) => <li key={step.state} className={index < rank ? "complete" : index === rank ? "current" : "pending"}><span aria-hidden="true">{index < rank ? "✓" : index === rank ? "●" : "○"}</span>{step.label}</li>)}</ol>;
}

export function AiAuthoringView() {
  const [prompt, setPrompt] = useState("Create a Critical rule for office AHUs in Building A when SAT differs from SAT setpoint by more than 3°C for 15 minutes while running."), [request, setRequest] = useState<Data>(), [answer, setAnswer] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState<string>();
  const post = async (path: string, body?: Data) => { setBusy(true); setError(undefined); try { setRequest(await api<Data>(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined})); } catch (caught) { setError(String(caught)); } finally { setBusy(false); } };
  const draft = request?.reviewed_draft, preview = request?.target_preview;
  return <main>
    <a className="back-link" href="/rules">← Rules</a>
    <PageTitle eyebrow="Guardrailed workflow" title="AI-assisted rule authoring" description="The model proposes an interpretation; server-side ontology resolution, validation, preview, and human confirmation remain authoritative."/>
    {!request && <SectionCard title="Describe the AFDD rule" subtitle="Use operational language. No rule is created or activated during interpretation."><label className="field" htmlFor="rule-prompt">Natural-language AFDD request<textarea id="rule-prompt" rows={6} value={prompt} onChange={event => setPrompt(event.target.value)}/></label><div className="form-actions"><button className="button primary" disabled={busy || !prompt.trim()} onClick={() => post("/ai/authoring-requests", {prompt})}>{busy ? "Interpreting…" : "Start safe authoring workflow"}</button></div></SectionCard>}
    {error && <div className="state error">Provider or API error: {error}</div>}
    {request && <>
      <SectionCard className="workflow-card"><Workflow state={request.state}/></SectionCard>
      <SectionCard className="ai-review-card">
        <div className={`review-banner ${request.state === "READY_FOR_REVIEW" ? "ready" : ""}`}><div><span>Workflow state</span><h2>{String(request.state).replaceAll("_", " ")}</h2>{request.state === "READY_FOR_REVIEW" && <><b>Human review required</b><p>This rule is not active. Review every value and target before confirming.</p></>}</div><StatusBadge tone={request.state === "READY_FOR_REVIEW" ? "success" : request.state === "REJECTED" || request.state === "FAILED" ? "critical" : "info"}>{request.state}</StatusBadge></div>
        <div className="ai-meta"><span>{request.provider} · {request.model}</span><span>{request.model_calls} model call{request.model_calls === 1 ? "" : "s"} · {request.retry_count} retries</span><EntityId>{request.id}</EntityId></div>
        <div className="original-request"><span>Original request</span><p>{request.original_prompt}</p></div>
        {request.stop_reason && <div className="state error">{request.stop_reason}</div>}
        {request.state === "NEEDS_CLARIFICATION" && <div className="clarification"><h3>Clarification required</h3><p>{request.clarification_question}</p><label className="field">Your answer<textarea rows={3} value={answer} onChange={event => setAnswer(event.target.value)}/></label><button className="button primary" disabled={busy || !answer.trim()} onClick={() => post(`/ai/authoring-requests/${request.id}/clarification`, {answer})}>Submit clarification</button></div>}
        {request.state === "READY_FOR_REVIEW" && <>
          <div className="ai-review-grid"><div className="review-column"><h3>Interpreted rule</h3><div className="key-values"><div><span>Severity</span><StatusBadge tone="critical">{draft?.severity}</StatusBadge></div><div><span>Threshold</span><b>&gt; {formatNumber(draft?.logic?.threshold)} °C</b></div><div><span>Duration</span><b>{formatDuration(draft?.logic?.duration_seconds)}</b></div><div><span>Required points</span><div className="chip-row">{draft?.scope?.required_points?.map((point: string) => <StatusBadge key={point} tone="info">{point}</StatusBadge>)}</div></div></div><h4>Scope</h4><ScopeSummary scope={draft?.scope || {}}/>{request.warnings?.map((warning: string) => <div className="state warning" key={warning}>{warning}</div>)}</div>
          <div className="review-column"><div className="preview-heading"><h3>Target preview</h3><div><strong>{preview?.matched_count}</strong><span>matched</span><strong>{preview?.excluded_count}</strong><span>excluded</span></div></div>{preview?.matched?.length ? <div className="compact-list">{preview.matched.map((item: Data) => <div key={item.equipment_id}><span><b>{humanizeId(item.equipment_id)}</b><EntityId>{item.equipment_id}</EntityId></span><small>{humanizeId(item.property_id)} / {humanizeId(item.floor_id)} · {formatNumber(item.effective_threshold)} °C</small></div>)}</div> : <p className="data-state data-missing">No matched targets.</p>}<h4>Exclusions</h4>{preview?.excluded?.length ? <div className="compact-list exclusions">{preview.excluded.map((item: Data) => <div key={item.equipment_id}><span><b>{humanizeId(item.equipment_id)}</b><EntityId>{item.equipment_id}</EntityId></span><small>{item.exclusion_reasons?.join(", ") || "—"}</small></div>)}</div> : <p className="data-state data-missing">No exclusions.</p>}</div></div>
          <div className="confirmation-bar"><div><b>Explicit confirmation required</b><span>This action creates and activates a new immutable rule version.</span></div><div><button className="button secondary" disabled={busy} onClick={() => post(`/ai/authoring-requests/${request.id}/cancel`)}>Cancel</button><button className="button primary confirm" disabled={busy} onClick={() => post(`/ai/authoring-requests/${request.id}/confirm`)}>Confirm and activate rule</button></div></div>
        </>}
        {request.state === "ACTIVATED" && <div className="state success"><b>Activated after explicit confirmation.</b><a href={`/rules/${request.activation_result?.rule?.id}`}>Open created rule</a></div>}
        <details className="inline-details"><summary>Technical details</summary><pre>{JSON.stringify({interpreted: request.interpreted_intent, reviewed_draft: draft, states: request.state_trace, tools: request.tool_trace}, null, 2)}</pre></details>
      </SectionCard>
    </>}
  </main>;
}

export function App() {
  const path = location.pathname, issue = path.match(/^\/issues\/([^/]+)$/), rule = path.match(/^\/rules\/([^/]+)$/);
  return <><Header/>{path === "/rules/new/ai" ? <AiAuthoringView/> : issue ? <IssueView issueId={issue[1]}/> : rule ? <RuleView ruleId={rule[1]}/> : path === "/rules" ? <Rules/> : <PortfolioView/>}</>;
}

const root = document.getElementById("root");
if (root) ReactDOM.createRoot(root).render(<React.StrictMode><App/></React.StrictMode>);
