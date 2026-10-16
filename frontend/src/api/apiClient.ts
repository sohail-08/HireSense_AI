export const API_URL = (
  import.meta.env.VITE_API_URL || "/api"
).replace(/\/$/, "");

export const TOKEN_KEY = "hiresense_token";
export const EXPIRY_KEY = "hiresense_token_expiry";
export const AUTH_EXPIRED_EVENT = "hiresense:auth-expired";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  authenticated = true,
): Promise<T> {
  const headers = new Headers(options.headers);

  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const token = authenticated
    ? sessionStorage.getItem(TOKEN_KEY)
    : null;

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;

  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
    });
  } catch {
    throw new ApiError(
      "Cannot connect to the server. Please try again.",
      0,
    );
  }

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    if (response.status === 401 && token) {
      sessionStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem(EXPIRY_KEY);

      window.dispatchEvent(
        new Event(AUTH_EXPIRED_EVENT),
      );
    }

    const detail = data?.detail;

    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((item: { msg: string }) => item.msg)
              .join("; ")
          : "The request failed. Please try again.";

    throw new ApiError(message, response.status);
  }

  return data as T;
}
