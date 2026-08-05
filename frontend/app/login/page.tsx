"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Login() {
  const [token, setToken] = useState("");
  const router = useRouter();
  return (
    <main className="mx-auto mt-24 max-w-sm space-y-4 p-4">
      <h1 className="text-xl font-bold">AutoMarketing</h1>
      <input
        className="w-full rounded border p-2"
        type="password"
        placeholder="Admin token"
        value={token}
        onChange={(e) => setToken(e.target.value)}
      />
      <button
        className="w-full rounded bg-black p-2 text-white"
        onClick={() => {
          localStorage.setItem("am_token", token);
          router.push("/");
        }}
      >
        เข้าสู่ระบบ
      </button>
    </main>
  );
}
