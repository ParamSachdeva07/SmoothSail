import { geometryLines } from '../globe/geometry.js';

const STRATEGIES = { fastest: 'Fastest', economical: 'Cheapest', lowest_emissions: 'Lowest CO₂' };
let currentReport = null;

// Keep the complete response, including provenance and compliance metadata.
// View models add presentation labels; they never recalculate cost, fuel or ETA.
export function setReport(report) {
  validateReport(report);
  currentReport = report;
}
export const getReport = () => currentReport;
export const getRoutes = () => (currentReport?.routes ?? []).map(presentRoute);
export const findRoute = (id) => getRoutes().find((route) => route.id === id) ?? null;

export function validateReport(report) {
  if (!Array.isArray(report?.routes) || !report.routes.length) {
    throw new Error('No routes were returned for these ports. Please try another pair.');
  }
  const ids = new Set();
  for (const route of report.routes) {
    const lines = geometryLines(route.geometry);
    if (!route.id || ids.has(route.id) || !lines.length || lines.some((line) => !Array.isArray(line) || line.length < 2 || line.some((p) =>
      !Array.isArray(p) || p.length < 2 || !Number.isFinite(p[0]) || !Number.isFinite(p[1]) || Math.abs(p[1]) > 90))) {
      throw new Error('The routing service returned invalid route geometry. Please retry.');
    }
    ids.add(route.id);
  }
  return report;
}

export function presentRoute(route) {
  const canals = (route.canalTransits ?? []).map((canal) => canal.name).filter(Boolean);
  const passages = route.passageIds ?? [];
  const name = canals.length ? [...new Set(canals)].join(' + ')
    : passages.includes('suez') ? 'Suez Canal'
    : passages.includes('panama') ? 'Panama Canal'
    : passages.includes('south_africa') ? 'Cape of Good Hope' : 'Ocean passage';
  return { ...route, label: STRATEGIES[route.strategy] ?? 'Route option', name };
}

export function reportPort(report, role) {
  const port = report?.metadata?.ports?.[role];
  const route = report?.routes?.[0];
  const lines = geometryLines(route?.geometry);
  const endpoint = role === 'origin' ? lines[0]?.[0] : lines.at(-1)?.at(-1);
  return { name: port?.name ?? report?.[role] ?? role,
    code: port?.locode ?? report?.[role], coordinates: port?.approachCoordinates ?? endpoint };
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}
export function formatNumber(value, digits = 0) {
  return Number.isFinite(value) ? value.toLocaleString('en-GB', { maximumFractionDigits: digits }) : '—';
}
export function formatDuration(hours) {
  if (!Number.isFinite(hours)) return '—';
  const rounded = Math.round(hours);
  return `${Math.floor(rounded / 24)}d ${rounded % 24}h`;
}
export const formatNm = (nm) => `${formatNumber(nm)} nm`;
export function formatUsd(amount, { compact = false } = {}) {
  if (!Number.isFinite(amount)) return 'Unavailable';
  if (compact && amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(2)}M`;
  if (compact && amount >= 10_000) return `$${(amount / 1_000).toFixed(1)}k`;
  return `$${formatNumber(amount)}`;
}
export function coverageLabel(route) {
  return Number.isFinite(route.forecastCoveragePercent)
    ? `${formatNumber(route.forecastCoveragePercent)}% weather coverage` : 'Weather coverage unavailable';
}
