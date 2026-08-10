"use client";
import { useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

type Caption = {
  channel: string; title: string | null; body: string;
  hashtags: string[]; edited_by_human: boolean;
};
type Publication = {
  channel: string; status: string; scheduled_at: string | null;
  posted_at: string | null; post_ref: string | null;
  attempts: number; last_error: string | null;
};
export type Item = {
  id: string; slug: string; topic: string; status: string;
  media_url: string | null; banned_violations: string[];
  reject_reason: string | null; captions: Caption[]; publications: Publication[];
  scenario: string | null;
  render_error: string | null;
};

const CHANNELS = ["tiktok", "youtube", "instagram", "facebook", "x", "line"];

export default function ItemCard({
  item,
  onChanged,
}: {
  item: Item;
  // `nextTab` moves the queue to the tab where the item just landed -- an
  // action that changes an item's status moves it out of the current list.
  onChanged: (nextTab?: string) => void;
}) {
  const [captions, setCaptions] = useState<Caption[]>(item.captions);
  const [when, setWhen] = useState("");
  const [channels, setChannels] = useState<string[]>(["facebook", "instagram", "x", "line"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fmt, setFmt] = useState("demo");
  const [scenario, setScenario] = useState(item.scenario ?? "");
  const originalBodies = useRef<Record<string, string>>(
    Object.fromEntries(item.captions.map((c) => [c.channel, c.body]))
  );

  const act = async (fn: () => Promise<unknown>, nextTab?: string) => {
    setBusy(true); setError("");
    try { await fn(); onChanged(nextTab); } catch (e) { setError(String(e)); }
    setBusy(false);
  };

  const saveCaption = (c: Caption) =>
    act(() =>
      apiFetch(`/api/items/${item.id}/captions`, { method: "PUT", body: JSON.stringify(c) }).then(
        (result) => {
          originalBodies.current[c.channel] = c.body;
          return result;
        }
      )
    );

  return (
    <div className="space-y-3 rounded-xl border p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">{item.topic}</h2>
        <span className="rounded bg-gray-100 px-2 py-1 text-xs">{item.status}</span>
      </div>
      {item.media_url && (
        <video src={item.media_url} controls className="max-h-80 w-full rounded bg-black" />
      )}
      {item.banned_violations.length > 0 && (
        <p className="text-sm text-red-600">คำต้องห้าม: {item.banned_violations.join(", ")}</p>
      )}
      {captions.map((c) =>
        item.status === "in_review" || item.status === "idea" ? (
          <div key={c.channel} className="space-y-1">
            <label className="text-xs font-semibold uppercase">{c.channel}</label>
            <textarea
              className="w-full rounded border p-2 text-sm"
              rows={3}
              value={c.body}
              onChange={(e) =>
                setCaptions(captions.map((x) => (x.channel === c.channel ? { ...x, body: e.target.value } : x)))
              }
              onBlur={() => {
                const current = captions.find((x) => x.channel === c.channel)!;
                if (current.body !== originalBodies.current[c.channel]) {
                  saveCaption(current);
                }
              }}
            />
          </div>
        ) : (
          <div key={c.channel} className="space-y-1">
            <label className="text-xs font-semibold uppercase">{c.channel}</label>
            <p className="w-full whitespace-pre-wrap rounded border bg-gray-50 p-2 text-sm">{c.body}</p>
          </div>
        )
      )}
      {!item.media_url && ["idea", "in_review", "failed"].includes(item.status) && (
        <div className="space-y-2 rounded border border-dashed p-3">
          <p className="text-sm font-medium">สร้างวิดีโออัตโนมัติ</p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="rounded border p-2 text-sm"
              value={fmt}
              onChange={(e) => setFmt(e.target.value)}
            >
              <option value="demo">เดโมสินค้า</option>
              <option value="tips">การ์ดเคล็ดลับ</option>
              {/* Labelled with its cost: motion_ad is the only format that
                  spends AIVDO credits, and they are deducted the moment the
                  render is dispatched -- not refunded if it fails afterwards.
                  The reviewer should see that before pressing the button. */}
              <option value="motion_ad">โฆษณาสั้น 11 วินาที (ใช้ 5 เครดิต)</option>
            </select>
            {fmt === "demo" && (
              <input
                className="rounded border p-2 text-sm"
                placeholder="ชื่อ scenario เช่น tgat-demo"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              />
            )}
            <button
              disabled={busy || (fmt === "demo" && !scenario)}
              className="rounded bg-indigo-600 px-3 py-2 text-sm text-white disabled:opacity-40"
              onClick={() =>
                act(
                  () =>
                    apiFetch(`/api/items/${item.id}/render`, {
                      method: "POST",
                      body: JSON.stringify({
                        format: fmt,
                        scenario: fmt === "demo" ? scenario : null,
                      }),
                    }),
                  "rendering"
                )
              }
            >
              สร้างวิดีโอ
            </button>
          </div>
        </div>
      )}
      {item.status === "rendering" && (
        <p className="text-sm text-indigo-600">กำลังสร้างวิดีโอ… (ปกติ 2–5 นาที)</p>
      )}
      {item.render_error && (
        <p className="text-sm text-red-600">เรนเดอร์ล้มเหลว: {item.render_error}</p>
      )}
      {item.status === "in_review" && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {CHANNELS.map((ch) => (
              <label key={ch} className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={channels.includes(ch)}
                  onChange={(e) =>
                    setChannels(e.target.checked ? [...channels, ch] : channels.filter((x) => x !== ch))
                  }
                />
                {ch}
              </label>
            ))}
          </div>
          <input
            type="datetime-local"
            className="rounded border p-2 text-sm"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              disabled={busy || !when || channels.length === 0}
              className="rounded bg-green-600 px-3 py-2 text-sm text-white disabled:opacity-40"
              onClick={() =>
                act(
                  () =>
                    apiFetch(`/api/items/${item.id}/approve`, {
                      method: "POST",
                      body: JSON.stringify({
                        scheduled_at: new Date(when).toISOString(),
                        channels,
                      }),
                    }),
                  "scheduled"
                )
              }
            >
              อนุมัติ + ตั้งเวลา
            </button>
            <button
              disabled={busy}
              className="rounded bg-red-600 px-3 py-2 text-sm text-white disabled:opacity-40"
              onClick={() =>
                act(
                  () =>
                    apiFetch(`/api/items/${item.id}/reject`, {
                      method: "POST",
                      body: JSON.stringify({ reason: "rejected in review" }),
                    }),
                  "rejected"
                )
              }
            >
              ปฏิเสธ
            </button>
          </div>
        </div>
      )}
      {item.status === "failed" && (
        <button
          disabled={busy}
          className="rounded bg-amber-600 px-3 py-2 text-sm text-white"
          onClick={() =>
            act(() => apiFetch(`/api/items/${item.id}/retry`, { method: "POST" }), "scheduled")
          }
        >
          ลองใหม่
        </button>
      )}
      {item.status === "idea" && (
        <button
          disabled={busy}
          className="rounded bg-amber-600 px-3 py-2 text-sm text-white"
          onClick={() =>
            act(
              () => apiFetch(`/api/items/${item.id}/captions`, { method: "POST" }),
              "in_review"
            )
          }
        >
          สร้างแคปชันใหม่
        </button>
      )}
      {item.publications.length > 0 && (
        <table className="w-full text-xs">
          <tbody>
            {item.publications.map((p) => (
              <tr key={p.channel} className="border-t">
                <td className="py-1 font-medium">{p.channel}</td>
                <td>{p.status}</td>
                <td className="text-red-600">{p.last_error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
