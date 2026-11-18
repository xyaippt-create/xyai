import test from "node:test";
import assert from "node:assert/strict";
import { planPrintSize } from "../../src/printPreflight.js";

const image = { width: 7680, height: 4320 };
const order = { mode: "physical", axis: "width", cm: "200", ppi: "150" };

test("full width poster uses the requested physical width and rounds the pixel minimum up", () => {
  const plan = planPrintSize(image, order);
  assert.deepEqual([plan.pixelWidth, plan.pixelHeight], [11812, 6644]);
  assert.deepEqual([plan.cmWidth, plan.cmHeight], [200, 112.5]);
  assert.equal(plan.effectivePpi.toFixed(2), "97.54");
  assert.equal(plan.scale.toFixed(2), "1.54");
  assert.ok(planPrintSize(image, { ...order, ppi: 90 }).scale < 1);
});

test("an exact pixel boundary and a slightly insufficient source have different verdicts", () => {
  const exact = { ...order, cm: 25.4, ppi: 300 };
  const square = { width: 3000, height: 3000 };
  assert.equal(planPrintSize(square, exact).scale, 1);
  assert.equal(planPrintSize(square, { ...exact, cm: 25.40001 }).pixelWidth, 3001);
});

test("equivalent width and height give the same minimum pixels and scale", () => {
  const source = { width: 1280, height: 548 };
  const fromWidth = planPrintSize(source, { ...order, cm: 25.4, ppi: 100 });
  const fromHeight = planPrintSize(source, { ...order, axis: "height", cm: 10.874375, ppi: 100 });
  for (const plan of [fromWidth, fromHeight]) {
    assert.deepEqual([plan.pixelWidth, plan.pixelHeight], [1000, 429]);
    assert.equal(plan.scale, 429 / 548);
  }
});

test("height input and the 8K preset follow the portrait long edge", () => {
  const portrait = { width: 4320, height: 7680 };
  const byHeight = planPrintSize(portrait, { ...order, axis: "height" });
  assert.deepEqual([byHeight.cmWidth, byHeight.cmHeight], [112.5, 200]);
  const estimate = planPrintSize(portrait, { ...order, mode: "8k", cm: "", ppi: 300 });
  assert.deepEqual([estimate.pixelWidth, estimate.pixelHeight, estimate.scale], [4320, 7680, 1]);
  assert.equal(estimate.cmHeight.toFixed(2), "65.02");
  assert.ok(planPrintSize({ width: 8000, height: 4000 }, { ...order, mode: "8k" }).scale < 1);
});

test("invalid, out-of-range or missing order values cannot retain a successful plan", () => {
  for (const field of ["ppi", "cm"]) {
    for (const value of ["", "NaN", -1, 0, "Infinity", "1e308"]) {
      assert.ok(planPrintSize(image, { ...order, [field]: value }).error);
    }
  }
});

test("8K from a small colour source reports the detail left after 4K reconstruction", () => {
  const plan = planPrintSize({ width: 1672, height: 941 }, { mode: "8k", axis: "width", cm: "", ppi: "300" });
  assert.equal(plan.nominalPpi, 300);
  assert.equal(plan.reconstructed, true);
  assert.equal(plan.effectivePpi.toFixed(1), "65.3");
  assert.equal(plan.detailPpi.toFixed(1), "195.9");
  assert.equal(plan.soft, false);
  const banner = planPrintSize({ width: 1000, height: 563 }, { mode: "8k", axis: "width", cm: "", ppi: "300" });
  assert.equal(banner.soft, true);
  assert.equal(banner.interpolation.toFixed(2), "2.56");
  const large = planPrintSize({ width: 3000, height: 2000 }, { mode: "8k", axis: "width", cm: "", ppi: "300" });
  assert.equal(large.reconstructed, false);
  assert.equal(large.soft, true);
});
