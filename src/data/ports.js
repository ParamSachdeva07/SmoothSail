// Port reference data.
//
// Shape matches the MVP's `Port` type (AUDIT-MVP.md §6 / src/lib/types.ts):
//   { id, name, country, code (UN/LOCODE), coordinates: [lon, lat] }
// The coordinate is the *sea-side approach*, not the berth — the MVP snaps it
// to the nearest connected node of the sea-lane network (mean 6.1 nm, worst
// 18.2 nm). Keeping the same shape means swapping this file for the MVP's
// `PORTS` export is a one-line change.

export const PORTS = [
  { id: 'ningbo', name: 'Ningbo-Zhoushan', country: 'China', code: 'CNNGB', coordinates: [121.95, 29.87] },
  { id: 'shanghai', name: 'Shanghai', country: 'China', code: 'CNSHA', coordinates: [121.8, 31.0] },
  { id: 'shenzhen', name: 'Shenzhen', country: 'China', code: 'CNSZX', coordinates: [113.9, 22.5] },
  { id: 'qingdao', name: 'Qingdao', country: 'China', code: 'CNTAO', coordinates: [120.3, 36.0] },
  { id: 'hong-kong', name: 'Hong Kong', country: 'Hong Kong SAR', code: 'HKHKG', coordinates: [114.13, 22.25] },
  { id: 'busan', name: 'Busan', country: 'South Korea', code: 'KRPUS', coordinates: [129.08, 35.08] },
  { id: 'singapore', name: 'Singapore', country: 'Singapore', code: 'SGSIN', coordinates: [103.8, 1.23] },
  { id: 'port-klang', name: 'Port Klang', country: 'Malaysia', code: 'MYPKG', coordinates: [101.35, 2.99] },
  { id: 'jebel-ali', name: 'Jebel Ali', country: 'United Arab Emirates', code: 'AEJEA', coordinates: [55.02, 24.98] },
  { id: 'colombo', name: 'Colombo', country: 'Sri Lanka', code: 'LKCMB', coordinates: [79.82, 6.94] },
  { id: 'mundra', name: 'Mundra', country: 'India', code: 'INMUN', coordinates: [69.7, 22.73] },
  { id: 'felixstowe', name: 'Felixstowe', country: 'United Kingdom', code: 'GBFXT', coordinates: [1.33, 51.95] },
  { id: 'southampton', name: 'Southampton', country: 'United Kingdom', code: 'GBSOU', coordinates: [-1.4, 50.88] },
  { id: 'rotterdam', name: 'Rotterdam', country: 'Netherlands', code: 'NLRTM', coordinates: [4.05, 51.95] },
  { id: 'antwerp', name: 'Antwerp', country: 'Belgium', code: 'BEANR', coordinates: [4.3, 51.35] },
  { id: 'hamburg', name: 'Hamburg', country: 'Germany', code: 'DEHAM', coordinates: [8.8, 53.9] },
  { id: 'le-havre', name: 'Le Havre', country: 'France', code: 'FRLEH', coordinates: [0.08, 49.48] },
  { id: 'marseille', name: 'Marseille', country: 'France', code: 'FRMRS', coordinates: [5.3, 43.3] },
  { id: 'algeciras', name: 'Algeciras', country: 'Spain', code: 'ESALG', coordinates: [-5.45, 36.08] },
  { id: 'valencia', name: 'Valencia', country: 'Spain', code: 'ESVLC', coordinates: [-0.3, 39.43] },
  { id: 'piraeus', name: 'Piraeus', country: 'Greece', code: 'GRPIR', coordinates: [23.6, 37.93] },
  { id: 'istanbul', name: 'Istanbul', country: 'Türkiye', code: 'TRIST', coordinates: [28.9, 40.97] },
  { id: 'gdansk', name: 'Gdańsk', country: 'Poland', code: 'PLGDN', coordinates: [18.75, 54.4] },
  { id: 'new-york', name: 'New York / New Jersey', country: 'United States', code: 'USNYC', coordinates: [-74.05, 40.5] },
  { id: 'savannah', name: 'Savannah', country: 'United States', code: 'USSAV', coordinates: [-80.85, 31.98] },
  { id: 'houston', name: 'Houston', country: 'United States', code: 'USHOU', coordinates: [-94.9, 29.3] },
  { id: 'los-angeles', name: 'Los Angeles', country: 'United States', code: 'USLAX', coordinates: [-118.3, 33.6] },
  { id: 'vancouver', name: 'Vancouver', country: 'Canada', code: 'CAVAN', coordinates: [-123.3, 49.28] },
  { id: 'santos', name: 'Santos', country: 'Brazil', code: 'BRSSZ', coordinates: [-46.3, -24.02] },
  { id: 'buenos-aires', name: 'Buenos Aires', country: 'Argentina', code: 'ARBUE', coordinates: [-58.3, -34.7] },
  { id: 'valparaiso', name: 'Valparaíso', country: 'Chile', code: 'CLVAP', coordinates: [-71.65, -33.03] },
  { id: 'durban', name: 'Durban', country: 'South Africa', code: 'ZADUR', coordinates: [31.05, -29.87] },
  { id: 'sydney', name: 'Sydney', country: 'Australia', code: 'AUSYD', coordinates: [151.25, -33.87] },
  { id: 'melbourne', name: 'Melbourne', country: 'Australia', code: 'AUMEL', coordinates: [144.9, -37.85] }
];

export function findPort(id) {
  return PORTS.find((port) => port.id === id) ?? null;
}

export function searchPorts(query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return PORTS;
  return PORTS.filter((port) =>
    `${port.name} ${port.country} ${port.code}`.toLowerCase().includes(needle));
}
