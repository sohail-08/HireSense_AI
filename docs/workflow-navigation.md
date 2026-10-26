# Workflow navigation

Explicit assistant actions reveal the workspace where their result is shown:

- Draft/edit a job: job-description review, including a draft rendered below saved jobs.
- Approve/post a job: publication controls for the approved description.
- Sync responses: the collected-candidate list.
- Screen candidates: CV Screening with the batch's job selected.
- Schedule interviews: candidate selection; sent/rescheduled invitations: Interviews.
- Rank, generate or compare assessments: final ranking or the saved report/comparison modal.

The frontend maps structured tool names/results to known internal routes and section
IDs. It does not interpret assistant prose as a URL. Assessment links are limited to
the local reports route and positive numeric identifiers. No new API or AI request
is made solely to decide navigation. Multiple report links stay a choice in chat;
the page opens the ranking overview rather than arbitrarily selecting one report.

Manual actions also reveal CV ranking progress/results, final ranking, answer-analysis
results, publication controls after JD approval, scheduling time settings after a
selection preview, and delivery progress after confirmation. Interview-assistant
task creation opens the practical tab; analysis requests open Answer analysis.
Switching from Practical exercise to its assistant reveals the composer. Existing
confirmation modals, approval requirements and scoring behavior are unchanged.

`useSectionReveal` waits for delayed React content, loading layout and hidden tabs, scrolls once,
and briefly outlines the destination. Sticky-header spacing and reduced-motion
preferences are respected. It can scroll inside an existing modal but never behind
one. It preserves keyboard input focus. A pending reveal is cancelled on user
scroll/touch/keyboard/pointer interaction or component cleanup, and expires after
eight seconds. On small screens an explicit assistant destination closes the
covering assistant panel so the result can actually be seen.

Restoring a chat, polling progress and ordinary refreshes do not trigger navigation.
An assistant response arriving after the user changes routes is shown in chat but
does not pull the user back. Repeated explicit commands can reveal the same section
again; background updates cannot repeatedly move the page.

Tests use synthetic mocked responses in JSDOM; they make no provider, media or email
requests. Regression coverage includes delayed targets, hidden tabs, modals, reduced
motion, preserved focus, user cancellation, safe destinations, restored chats and
late responses after navigation.
