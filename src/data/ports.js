import { api } from '../api/client.js';

// Cache only seen records. The API searches the full supported catalogue.
export let PORTS = [];
let loading;
const countries = new Intl.DisplayNames(['en'], { type: 'region' });
const FEATURED_IDS = ['NLRTM', 'SGSIN', 'INBOM', 'FRLEH', 'DEHAM', 'USNYC', 'USLAX', 'JPTYO', 'AUSYD', 'PTLIS'];

function remember(ports) {
  if (!Array.isArray(ports)) throw new Error('The port catalogue returned an invalid response.');
  const byId = new Map(PORTS.map(port => [port.id, port]));
  for (const port of ports) byId.set(port.id, {
    ...port, code: port.id,
    country: /^[A-Z]{2}$/.test(port.country) ? countries.of(port.country) : port.country
  });
  PORTS = [...byId.values()];
  return ports.map(port => byId.get(port.id));
}

export async function loadPorts() {
  if (PORTS.length) return PORTS;
  if (!loading) loading = api.getPorts({ limit: 50 }).then(async ({ ports }) => {
    if (!Array.isArray(ports) || !ports.length) throw new Error('No supported ports are available. Please retry.');
    remember(ports);
    await Promise.allSettled(FEATURED_IDS.filter(id => !findPort(id)).map(ensurePort));
    return PORTS;
  }).finally(() => { loading = null; });
  return loading;
}

export async function ensurePort(id) {
  if (!id || findPort(id)) return findPort(id);
  const { ports } = await api.getPorts({ query: id, limit: 1 });
  return remember(ports).find(port => port.id === id) ?? null;
}

export function findPort(id) {
  return PORTS.find((port) => port.id === id) ?? null;
}

export async function searchPorts(query, { signal } = {}) {
  const needle = query.trim();
  if (!needle) {
    const featured = FEATURED_IDS.map(findPort).filter(Boolean);
    return [...featured, ...PORTS.filter(port => !FEATURED_IDS.includes(port.id))].slice(0, 20);
  }
  if (needle.length < 2) return PORTS.filter(port =>
    `${port.name} ${port.country} ${port.code}`.toLowerCase().includes(needle.toLowerCase())).slice(0, 20);
  const { ports } = await api.getPorts({ query: needle, limit: 20, signal });
  return remember(ports);
}
