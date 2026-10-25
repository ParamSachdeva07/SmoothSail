import { shipZoomScale } from './map-navigation.js';
import mapboxgl from 'mapbox-gl';
import { createVoyageTrack } from './voyage.js';
import { cssDurationMs } from '../settings.js';

export function createVoyagePlayer(map, { onTick = () => {}, onTime = () => {}, onState = () => {} }) {
  const element = document.createElement('div');
  element.className = 'voyage-ship';
  element.setAttribute('aria-label', 'Simulated vessel position');
  element.innerHTML = '<div class="voyage-ship__heading" aria-hidden="true"><span class="voyage-ship__body"></span></div>';
  const marker = new mapboxgl.Marker({ element, anchor: 'center' });
  const headingElement = element.firstElementChild;
  let track = null, hour = 0, playing = false, active = true, raf = null, previous = 0, heading = null, speed = 1;
  const scaleShip = () => { element.style.setProperty('--ship-scale', shipZoomScale(map.getZoom())); };
  map.on('zoom', scaleShip); scaleShip();
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
    onTime(hour, force);
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
    onState({ playing, hour, duration: track?.duration ?? 0, speed });
  }
  function frame(now) {
    if (!playing || !active || !track) return;
    const elapsed = previous ? now - previous : 0;
    previous = now;
    hour = Math.min(track.duration, hour + elapsed * speed / durationMs * track.duration);
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
      onState({ playing: false, hour, duration: track.duration, speed });
    },
    seek(fraction) {
      if (!track) return;
      hour = Math.max(0, Math.min(1, fraction)) * track.duration;
      render(0, true);
      if (hour === track.duration) setPlaying(false);
    },
    toggle() { setPlaying(!playing); },
    restart() { hour = 0; render(0, true); setPlaying(true); },
    setSpeed(next) {
      if (![1, 1.5, 2, 4].includes(next)) return;
      speed = next;
      onState({ playing, hour, duration: track?.duration ?? 0, speed });
    },
    setActive(next) { active = next; if (!next) setPlaying(false); },
    destroy() { map.off('zoom', scaleShip); setPlaying(false); marker.remove(); document.removeEventListener('visibilitychange', visibility); reducedMotion.removeEventListener('change', motionPreference); }
  };
}
