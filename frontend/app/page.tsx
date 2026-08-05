"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ItemCard, { Item } from "@/components/ItemCard";
import { apiFetch } from "@/lib/api";

const TABS = ["in_review", "scheduled", "posted", "failed", "rejected", "idea"];

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
        <ItemCard key={i.id} item={i} onChanged={load} />
      ))}
      {items.length === 0 && <p className="text-sm text-gray-500">ไม่มีรายการ</p>}
    </main>
  );
}
