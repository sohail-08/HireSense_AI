// Hidden scheduling defaults are applied to both invitations and reschedules.
export function buildInterviewSchedule(fields: Record<string, string>): Record<string, unknown> {
  return {
    ...fields,
    timezone: "Asia/Dhaka",
    mode: "sequential",
    duration_minutes: Number(fields.duration_minutes),
    buffer_minutes: Number(fields.buffer_minutes),
  };
}
