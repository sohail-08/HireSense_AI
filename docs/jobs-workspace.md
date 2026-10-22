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
4. Choose **Create manually** or **Create with assistant**. Manual creation opens
   a form for the job title, description and explicit screening requirements. It
   saves a draft without AI, embeddings or reference retrieval. Required skills
   are entered one per line; qualifications, preferred skills and experience are
   optional. The requirements and job are saved together, owned by the interviewer.
   Approval is a separate, explicit step using the existing approval endpoint.
5. **Create with assistant** opens the assistant and starts a fresh conversation.
   An existing conversation is reset only after confirmation. Saved jobs are not
   deleted. No model request is made until the user sends a message or explicitly
   requests confirmation, generation or approval.
6. Assistant requirements and the draft appear in the current workspace only when needed.
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
- `JobRequirementsPanel.tsx`: concise requirements and explicit confirmation.
- `JobKnowledgeModal.tsx`: reference uploads and deletion.
- `PreviewModal.tsx`: optional wide layout; default modals are unchanged.
- `SupervisorProvider.tsx`: exposes its existing new-workflow reset to the page.
- `backend/app/routes/job_descriptions.py`: authenticated `POST /api/job-descriptions/manual`.
- `backend/app/services/job_description_service.py`: atomic manual profile/draft creation.
- `backend/app/schemas/job.py`: bounded manual input; clients cannot set ownership,
  approval status, source references or arbitrary metadata. Existing tables suffice;
  no migration is needed.

Frontend tests use synthetic data and mocked APIs, including cancellation,
focus restoration, duplicate-click protection and failed-save recovery. No real
email, publication or AI generation is used for verification. Run
`npm run test:rooms` and `npm run build` from `frontend`. Backend tests cover
manual creation, screening compatibility, validation, ownership, role checks,
approval and transaction rollback in synthetic SQLite databases.
