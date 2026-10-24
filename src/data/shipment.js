// Demo shipment state.
//
// `toVoyageInput()` emits exactly the MVP's `VoyageInput` shape
// (AUDIT-MVP.md §6): origin/destination are full Port objects, `departure` is
// YYYY-MM-DD, and the remaining fields take the MVP's own defaults
// (speed 18 kn, container, balanced, canals open). When the real engine is
// wired, the call becomes:
//
//   planRoutes(network, toVoyageInput(state), marine)
//
// PLACEHOLDER: everything else on this object is demo cargo detail for the
// prototype — the MVP collects a goods category but has no cost model at all.

import { findPort } from './ports.js';

export const shipment = {
  originId: 'ningbo',
  destinationId: 'felixstowe',
  departure: '2026-11-23',

  // Cargo — fabric rolls, one full container load.
  cargo: {
    description: 'Fabric rolls — woven textile',
    containers: 1,
    containerType: "40ft dry",
    grossWeightKg: 18500,
    volumeCbm: 58,
    commodity: 'Textiles'
  },

  // Commercial terms behind the alert on screen 5.
  letterOfCredit: {
    reference: 'LC-4471-NB',
    latestShipmentDate: '2026-11-30',
    expiry: '2026-12-15'
  },

  // Vessel defaults, matching the MVP's Dashboard defaults.
  speedKnots: 18,
  vessel: 'container',
  priority: 'balanced'
};

export function toVoyageInput(state = shipment) {
  return {
    origin: findPort(state.originId),
    destination: findPort(state.destinationId),
    departure: state.departure,
    speed: state.speedKnots,
    vessel: state.vessel,
    priority: state.priority,
    avoidSuez: false,
    avoidPanama: false
  };
}

export function formatDate(iso) {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${date.getUTCDate()} ${months[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}
