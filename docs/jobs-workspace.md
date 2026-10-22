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
