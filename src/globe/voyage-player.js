import mapboxgl from 'mapbox-gl';
import { createVoyageTrack } from './voyage.js';
import { cssDurationMs } from '../settings.js';

export function createVoyagePlayer(map, { onTick = () => {}, onState = () => {} }) {
  const element = document.createElement('div');
  element.className = 'voyage-ship';
  element.setAttribute('aria-label', 'Simulated vessel position');
  element.innerHTML = `<div class="voyage-ship__heading"><svg viewBox="-22 -32 44 64" aria-hidden="true">
    <path class="voyage-ship__wake" d="M-4 15 -9 29 M4 15 9 29 M0 18 0 31"/>
    <path class="voyage-ship__hull" d="M0-15 C3-12 7-5 7 2 L6 13 -6 13 -7 2 C-7-5-3-12 0-15Z"/>
    <path class="voyage-ship__deck" d="M-3-3 3-3 3 7 -3 7Z M-3 9 3 9"/>
  </svg></div>`;
  const marker = new mapboxgl.Marker({ element, anchor: 'center' });
  const headingElement = element.firstElementChild;
  let track = null, hour = 0, playing = false, active = true, raf = null, previous = 0, heading = null;
  let lastTick = 0;
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const durationMs = cssDurationMs('--voyage-preview-duration', 90_000);
  function render(delta = 16, force = false) {
    if (!track) return;
    const position = track.at(hour);
    if (!position.coordinates) return;
    const next = track.at(Math.min(track.duration, hour + Math.min(0.2, track.duration / 1000)));
    const a = position.coordinates, b = next.coordinates;
    if (b && (a[0] !== b[0] || a[1] !== b[1])) {
      const lon = a[0] + ((b[0] - a[0] + 540) % 360 - 180);
      const start = map.project(a), end = map.project([lon, b[1]]);
      const target = Math.atan2(end.x - start.x, -(end.y - start.y)) * 180 / Math.PI;
      if (heading === null || force) heading = target;
      else heading += ((target - heading + 540) % 360 - 180) * (1 - Math.exp(-delta / 180));
      headingElement.style.transform = `rotate(${heading}deg)`;
    }
    marker.setLngLat(a);
    element.dataset.waiting = String(position.kind === 'canal_wait');
    const now = performance.now();
    if (force || now - lastTick >= 80) {
      lastTick = now;
      onTick({ hour, duration: track.duration, coordinates: a, kind: position.kind, waveHeightM: position.waveHeightM });
    }
  }
  function setPlaying(next) {
    playing = Boolean(next && track && active && !document.hidden);
    cancelAnimationFrame(raf); raf = null; previous = 0;
    if (playing) {
      if (hour >= track.duration) hour = 0;
      raf = requestAnimationFrame(frame);
    }
    if (!playing) render(0, true);
    onState({ playing, hour });
  }
  function frame(now) {
    if (!playing || !active || !track) return;
    const elapsed = previous ? now - previous : 0;
    previous = now;
    hour = Math.min(track.duration, hour + elapsed / durationMs * track.duration);
    render(elapsed);
    if (hour >= track.duration) { render(0, true); setPlaying(false); }
    else raf = requestAnimationFrame(frame);
  }
  function visibility() { if (document.hidden) setPlaying(false); }
  function motionPreference() { if (reducedMotion.matches) setPlaying(false); }
  document.addEventListener('visibilitychange', visibility);
  reducedMotion.addEventListener('change', motionPreference);
  return {
    load(route, departure) {
      setPlaying(false);
      track = createVoyageTrack(route, departure);
      hour = 0; heading = null;
      marker.setLngLat(track.at(0).coordinates).addTo(map);
      render(0, true);
      if (!reducedMotion.matches) setPlaying(true);
    },
    seek(fraction) {
      if (!track) return;
      hour = Math.max(0, Math.min(1, fraction)) * track.duration;
      render(0, true);
      if (hour === track.duration) setPlaying(false);
    },
    toggle() { setPlaying(!playing); },
    restart() { hour = 0; render(0, true); setPlaying(true); },
    setActive(next) { active = next; if (!next) setPlaying(false); },
    destroy() { setPlaying(false); marker.remove(); document.removeEventListener('visibilitychange', visibility); reducedMotion.removeEventListener('change', motionPreference); }
  };
}
