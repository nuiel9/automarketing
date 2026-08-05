"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";

export default function NewItem() {
  const [topic, setTopic] = useState("");
  const [hook, setHook] = useState("");
  const [link, setLink] = useState("https://eduverse.one");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  const submit = async () => {
    setBusy(true); setError("");
    const form = new FormData();
    form.set("topic", topic);
    if (hook) form.set("hook", hook);
    if (link) form.set("link", link);
    if (file) form.set("file", file);
    try {
      await apiFetch("/api/items", { method: "POST", body: form });
      router.push("/");
    } catch (e) {
      setError(String(e));
    }
    setBusy(false);
  };

  return (
    <main className="mx-auto max-w-md space-y-3 p-4">
      <h1 className="text-xl font-bold">คอนเทนต์ใหม่</h1>
      <input className="w-full rounded border p-2" placeholder="หัวข้อ"
        value={topic} onChange={(e) => setTopic(e.target.value)} />
      <input className="w-full rounded border p-2" placeholder="Hook (ไม่บังคับ)"
        value={hook} onChange={(e) => setHook(e.target.value)} />
      <input className="w-full rounded border p-2" placeholder="ลิงก์"
        value={link} onChange={(e) => setLink(e.target.value)} />
      <input type="file" accept="video/mp4" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <button
        disabled={busy || !topic}
        className="w-full rounded bg-black p-2 text-white disabled:opacity-40"
        onClick={submit}
      >
        {busy ? "กำลังเขียนแคปชัน..." : "สร้าง + เขียนแคปชัน"}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </main>
  );
}
