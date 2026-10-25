import test from 'node:test';
import assert from 'node:assert/strict';
import { nearestWorldLongitude, shipZoomScale, latitudeWithinCoverage } from '../src/globe/map-navigation.js';
test('ports follow the nearest world across repeated antimeridian crossings', () => {
  assert.equal(nearestWorldLongitude(4, 730), 724);
  assert.equal(nearestWorldLongitude(4, -710), -716);
});
test('ship size scales continuously and stays legible', () => {
  assert.ok(shipZoomScale(2) < shipZoomScale(3));
  assert.ok(shipZoomScale(3.01) - shipZoomScale(3) < .01);
  assert.equal(shipZoomScale(20), 2);
});
test('polar bounds retain viewport coverage without changing longitude', () => {
  const bounds = [[-180,-60],[180,70]];
  assert.ok(latitudeWithinCoverage(85,bounds,3,800) < 70);
  assert.ok(latitudeWithinCoverage(-85,bounds,3,800) > -60);
  assert.equal(latitudeWithinCoverage(0,bounds,3,800), 0);
});
