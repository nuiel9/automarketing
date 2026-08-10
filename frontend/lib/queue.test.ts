import { expect, test } from "vitest";
import { TABS, hasActiveWork } from "./queue";

// Every status an item can come to REST in must be reachable from some tab.
// `rendering` was missing, so clicking สร้างวิดีโอ made the item vanish from
// the queue with no sign the render had started.
//
// backend/app/state.py declares nine statuses; two are deliberately absent
// here because an item is never fetched in them:
//   - `planned`  -- declared for Phase 2+, nothing sets it today.
//   - `approved` -- a pass-through. api/items.py transitions approved ->
//                   scheduled inside the same request, so it never commits.
// If either ever becomes a resting status, this test should start failing.
test("every item status has a tab to appear under", () => {
  const BACKEND_STATUSES = [
    "idea",
    "in_review",
    "rendering",
    "scheduled",
    "posted",
    "failed",
    "rejected",
  ];
  expect([...TABS].sort()).toEqual([...BACKEND_STATUSES].sort());
});

test("a rendering item means the queue still has work to watch", () => {
  expect(hasActiveWork([{ status: "in_review" }, { status: "rendering" }])).toBe(true);
});

test("a queue with nothing rendering has no work to watch", () => {
  expect(hasActiveWork([{ status: "in_review" }, { status: "posted" }])).toBe(false);
});

test("an empty queue has no work to watch", () => {
  expect(hasActiveWork([])).toBe(false);
});
