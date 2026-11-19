import test from "node:test";
import assert from "node:assert/strict";
import { pickRegionColors } from "../../src/printLayerColors.js";

function region(width, height, background, inked) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const i = (y * width + x) * 4;
    const cover = inked(x, y);
    const bg = background(x, y);
    const ink = [30, 80, 150];
    for (let c = 0; c < 3; c++) data[i + c] = bg[c] + (ink[c] - bg[c]) * cover;
    data[i + 3] = 255;
  }
  return data;
}
// Strokes 4 px wide every 12 px, with one anti-aliased pixel on each side.
const strokes = x => { const m = x % 12; return m >= 4 && m < 8 ? 1 : m === 3 || m === 8 ? 0.5 : 0; };
const hexRgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));

test("ink on flat paper is read from the poster and counted as flat", () => {
  const picked = pickRegionColors(region(120, 40, () => [250, 247, 240], strokes));
  assert.equal(picked.flat, true);
  hexRgb(picked.ink).forEach((v, c) => assert.ok(Math.abs(v - [30, 80, 150][c]) <= 6, picked.ink));
  hexRgb(picked.paper).forEach((v, c) => assert.ok(Math.abs(v - [250, 247, 240][c]) <= 3, picked.paper));
});

test("text over a sky gradient is not flat, so a single paper colour would change the design", () => {
  const sky = (x, y) => [150 + y * 2, 200 + y, 245];
  const picked = pickRegionColors(region(120, 40, sky, strokes));
  assert.equal(picked.flat, false);
  // The ink still follows the poster's own blue, not a fixed red.
  const [r, , b] = hexRgb(picked.ink);
  assert.ok(b > r, picked.ink);
});

test("an empty region gives no colours", () => {
  assert.equal(pickRegionColors(new Uint8ClampedArray(0)), null);
});
