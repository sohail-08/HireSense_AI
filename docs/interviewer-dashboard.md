# Interviewer dashboard

The recruitment overview replaces navigation-only placeholder cards with saved
workflow information. It uses the existing owner-authorized GET endpoints for
job descriptions, screening jobs, and interview schedules. Opening or refreshing
the dashboard never syncs applications, screens CVs, generates assessments, sends
invitations, joins a room, or adds chatbot messages.

- Totals: published posts (not distinct roles), applications (not unique people),
  applications missing a compatible current screening result, and upcoming/open interviews.
- Snapshot: approved descriptions and completed interviews. Draft/approved counts
  represent saved versions, matching the Jobs page, not distinct position titles.
- Next interviews: open rooms first, then chronological upcoming or ongoing time slots.
  Ended, cancelled and ending rooms are excluded. Passed slots that remain open
  in the scheduling workflow are flagged for review rather than called completed.
- Needs attention: pending screening, saved job drafts, past uncompleted interview slots.
- Role activity: up to four job posts, prioritizing pending screening; screened counts
  are applications minus pending compatibility checks, not hiring recommendations.
- Dates and “today” use Asia/Dhaka, regardless of the browser's timezone.

The layout uses the shared dark-blue palette with teal, amber and violet accents,
responsive cards and wrapping rows. Each section has loading, empty and unavailable
states. Partial failures retain successful sections without showing false zeroes.
Refresh overview retries all three GETs; assistant refresh events also reload them.
A minute timer only updates date-sensitive presentation, not server calls. Links
navigate to existing workspaces without performing business mutations.

Synthetic dashboard tests cover counts, Dhaka midnight, room states, read-only
behavior, errors, recovery, empty states and screening progress. Browser visual
verification is not part of these tests.
