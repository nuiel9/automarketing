import { describe, expect, it, vi } from "vitest";
import { apiFetch } from "./api";

describe("apiFetch", () => {
  it("sends bearer token and parses json", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("localStorage", {
      getItem: () => "tok123",
    } as unknown as Storage);

    const data = await apiFetch("/api/items");
    expect(data).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/items");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok123");
  });

  it("throws on non-2xx with body text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 422 })));
    vi.stubGlobal("localStorage", { getItem: () => "t" } as unknown as Storage);
    await expect(apiFetch("/api/items")).rejects.toThrow("nope");
  });
});
