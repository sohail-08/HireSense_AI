import { beforeEach, expect, it, vi } from "vitest";
import { apiBlob, apiRequest, AUTH_EXPIRED_EVENT, EXPIRY_KEY, TOKEN_KEY } from "../../src/api/apiClient";

beforeEach(() => { sessionStorage.clear(); });

it("uses the session authorization header for private blobs and prevents fetch caching", async () => {
  sessionStorage.setItem(TOKEN_KEY, "synthetic-private-token");
  const fetcher = vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "application/pdf" } }));
  vi.stubGlobal("fetch", fetcher);
  const blob = await apiBlob("/candidates/applications/1/cvs/2");
  expect(blob.type).toBe("application/pdf"); expect(blob.size).toBe(3);
  expect(fetcher.mock.calls[0][0]).toBe("/api/candidates/applications/1/cvs/2");
  expect(fetcher.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer synthetic-private-token");
  expect(fetcher.mock.calls[0][1].cache).toBe("no-store");
});

it("expires authentication on a denied file request just like JSON requests", async () => {
  sessionStorage.setItem(TOKEN_KEY, "synthetic"); sessionStorage.setItem(EXPIRY_KEY, "synthetic-expiry");
  const expired = vi.fn(); window.addEventListener(AUTH_EXPIRED_EVENT, expired);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Please sign in again" }), { status: 401 })));
  try {
    await expect(apiBlob("/private-file")).rejects.toThrow("Please sign in again");
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull(); expect(sessionStorage.getItem(EXPIRY_KEY)).toBeNull();
    expect(expired).toHaveBeenCalledOnce();
  } finally { window.removeEventListener(AUTH_EXPIRED_EVENT, expired); }
});

it("preserves JSON and empty-response handling after adding blob support", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }))).mockResolvedValueOnce(new Response(null, { status: 204 })));
  expect(await apiRequest("/json")).toEqual({ ok: true });
  expect(await apiRequest("/delete", { method: "DELETE" })).toBeNull();
});
