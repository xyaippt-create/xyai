import assert from "node:assert/strict";
import test from "node:test";
import { currentBatchCandidate, selectedBatchCandidates } from "../../src/localRetouchBatch.js";

test("蒙版改变立即使旧候选不可显示或确认，保存绑定逐图会话", () => {
  const items = [
    { item_id: "a", status: "candidate", candidate: { session_id: "source-a-candidate", mask_revision: 3 } },
    { item_id: "b", status: "candidate", candidate: { session_id: "source-b-candidate", mask_revision: 2 } },
    { item_id: "c", status: "failed", candidate: null },
    { item_id: "d", status: "saved", candidate: { session_id: "source-d-candidate", mask_revision: 3 } },
  ];
  assert.equal(currentBatchCandidate(items[0], 4), null);
  assert.equal(currentBatchCandidate(items[3], 4), items[3].candidate, "新选区不应隐藏已另存的成品");
  assert.deepEqual(selectedBatchCandidates({ items }, ["a", "b", "c", "d"], 3), [{ item_id: "a", session_id: "source-a-candidate" }]);
  assert.deepEqual(selectedBatchCandidates({ items }, ["a", "b"], 4), []);
});
