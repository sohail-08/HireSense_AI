export const APPLICATIONS_CHANGED_EVENT = "hiresense:applications-changed";

export function notifyApplicationsChanged() {
  window.dispatchEvent(new Event(APPLICATIONS_CHANGED_EVENT));
}
