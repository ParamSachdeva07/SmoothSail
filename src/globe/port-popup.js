/** Keep a port-anchored panel inside the map; the roomier side wins. */
export function portPopupPlacement({ x, y, width, height, naturalHeight, preferredWidth = 360, margin = 16 }) {
  const panelWidth = Math.max(0, Math.min(preferredWidth, width - margin * 2));
  const above = Math.max(0, y - 54 - margin);
  const below = Math.max(0, height - y - 14 - margin);
  const side = below >= above ? 'below' : 'above';
  const maxHeight = Math.min(Math.max(0, height - margin * 2), side === 'below' ? below : above);
  const panelHeight = Math.min(naturalHeight, maxHeight);
  return {
    side, width: panelWidth, maxHeight,
    left: Math.max(margin, Math.min(x - panelWidth / 2, width - panelWidth - margin)),
    top: Math.max(margin, Math.min(side === 'below' ? y + 14 : y - 54 - panelHeight, height - panelHeight - margin))
  };
}

/** Reposition one small DOM panel during camera moves, expansion and streamed findings. */
export function createPortPopup({ map, container, coordinates, card, label, onClose }) {
  const element = document.createElement('div');
  element.className = 'mapboxgl-popup congestion-popup port-popup';
  element.setAttribute('role', 'dialog'); element.setAttribute('aria-label', label);
  const content = document.createElement('div'); content.className = 'mapboxgl-popup-content';
  const close = document.createElement('button'); close.className = 'mapboxgl-popup-close-button';
  close.type = 'button'; close.setAttribute('aria-label', 'Close popup'); close.textContent = '×';
  content.append(card, close); element.append(content); container.append(element);
  let frame = null, removed = false;
  function position() {
    frame = null;
    if (removed) return;
    const { x, y } = map.project(coordinates);
    const width = container.clientWidth, height = container.clientHeight;
    element.hidden = x < 0 || x > width || y < 0 || y > height;
    const placement = portPopupPlacement({ x, y, width, height, naturalHeight: content.scrollHeight + 2 });
    element.dataset.placement = placement.side;
    element.style.width = `${placement.width}px`;
    element.style.left = `${placement.left}px`; element.style.top = `${placement.top}px`;
    content.style.maxHeight = `${placement.maxHeight}px`;
  }
  function schedule() { if (!removed && frame == null) frame = requestAnimationFrame(position); }
  const observer = new ResizeObserver(schedule); observer.observe(content);
  map.on('move', schedule); map.on('resize', schedule);
  element.addEventListener('toggle', schedule, true);
  element.addEventListener('click', event => event.stopPropagation());
  const popup = {
    getElement: () => element,
    update: schedule,
    remove() {
      if (removed) return; removed = true;
      if (frame != null) cancelAnimationFrame(frame);
      observer.disconnect(); map.off('move', schedule); map.off('resize', schedule);
      element.remove(); onClose();
    }
  };
  close.addEventListener('click', () => popup.remove());
  position();
  return popup;
}
