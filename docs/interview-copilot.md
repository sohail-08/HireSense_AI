# Private interviewer assistance

The interview console includes only two new sections: candidate information and the HireSense interview assistant. Video/device controls remain on the left; the private sections are on the right on wide screens and stack below on smaller screens. There is no transcript, notes, evaluation, recording, or live analysis in this increment.

## Candidate information

The authenticated, assigned interviewer sees the application's candidate name, email, phone, location when available, and saved CV-screening highlights (skills, education, experience and recent roles). Missing information is labeled unavailable, not invented. CV claims are not independently verified. The selected posting's JD and requirements supply the interview context. No candidate data is added to the public candidate room response.

## Question knowledge and RAG

`backend/app/data/interview_questions.json` contains 24 explicitly synthetic question-bank entries covering frontend/backend engineering, QA, DevOps, full-stack, data/AI, HR, design and project management. They are examples for demonstration, not actual company interview records.

After migrating, index the question bank with the existing embedding model:

```powershell
docker compose exec backend python -m app.seed_interview_questions
```

The command is idempotent for the bundled dataset. Ollama must be reachable and its configured `nomic-embed-text` model available. The questions and 768-dimensional embeddings are saved in the existing knowledge tables/pgvector index with source type `interview_question`. JD discovery/generation and the previous-JD document list exclude these entries. Interview questions can be listed using `GET /api/knowledge/documents?source_type=interview_question`; authorized knowledge-document APIs accept this source type for curated additions. The existing PDF upload remains for previous JDs.

For each message, the backend authorizes interview ownership, loads its job context, embeds the job title/skills plus the request, retrieves up to six question-bank chunks with cosine similarity of at least 0.25, and asks the configured Gemini model for relevant questions. The full JD (bounded to 16,000 characters) and recent interview chat are included. Candidate contacts and media credentials are not included automatically. Every suggested question must cite retrieved chunk IDs. Users can expand the cited excerpts. If there is no relevant evidence, the assistant says so rather than silently using generic, uncited questions. Citation validation checks source identity, not the correctness of every generated statement; interviewer review is still needed.

## Privacy, persistence and boundaries

`GET/POST /api/interview-rooms/{interview_id}/copilot` require an active interviewer JWT and ownership of that schedule. Candidate cookies, candidate JWTs and other interviewers cannot use them. Responses have `Cache-Control: no-store`. The candidate frontend and LiveKit room receive neither section nor messages; deliberate screen sharing is outside these UI/API protections.

Chat is scoped to the interview rather than the recruiter workflow. It is saved on `interview_schedules.copilot_messages`, survives reloads, and is removed when that schedule is deleted. An independent conversation version rejects stale/concurrent sends without overwriting history. There are at most 50 user turns per interview and 10 requests per minute per interviewer (single-process limiter). The assistant is read-only apart from its chat history: it has no posting, email, ranking, scheduling or media-control capabilities. The existing recruiter supervisor and its tools remain unchanged.

## Try it

1. Open an interview console while signed in as its assigned interviewer.
2. Check candidate information. Screen the CV first if highlights are missing.
3. Click **Suggest questions**, or ask “Suggest three practical questions about the required React skills.”
4. Ask “Make the second question more challenging” and expand **Knowledge sources**.
5. Reload to confirm the saved conversation remains. Open the candidate invitation in another browser: neither private section should appear.

No new API keys or environment files are needed. Existing Gemini and Ollama settings are reused. Schema migration: `0019_interview_copilot`. Normal startup applies it. Never restart the backend during an active interview or pending email delivery to activate this feature.
