import { api } from '../api/client.js';

// The API catalogue contains only ports supported by the deployed network.
// In-memory cache only; refresh the page to fetch the catalogue again.
export let PORTS = [];
let loading;
const countries = new Intl.DisplayNames(['en'], { type: 'region' });

export async function loadPorts() {
  if (PORTS.length) return PORTS;
  if (!loading) loading = api.getPorts().then(({ ports }) => {
    if (!Array.isArray(ports) || !ports.length) throw new Error('No supported ports are available. Please retry.');
    PORTS = ports.map((port) => ({
      ...port,
      code: port.id,
      country: /^[A-Z]{2}$/.test(port.country) ? countries.of(port.country) : port.country
    }));
    return PORTS;
  }).finally(() => { loading = null; });
  return loading;
}

export function findPort(id) {
  return PORTS.find((port) => port.id === id) ?? null;
}

export function searchPorts(query) {
  const needle = query.trim().toLowerCase();
  return PORTS.filter((port) =>
    `${port.name} ${port.country} ${port.code}`.toLowerCase().includes(needle));
}
