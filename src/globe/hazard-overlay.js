import mapboxgl from 'mapbox-gl';
import { activeAreaNotices, verifiedAreaNotices } from './hazards.js';
import { cssToken } from '../settings.js';

const empty = () => ({ type: 'FeatureCollection', features: [] });
export function createHazardOverlay(map, { beforeLayer, onNotices = () => {} }) {
  const high = cssToken('--hazard-high', '#B07857'), severe = cssToken('--hazard-severe', '#AD6068');
  const restricted = cssToken('--hazard-restricted', '#8C6477');
  const seaColor = ['case', ['>=', ['get', 'thresholdM'], 6], severe, high];
  let notices = [], previousSeas = null, previousNotices = '', popup = null;
  const visible = { hazards: true, restrictions: true };
  const groups = { hazards: [], restrictions: [] };
  const polygon = ['==', ['geometry-type'], 'Polygon'];
  const add = (group, layer) => { groups[group].push(layer.id); map.addLayer(layer, beforeLayer); };
  map.addSource('sea-hazards', { type: 'geojson', data: empty(), tolerance: 0.1 });
  map.addSource('area-notices', { type: 'geojson', data: empty() });
  add('hazards', { id: 'sea-hazard-fill', type: 'fill', source: 'sea-hazards', filter: polygon,
    paint: { 'fill-color': seaColor, 'fill-opacity': 0.12 } });

  const hatch = document.createElement('canvas'); hatch.width = hatch.height = 12;
  const ctx = hatch.getContext('2d'); ctx.strokeStyle = restricted; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(-6, 12); ctx.lineTo(6, 0); ctx.moveTo(6, 12); ctx.lineTo(18, 0); ctx.stroke();
  map.addImage('notice-hatch', ctx.getImageData(0, 0, 12, 12));
  add('restrictions', { id: 'area-notice-fill', type: 'fill', source: 'area-notices', paint: { 'fill-color': restricted, 'fill-opacity': 0.055 } });
  add('restrictions', { id: 'area-notice-hatch', type: 'fill', source: 'area-notices', paint: { 'fill-pattern': 'notice-hatch', 'fill-opacity': 0.3 } });
  add('restrictions', { id: 'area-notice-line', type: 'line', source: 'area-notices', paint: { 'line-color': restricted, 'line-width': 1.3, 'line-dasharray': [2, 2] } });
  const labelLayout = { 'text-field': ['get', 'label'], 'text-font': ['DIN Pro Medium', 'Arial Unicode MS Regular'],
    'text-size': 10, 'text-letter-spacing': 0.1, 'text-transform': 'uppercase', 'text-padding': 18 };
  add('restrictions', { id: 'area-notice-label', type: 'symbol', source: 'area-notices', layout: labelLayout,
    paint: { 'text-color': restricted } });

  function showDetails(event) {
    const p = event.features?.[0]?.properties;
    if (!p) return;
    const content = document.createElement('div'); content.className = 'hazard-card';
    const title = document.createElement('strong'); title.textContent = p.name || 'Verified area notice';
    const detail = document.createElement('p');
    detail.textContent = `${p.action === 'exclude' ? 'Exclusion' : 'Review notice'} · ${p.validFrom || 'No start specified'} → ${p.validTo || 'No end specified'}. Applies to this supplied notice only.`;
    content.append(title, detail);
    if (p.sourceUrl && /^https?:\/\//i.test(p.sourceUrl)) {
      const link = document.createElement('a'); link.href = p.sourceUrl; link.textContent = 'Source notice'; link.target = '_blank'; link.rel = 'noopener noreferrer'; content.append(link);
    }
    popup?.remove(); popup = new mapboxgl.Popup({ closeButton: true, maxWidth: '290px', className: 'hazard-popup' }).setLngLat(event.lngLat).setDOMContent(content).addTo(map);
  }
  for (const id of ['area-notice-fill']) {
    map.on('click', id, showDetails);
    map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
  }
  return {
    setSeas(data) { if (previousSeas !== data) { previousSeas = data; map.getSource('sea-hazards').setData(data || empty()); } },
    setNotices(overlays) { notices = verifiedAreaNotices(overlays); previousNotices = ''; },
    setTime(when) {
      const data = activeAreaNotices(notices, when), key = JSON.stringify(data.features.map(f => f.properties.id || f.properties.name));
      if (key !== previousNotices) { map.getSource('area-notices').setData(data); previousNotices = key; }
      onNotices({ available: notices.length, active: data.features.length });
    },
    setVisible(group, next) { visible[group] = next; groups[group]?.forEach(id => map.setLayoutProperty(id, 'visibility', next ? 'visible' : 'none')); popup?.remove(); },
    destroy() { popup?.remove(); }
  };
}
