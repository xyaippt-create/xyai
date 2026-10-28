import assert from "node:assert/strict";
import test from "node:test";

import {
  OUTPUT_THUMBNAIL_MAX_CONCURRENCY,
  OUTPUT_THUMBNAIL_PREFETCH_MARGIN_PX,
  createOutputThumbnailQueue,
} from "../../src/outputThumbnailLoader.js";

test("output thumbnail queue bounds concurrency and prioritizes visible work", async () => {
  assert.equal(OUTPUT_THUMBNAIL_MAX_CONCURRENCY, 4);
  assert.equal(OUTPUT_THUMBNAIL_PREFETCH_MARGIN_PX, 640);
  const queue = createOutputThumbnailQueue({ limit: 2 });
  const started = [];
  const releases = new Map();
  const start = (id) => (release) => {
    started.push(id);
    releases.set(id, release);
  };

  queue.schedule("prefetch-a", "prefetch", start("prefetch-a"));
  queue.schedule("prefetch-b", "prefetch", start("prefetch-b"));
  queue.schedule("visible-a", "visible", start("visible-a"));
  assert.deepEqual(started, ["visible-a", "prefetch-a"]);
  assert.equal(queue.inspect().active.length, 2);

  queue.schedule("visible-b", "visible", start("visible-b"));
  releases.get("visible-a")();
  assert.deepEqual(started, ["visible-a", "prefetch-a", "visible-b"]);
  assert.equal(queue.inspect().active.length, 2);

  releases.get("prefetch-a")();
  releases.get("visible-b")();
  await new Promise((resolve) => queueMicrotask(resolve));
  assert.deepEqual(started, ["visible-a", "prefetch-a", "visible-b", "prefetch-b"]);
});

test("queued offscreen thumbnail work can be cancelled before it starts", async () => {
  const queue = createOutputThumbnailQueue({ limit: 1 });
  const started = [];
  queue.schedule("visible", "visible", () => started.push("visible"));
  queue.schedule("far", "prefetch", () => started.push("far"));
  assert.equal(queue.cancel("far"), true);
  await new Promise((resolve) => queueMicrotask(resolve));
  assert.deepEqual(started, ["visible"]);
});
