"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ItemCard, { Item } from "@/components/ItemCard";
import { apiFetch } from "@/lib/api";
import { TABS, hasActiveWork } from "@/lib/queue";

// A render takes 2-5 minutes, so a slow poll keeps the card's progress line
// honest without hammering the backend.
const POLL_MS = 10_000;

export default function Queue() {
  const [tab, setTab] = useState("in_review");
  const [items, setItems] = useState<Item[]>([]);
  const load = useCallback(async () => {
    try {
      setItems((await apiFetch(`/api/items?status=${tab}`)) as Item[]);
    } catch {
      window.location.href = "/login";
    }
  }, [tab]);
  useEffect(() => { load(); }, [load]);

  // Nothing the reviewer does moves an item out of `rendering` -- the render
  // job does it in the background -- so the queue has to look again itself,
  // or the card sits on "กำลังสร้างวิดีโอ…" until a manual reload.
  useEffect(() => {
    if (!hasActiveWork(items)) return;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [items, load]);

  return (
    <main className="mx-auto max-w-2xl space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Review Queue</h1>
        <Link href="/new" className="rounded bg-black px-3 py-2 text-sm text-white">
          + คอนเทนต์ใหม่
        </Link>
      </div>
      <div className="flex gap-2 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded px-3 py-1 text-sm ${tab === t ? "bg-black text-white" : "bg-gray-100"}`}
          >
            {t}
          </button>
        ))}
      </div>
      {items.map((i) => (
        <ItemCard
          key={i.id}
          item={i}
          onChanged={(nextTab) => (nextTab ? setTab(nextTab) : load())}
        />
      ))}
      {items.length === 0 && (
        <p className="text-sm text-gray-500">
          {tab === "rendering"
            ? "ไม่มีวิดีโอที่กำลังสร้าง — ถ้าเพิ่งสร้างเสร็จ ดูที่แท็บ in_review"
            : "ไม่มีรายการ"}
        </p>
      )}
    </main>
  );
}
