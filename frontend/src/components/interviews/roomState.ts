import { formatDateTime } from "../../utils/dateTime";

export function accessMessage(code: string): { title: string; message: string } {
  switch (code) {
    case "expired_link": return { title: "This invitation has expired", message: "Contact the interviewer for an updated invitation." };
    case "revoked_link": return { title: "This invitation is no longer valid", message: "Use the latest invitation from your interviewer." };
    case "cancelled": return { title: "Interview cancelled", message: "Contact the interviewer if you need help." };
    case "ending": return { title: "The interview is closing", message: "Room access is closed. Please wait for the interviewer." };
    case "ended": return { title: "Interview ended", message: "Thank you for attending. You can close this page." };
    case "rate_limited": return { title: "Please wait a moment", message: "Too many link attempts. Please try again in a minute." };
    case "invalid_session": return { title: "Your interview session has expired", message: "Reopen the latest interview link in your invitation email." };
    case "network_error": return { title: "Connection unavailable", message: "Check your internet connection and try again." };
    default: return { title: "Interview link unavailable", message: "This link may be invalid or replaced. Open the latest invitation or contact the interviewer." };
  }
}

export function deviceMessage(error: Error): string {
  if (/NotAllowed|Permission|Security/i.test(error.name)) return "Camera or microphone permission was denied. Allow access in your browser settings, or join with those devices off.";
  if (/NotFound|DevicesNotFound/i.test(error.name)) return "No camera or microphone was found. Connect a device, choose another input, or join with it off.";
  if (/NotReadable|TrackStart|Overconstrained/i.test(error.name)) return "Your selected device is unavailable or in use. Close other video apps or choose another device.";
  return "The media connection or device could not start. Check browser permissions and connectivity, then try again.";
}

export function formatRoomTime(value: string, timezone: string): string {
  return formatDateTime(value, timezone);
}
