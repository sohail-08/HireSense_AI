import { API_URL, ApiError, apiRequest } from "../../api/apiClient";
export type IdentityState = { enabled: boolean; reference_available: boolean; reference_ready: boolean; status: string; message: string;
  version: number; consented: boolean; checked_at: string | null; notice_version: string; notice: string; reference_expires_at: string | null;
  similarity?: number | null; threshold?: number | null; manual_note?: string | null };
export type CandidateIdentityState = Omit<IdentityState, "checked_at" | "similarity" | "threshold" | "manual_note"> & { capture_available: boolean };
async function candidate(path = "", body?: object): Promise<CandidateIdentityState> {
  const response = await fetch(`${API_URL}/interview-rooms/candidate/identity${path}`, { credentials: "include", cache: "no-store",
    method: body ? "POST" : "GET", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(typeof value?.detail === "string" ? value.detail : "Photo matching is unavailable. You can continue with manual verification.", response.status);
  return value;
}
export const identityApi = {
  candidate: () => candidate(),
  consent: (allow: boolean, notice_version: string) => candidate("/consent", { allow, notice_version }),
  verify: (frames: string[], version: number) => candidate("/verify", { frames, version }),
  withdraw: () => candidate("/withdraw", { confirmed: true }),
  read: (id: number) => apiRequest<IdentityState>(`/interview-rooms/${id}/identity`, { cache: "no-store" }),
  manual: (id: number, note: string) => apiRequest<IdentityState>(`/interview-rooms/${id}/identity/manual`, { method: "POST", body: JSON.stringify({ confirmed: true, note }) }),
};
