import test from 'node:test';
import assert from 'node:assert/strict';
import { portPopupPlacement } from '../src/globe/port-popup.js';

const view = { width: 1200, height: 800, naturalHeight: 600 };
test('port panels open down near the top and up near the bottom', () => {
  const top = portPopupPlacement({ ...view, x: 600, y: 100 });
  assert.equal(top.side, 'below'); assert.equal(top.top, 114);
  const bottom = portPopupPlacement({ ...view, x: 600, y: 700 });
  assert.equal(bottom.side, 'above');
  assert.equal(bottom.top + Math.min(view.naturalHeight, bottom.maxHeight), 646);
});

test('expanded content stays within every viewport edge, including narrow mobile views', () => {
  for (const width of [320, 800, 1200]) for (const height of [300, 600, 900]) {
    for (const x of [0, width / 2, width]) for (const y of [0, height / 2, height]) {
      const placement = portPopupPlacement({ width, height, x, y, naturalHeight: 1000 });
      assert.ok(placement.left >= 16);
      assert.ok(placement.left + placement.width <= width - 16);
      assert.ok(placement.top >= 16);
      assert.ok(placement.top + placement.maxHeight <= height - 16);
    }
  }
});

test('changing content height preserves the chosen side without overlap with the port', () => {
  for (const y of [100, 650]) {
    const small = portPopupPlacement({ ...view, x: 600, y, naturalHeight: 80 });
    const expanded = portPopupPlacement({ ...view, x: 600, y, naturalHeight: 1200 });
    assert.equal(small.side, expanded.side);
    assert.equal(small.maxHeight, expanded.maxHeight);
    if (small.side === 'above') assert.ok(expanded.top + expanded.maxHeight <= y - 54);
    else assert.ok(expanded.top >= y + 14);
  }
});
