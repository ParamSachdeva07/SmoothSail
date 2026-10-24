// Form state lasts only for the current page session. Vessel assumptions and
// all voyage calculations belong to the API, not to a second frontend model.
export const shipment = {
  originId: 'NLRTM',
  destinationId: 'SGSIN',
  departure: new Date().toISOString().slice(0, 10)
};

export function toRouteRequest(state = shipment, now = new Date()) {
  if (!state.originId || !state.destinationId) throw new Error('Choose both ports from the suggestions.');
  if (state.originId === state.destinationId) throw new Error('Choose two different ports.');
  const day = state.departure;
  const date = new Date(`${day}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== day) {
    throw new Error('Choose a valid departure date.');
  }
  const today = now.toISOString().slice(0, 10);
  if (day < today) throw new Error('Choose today or a future departure date.');
  return {
    origin: state.originId,
    destination: state.destinationId,
    // Today means depart now; future dates use midnight UTC.
    ...(day === today ? {} : { departureTime: date.toISOString() })
  };
}

export function formatDate(iso) {
  if (!iso) return 'Unavailable';
  const date = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (!Number.isFinite(date.getTime())) return 'Unavailable';
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(date);
}

export function formatEta(iso) {
  if (!iso || !Number.isFinite(new Date(iso).getTime())) return 'Unavailable';
  return `${formatDate(iso)} · ${new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }).format(new Date(iso))} UTC`;
}
