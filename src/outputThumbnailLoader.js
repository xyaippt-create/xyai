export const OUTPUT_THUMBNAIL_MAX_CONCURRENCY = 4;
export const OUTPUT_THUMBNAIL_PREFETCH_MARGIN_PX = 640;

const PRIORITY = Object.freeze({ visible: 0, prefetch: 1 });

export function createOutputThumbnailQueue({ limit = OUTPUT_THUMBNAIL_MAX_CONCURRENCY } = {}) {
  const concurrency = Math.max(1, Number(limit) || OUTPUT_THUMBNAIL_MAX_CONCURRENCY);
  const queued = new Map();
  const active = new Set();
  let sequence = 0;
  let prefetchPumpPending = false;

  const release = (itemId) => {
    if (!active.delete(itemId)) return;
    pump();
  };

  const pump = () => {
    while (active.size < concurrency && queued.size) {
      const next = [...queued.values()].sort((left, right) => (
        left.priority - right.priority || left.sequence - right.sequence
      ))[0];
      queued.delete(next.itemId);
      active.add(next.itemId);
      try {
        next.start(() => release(next.itemId));
      } catch {
        release(next.itemId);
      }
    }
  };

  const schedule = (itemId, priority, start) => {
    const normalizedPriority = PRIORITY[priority] ?? PRIORITY.prefetch;
    if (active.has(itemId)) return;
    const existing = queued.get(itemId);
    if (existing) {
      if (normalizedPriority < existing.priority) {
        existing.priority = normalizedPriority;
        existing.start = start;
      }
    } else {
      queued.set(itemId, {
        itemId,
        priority: normalizedPriority,
        sequence: sequence++,
        start,
      });
    }
    if (normalizedPriority === PRIORITY.visible) {
      pump();
    } else if (!prefetchPumpPending) {
      prefetchPumpPending = true;
      queueMicrotask(() => {
        prefetchPumpPending = false;
        pump();
      });
    }
  };

  const cancel = (itemId) => queued.delete(itemId);

  return {
    schedule,
    cancel,
    inspect: () => ({ active: [...active], queued: [...queued.values()] }),
  };
}

export const outputThumbnailQueue = createOutputThumbnailQueue();
