// Candidate routes for the demo shipment (Ningbo-Zhoushan → Felixstowe).
//
// SHAPE: each option mirrors the MVP's `RouteOption` (AUDIT-MVP.md §2.2) —
// id, name, coordinates, distanceNm, durationHours, fuelTonnes, co2Tonnes,
// passages, maxWave, meanWind, forecastSamples/weatherCoverage. Those fields
// are computed here with the MVP's own formulas, so swapping in real
// `planRoutes()` output changes nothing downstream.
//
// PLACEHOLDER: `cost` and `risk` are prototype-only. AUDIT-MVP.md is explicit
// that the MVP has NO monetary model, no canal fees, no ETS and no war-risk /
// insurance — every figure in `cost` is an illustrative demo value, not a
// quote and not derived from a live feed.

// --- MVP voyage model (src/lib/routing.ts) ------------------------------
const FUEL_BASE_TONNES_PER_DAY = { container: 58, bulk: 32, tanker: 45 };
const CO2_PER_FUEL_TONNE = 3.114;          // tank-to-wake
const REFERENCE_SPEED_KNOTS = 18;

// --- Demo commercial assumptions (prototype only) -----------------------
export const COST_ASSUMPTIONS = {
  vlsfoUsdPerTonne: 610,         // bunker price, VLSFO
  vesselUsdPerDay: 34_000,       // charter + crew + opex, whole vessel
  etsUsdPerTonneCo2: 86,         // EU ETS allowance
  etsVoyageShare: 0.5            // 50% of an inbound voyage falls in EU scope
};

function voyageModel({ distanceNm, speedKnots, vessel = 'container' }) {
  const durationHours = distanceNm / speedKnots;
  const days = durationHours / 24;
  const fuelTonnes = days * FUEL_BASE_TONNES_PER_DAY[vessel] * (speedKnots / REFERENCE_SPEED_KNOTS) ** 3;
  return {
    durationHours,
    days,
    fuelTonnes,
    co2Tonnes: fuelTonnes * CO2_PER_FUEL_TONNE
  };
}

function buildCost(model, { canalFeeUsd, warRiskUsd, delayProvisionUsd }) {
  const fuel = model.fuelTonnes * COST_ASSUMPTIONS.vlsfoUsdPerTonne;
  const vesselDays = model.days * COST_ASSUMPTIONS.vesselUsdPerDay;
  const regulatory = model.co2Tonnes * COST_ASSUMPTIONS.etsVoyageShare * COST_ASSUMPTIONS.etsUsdPerTonneCo2;
  const lines = [
    { id: 'fuel', label: 'Bunkers (VLSFO)', amountUsd: fuel, note: `${Math.round(model.fuelTonnes).toLocaleString('en-GB')} t at $${COST_ASSUMPTIONS.vlsfoUsdPerTonne}/t` },
    { id: 'vessel', label: 'Vessel days', amountUsd: vesselDays, note: `${model.days.toFixed(1)} days at $${(COST_ASSUMPTIONS.vesselUsdPerDay / 1000).toFixed(0)}k/day` },
    { id: 'canal', label: 'Canal fees', amountUsd: canalFeeUsd, note: canalFeeUsd ? 'Suez Canal transit toll' : 'No canal transit' },
    { id: 'insurance', label: 'War-risk insurance', amountUsd: warRiskUsd, note: warRiskUsd > 50_000 ? 'Listed-area premium, Red Sea' : 'Standard hull cover only' },
    { id: 'regulatory', label: 'EU ETS allowances', amountUsd: regulatory, note: `${Math.round(model.co2Tonnes * COST_ASSUMPTIONS.etsVoyageShare).toLocaleString('en-GB')} t in scope at $${COST_ASSUMPTIONS.etsUsdPerTonneCo2}/t` },
    { id: 'delay', label: 'Delay-risk provision', amountUsd: delayProvisionUsd, note: 'Demurrage and storage exposure' }
  ];
  return { lines, totalUsd: lines.reduce((sum, line) => sum + line.amountUsd, 0) };
}

function makeRoute(definition) {
  const model = voyageModel(definition);
  return {
    ...definition,
    ...model,
    cost: buildCost(model, definition.costInputs)
  };
}

// Waypoints. PLACEHOLDER geometry: hand-authored sea lanes good enough to draw
// the corridor. The MVP derives these from Dijkstra over a 9,681-node sea-lane
// network and longitude-unwraps them for the antimeridian; `coordinates` is
// the same field name its RouteOption uses.
const LEG_EAST_ASIA_TO_MALACCA = [
  [121.95, 29.87], [122.6, 25.4], [119.5, 22.0], [114.4, 18.2],
  [108.6, 11.4], [105.6, 5.2], [103.8, 1.23]
];

const LEG_BISCAY_TO_FELIXSTOWE = [
  [-9.8, 43.4], [-5.2, 48.4], [-1.5, 49.6], [1.4, 50.4], [1.33, 51.95]
];

const SUEZ_COORDINATES = [
  ...LEG_EAST_ASIA_TO_MALACCA,
  [100.4, 3.6], [96.0, 5.6], [88.0, 6.2], [78.0, 7.4], [66.0, 10.6],
  [56.0, 12.4], [48.5, 12.1], [43.3, 12.6], [40.0, 17.2], [36.2, 23.6],
  [33.4, 27.8], [32.55, 29.95], [32.3, 31.4], [28.0, 33.0], [20.0, 34.2],
  [11.0, 37.2], [2.0, 37.0], [-5.6, 35.95], [-9.3, 37.2], [-9.8, 43.4],
  ...LEG_BISCAY_TO_FELIXSTOWE.slice(1)
];

const CAPE_COORDINATES = [
  ...LEG_EAST_ASIA_TO_MALACCA,
  [104.6, -1.2], [105.9, -6.0], [102.0, -9.5], [92.0, -12.0], [78.0, -16.0],
  [64.0, -21.0], [52.0, -26.0], [40.0, -31.0], [30.0, -34.6], [20.0, -35.4],
  [15.0, -32.0], [10.0, -25.0], [5.0, -15.0], [-1.0, -4.0], [-8.0, 5.0],
  [-16.0, 14.0], [-18.5, 24.0], [-14.0, 33.0], [-10.5, 38.0], [-9.8, 43.4],
  ...LEG_BISCAY_TO_FELIXSTOWE.slice(1)
];

export const ROUTES = [
  makeRoute({
    id: 'fastest',
    label: 'Fastest',
    name: 'Suez Canal transit',
    distanceNm: 10_420,
    speedKnots: 18.5,
    coordinates: SUEZ_COORDINATES,
    stops: [{ name: 'Singapore bunkering call', coordinates: [103.8, 1.23] }],
    vessel: 'container',
    passages: ['malacca', 'babalmandab', 'suez', 'gibraltar'],
    // Weather fields in the MVP's honesty format: sampled, may be null.
    maxWave: 3.4,
    meanWind: 21,
    forecastSamples: 8,
    weatherCoverage: 8,
    risk: { level: 'attention', summary: 'Transits a flagged conflict corridor' },
    tags: [
      { tone: 'warning', text: 'War-risk area · Bab al-Mandab' },
      { tone: 'warning', text: 'Wave 3.4 m sampled' }
    ],
    summary: [
      'Shortest sea distance: Malacca, Bab al-Mandab, Suez and Gibraltar, arriving Felixstowe 23 days 11 hours after departure.',
      'Carries a listed-area war-risk premium and a $465,000 Suez toll, which makes it the most expensive of the three.',
      'Buys roughly ten days against the Cape routing — the only option with slack before the 30 Nov LC shipment date.'
    ],
    costInputs: { canalFeeUsd: 465_000, warRiskUsd: 95_000, delayProvisionUsd: 60_000 }
  }),
  makeRoute({
    id: 'cheapest',
    label: 'Cheapest',
    name: 'Suez transit, slow steaming',
    distanceNm: 10_420,
    speedKnots: 15.3,
    coordinates: SUEZ_COORDINATES,
    stops: [{ name: 'Singapore bunkering call', coordinates: [103.8, 1.23] }],
    vessel: 'container',
    passages: ['malacca', 'babalmandab', 'suez', 'gibraltar'],
    maxWave: 3.4,
    meanWind: 21,
    forecastSamples: 8,
    weatherCoverage: 8,
    risk: { level: 'attention', summary: 'Same corridor, longer exposure window' },
    tags: [
      { tone: 'warning', text: 'War-risk area · Bab al-Mandab' },
      { tone: 'neutral', text: 'Slow steaming 15.3 kn' }
    ],
    summary: [
      'Identical geometry to the fastest option, run at 15.3 knots. The cubic speed law cuts bunkers by about 467 tonnes.',
      'Lowest total voyage cost of the three despite paying the same Suez toll and war-risk premium.',
      'Adds five days of transit, so the 18,500 kg of fabric lands after the Letter of Credit shipment date unless the LC is amended.'
    ],
    costInputs: { canalFeeUsd: 465_000, warRiskUsd: 95_000, delayProvisionUsd: 95_000 }
  }),
  makeRoute({
    id: 'lowest-risk',
    label: 'Lowest risk',
    name: 'Cape of Good Hope',
    distanceNm: 13_640,
    speedKnots: 17,
    coordinates: CAPE_COORDINATES,
    stops: [{ name: 'Singapore bunkering call', coordinates: [103.8, 1.23] },
            { name: 'Durban bunkering call', coordinates: [31.05, -29.87] }],
    vessel: 'container',
    passages: ['malacca', 'sunda', 'south_africa'],
    maxWave: 4.6,
    meanWind: 27,
    forecastSamples: 8,
    weatherCoverage: 7,
    risk: { level: 'clear', summary: 'Avoids all flagged conflict corridors' },
    tags: [
      { tone: 'positive', text: 'No listed-area transit' },
      { tone: 'warning', text: 'Southern Ocean swell 4.6 m' }
    ],
    summary: [
      'Routes south of Africa, clear of the Red Sea entirely — no Suez toll and only standard hull cover.',
      '3,220 nautical miles further and ten days longer, so bunkers rise to roughly 1,634 tonnes and ETS exposure with them.',
      'One forecast sample is unavailable off the Agulhas Bank; the 4.6 m figure is the highest of the seven returned.'
    ],
    costInputs: { canalFeeUsd: 0, warRiskUsd: 8_000, delayProvisionUsd: 120_000 }
  })
];

export function findRoute(id) {
  return ROUTES.find((route) => route.id === id) ?? null;
}

// --- Formatters (mirrors the MVP's src/lib/format.ts conventions) -------
export function formatDuration(hours) {
  const days = Math.floor(hours / 24);
  return `${days}d ${Math.round(hours - days * 24)}h`;
}

export function formatNm(nm) {
  return `${Math.round(nm).toLocaleString('en-GB')} nm`;
}

export function formatUsd(amount, { compact = false } = {}) {
  if (compact) return `$${(amount / 1_000_000).toFixed(2)}M`;
  return `$${Math.round(amount).toLocaleString('en-GB')}`;
}

export function arrivalDate(departureIso, durationHours) {
  const date = new Date(`${departureIso}T00:00:00Z`);
  date.setUTCHours(date.getUTCHours() + Math.round(durationHours));
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${date.getUTCDate()} ${months[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}
