// Tab order follows an item's lifecycle. `rendering` has to be here: the
// render endpoint moves the item out of in_review immediately, so without a
// tab of its own it would disappear from the queue for the 2-5 minutes the
// job takes, with nothing to show the render had even started.
export const TABS = [
  "idea",
  "in_review",
  "rendering",
  "scheduled",
  "posted",
  "failed",
  "rejected",
];

// Statuses the backend moves an item out of on its own, with no further input
// from the reviewer, AND that resolve within minutes -- so the queue can watch
// them to the end. `scheduled` also resolves on its own (the tick posts it) but
// does NOT belong here: scheduled_at can be days out, and adding it would poll
// every 10s for that whole time.
const TRANSIENT = new Set(["rendering"]);

export function hasActiveWork(items: { status: string }[]): boolean {
  return items.some((i) => TRANSIENT.has(i.status));
}
