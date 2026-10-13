import { apiRequest, API_URL } from "../../api/apiClient";

export type RoomStatus = "scheduled" | "waiting" | "ready" | "active" | "ending" | "ended" | "cancelled";
export type CandidateRoomInfo = {
  job_title: string; scheduled_start: string; scheduled_end: string; timezone: string;
  room_status: RoomStatus; waiting: boolean; admitted: boolean; join_opens_at: string; join_closes_at: string;
};
export type InterviewerRoomInfo = CandidateRoomInfo & {
  interview_id: number; candidate_name: string; room_version: number; has_join_link: boolean; link_revoked: boolean;
  candidate_joined_at: string | null; interviewer_joined_at: string | null;
  interview_started_at: string | null; interview_ended_at: string | null;
};
export type MediaAccess = { server_url: string; participant_token: string; expires_at: string; role: "candidate" | "interviewer" };
export type DeviceChoices = { username: string; audioEnabled: boolean; videoEnabled: boolean; audioDeviceId: string; videoDeviceId: string };

export class RoomApiError extends Error {
  constructor(public code: string, public status: number, public retryAt?: string) {
    super("Interview access is unavailable.");
  }
}

export async function candidateRequest<T>(path: string, data?: object): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/interview-rooms/candidate/${path}`, {
      method: data === undefined ? "GET" : "POST", credentials: "include", cache: "no-store",
      headers: data === undefined ? undefined : { "Content-Type": "application/json" },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  } catch { throw new RoomApiError("network_error", 0); }
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new RoomApiError(value?.code || "request_failed", response.status, value?.retry_at);
  return value as T;
}

export const roomApi = {
  exchange: (token: string) => candidateRequest<CandidateRoomInfo>("exchange", { token }),
  candidateStatus: () => candidateRequest<CandidateRoomInfo>("status"),
  waiting: () => candidateRequest<CandidateRoomInfo>("waiting", {}),
  candidateMedia: () => candidateRequest<MediaAccess>("media-token", {}),
  candidateConnected: () => candidateRequest<CandidateRoomInfo>("connected", {}),
  candidateLeave: () => candidateRequest<CandidateRoomInfo>("leave", {}),
  status: (id: number) => apiRequest<InterviewerRoomInfo>(`/interview-rooms/${id}`),
  admit: (id: number) => apiRequest<InterviewerRoomInfo>(`/interview-rooms/${id}/admit`, { method: "POST", body: JSON.stringify({ confirmed: true }) }),
  end: (id: number) => apiRequest<InterviewerRoomInfo>(`/interview-rooms/${id}/end`, { method: "POST", body: JSON.stringify({ confirmed: true }) }),
  interviewerMedia: (id: number) => apiRequest<MediaAccess>(`/interview-rooms/${id}/media-token`, { method: "POST", body: "{}" }),
  interviewerConnected: (id: number) => apiRequest<InterviewerRoomInfo>(`/interview-rooms/${id}/connected`, { method: "POST", body: "{}" }),
  interviewerLeave: (id: number) => apiRequest<InterviewerRoomInfo>(`/interview-rooms/${id}/leave`, { method: "POST", body: "{}" }),
  link: (id: number, operation = "") => apiRequest<{ join_url: string; expires_at: string }>(`/interview-rooms/${id}/candidate-link${operation}`, { method: "POST", body: JSON.stringify({ confirmed: true }) }),
  revoke: (id: number) => apiRequest<InterviewerRoomInfo>(`/interview-rooms/${id}/candidate-link/revoke`, { method: "POST", body: JSON.stringify({ confirmed: true }) }),
};
