# Jobs workspace

The Jobs page starts with the saved job list rather than empty requirements and
draft panels. It keeps the existing indigo theme and central assistant workflow.

## Interviewer flow

1. Browse full job titles in responsive cards. Search by title, filter by status, and
   use pagination. Dates and times are displayed in Dhaka time.
2. Open **View job** or **Edit draft** for details in a modal. Approved and
   archived descriptions are read-only. Closing restores focus to the card
   action without resetting search or pagination.
3. Edit a draft and **Save changes** before approving it. Unsaved edits are
   identified, failed saves keep the typed text, and closing asks before
   discarding edits. **New draft** preserves the approved version.
4. Choose **Create job description manually**, or use the existing assistant panel. Manual creation opens
   a form for the job title, description and explicit screening requirements. It
   saves a draft without AI, embeddings or reference retrieval. Required skills
   are entered one per line; qualifications, preferred skills and experience are
   optional. The requirements and job are saved together, owned by the interviewer.
   Approval is a separate, explicit step using the existing approval endpoint.
5. Open **Assistant** to describe a role; there is no separate assistant-creation
   button in the Jobs header. Use **New workflow** inside the panel for a fresh
   conversation. No model request is made until the user sends a message.
6. Say “I want to hire a backend engineer.” The assistant searches past job descriptions,
   checks which sources actually fit the role, and drafts the JD directly. There is no
   requirements proposal, requirements approval or separate generation button. If no
   suitable reference is found, it asks for skills and duties and drafts from the reply.
   Unknown qualifications, experience or selection steps are not invented or compulsory.
   The draft appears as a formatted preview: a single title, clear section headings,
   bullet lists and comfortable spacing. **Edit** opens manual title/body fields.
   **Save changes** returns to the updated preview; **Cancel** confirms discarding
   unsaved edits and restores the saved text. Failed saves preserve typed edits.
   Explicit JD approval is still required. Approved descriptions create a separate
   draft version for editing, rather than changing the approved record.
   Restoring a conversation does not automatically scroll away from saved jobs.
7. **Reference documents** opens a separate modal for past job-description PDFs.
   Upload and removal retain the existing authenticated APIs and backend file
   restrictions. Plain wording replaces the RAG/indexing terminology.
8. Approved job details still include the existing Discord preview/publish controls.
   Opening a job never creates or publishes a post. Removing a saved description
   requires confirmation and does not remove published Discord messages.

## Implementation and checks

- `JobDescriptionPage.tsx`: selection, current workflow, saved edits and actions.
- `SavedJobsCards.tsx`: search, status filter, pagination and card actions.
- `ManualJobModal.tsx`: independent manual creation with unsaved-input protection.
- `JobDescriptionEditor.tsx`: draft editing and readable saved descriptions.
- `JobDescriptionPreview.tsx`: safe text-based Markdown subset rendering; no raw
  HTML or executable links. Saved content is used instead of stale structured data.
- `DiscordPostPreview.tsx`: dark-blue role header, formatted JD body and separate
  application-detail cards with readable deadlines and HTTP(S)-only links. This
  preview does not publish on load. Heading, contact email and address are fixed
  company details, not editable fields. The editor only collects the application
  link, deadline and optional instructions. The backend owns the fixed values in
  `backend/app/job_posting_branding.py`; clients cannot override them.
  The contact email is `sohail.sh.ahmed@gmail.com` and the address is
  `House-5/B, Road-2/E, Block-J, Baridhara, Dhaka 1212`.
- The defaults endpoint accepts an optional, owner-checked `job_description_id`
  and returns the same posting-specific body used by the publisher. The known
  reference-employer alias “Northstar Digital” becomes “BJIT” in this body;
  existing approved JDs, knowledge documents and published posts are not rewritten.
  New JD prompts explicitly identify BJIT as the hiring employer. Legacy saved
  previews with old company details must be refreshed before publication. In the
  UI, **Publish to Discord** asks for one confirmation, saves the current details
  (including any updated company defaults), then publishes the returned preview
  ID. There is no separate save button. A failed save never reaches publication;
  changed JD/company content requires reloading and reviewing it again. Inputs
  and repeated submissions are locked while saving/publishing. Uncertain delivery
  is never automatically retried. Existing backend confirmation and snapshot
  safeguards also remain in force for chatbot posting.
- Confirmed publication shows an accessible green success notification and closes
  the editor and preview. Failed or unconfirmed publication keeps them open;
  recovering a confirmed published status also shows success without retrying.
  Publication history is not displayed; records and delivery safeguards are
  retained internally. Job
  selectors, candidate details, notifications and ranking omit visible posting
  numbers while retaining IDs for API requests and selection.
- `JobKnowledgeModal.tsx`: reference uploads and deletion.
- `PreviewModal.tsx`: optional wide layout; default modals are unchanged.
- `SupervisorProvider.tsx`: exposes its existing new-workflow reset to the page.
- `backend/app/routes/job_descriptions.py`: authenticated `POST /api/job-descriptions/manual`.
- `backend/app/services/job_description_service.py`: atomic manual profile/draft creation.
- `backend/app/agents/direct_job_description.py`: source relevance and grounded JD writing.
- `backend/app/services/direct_job_description_service.py`: knowledge-first drafting and
  automatic internal screening-profile creation from the same draft. Both records and
  the supervisor session commit together. Historical requirements and sessions remain
  readable, but the supervisor no longer exposes the requirements-discovery tool.
  A knowledge-service outage reports a retryable error, not a missing role.
- `backend/app/schemas/job.py`: bounded manual input; clients cannot set ownership,
  approval status, source references or arbitrary metadata. Existing tables suffice;
  no migration is needed.

Frontend tests use synthetic data and mocked APIs, including cancellation,
focus restoration, duplicate-click protection and failed-save recovery. No real
email, publication or AI generation is used for verification. Run
`npm run test:rooms` and `npm run build` from `frontend`. Backend tests cover
manual creation, screening compatibility, validation, ownership, role checks,
approval and transaction rollback in synthetic SQLite databases. Direct-drafting tests
also cover unrelated/missing sources, invalid citations, user-detail provenance,
follow-up continuity, legacy sessions, duplicate requests and embedding/model outages.
