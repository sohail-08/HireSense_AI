# Private interviewer assistance

The interview console includes candidate information and the HireSense interview assistant. Video/device controls remain on the left; the private assistance sections are on the right on wide screens and stack below on smaller screens. Later increments add [live transcription](live-transcription.md) and [versioned answer analysis](interview-analysis.md) below the media controls. Analysis and follow-up suggestions are interviewer-only.

## Candidate information

The authenticated, assigned interviewer sees the application's candidate name, email, phone, location when available, and saved CV-screening highlights (skills, education, experience and recent roles). Missing information is labeled unavailable, not invented. CV claims are not independently verified. The selected posting's JD and requirements supply the interview context. No candidate data is added to the public candidate room response.

## Question knowledge and RAG

`backend/app/data/interview_questions.json` contains 24 explicitly synthetic question-bank entries covering frontend/backend engineering, QA, DevOps, full-stack, data/AI, HR, design and project management. They are examples for demonstration, not actual company interview records.

After migrating, index the question bank with the existing embedding model:

```powershell
docker compose exec backend python -m app.seed_interview_questions
```

The command is idempotent for the bundled dataset. Ollama must be reachable and its configured `nomic-embed-text` model available. The questions and 768-dimensional embeddings are saved in the existing knowledge tables/pgvector index with source type `interview_question`. JD discovery/generation and the previous-JD document list exclude these entries. Interview questions can be listed using `GET /api/knowledge/documents?source_type=interview_question`; authorized knowledge-document APIs accept this source type for curated additions. The existing PDF upload remains for previous JDs.

For each message, the backend authorizes interview ownership and calls the central `SupervisorService.chat_interview` entry point. It uses the same `HireSenseSupervisorGraph`, `bind_tools()` and native `ToolNode` as recruitment chat, with a server-enforced interview-only tool set. The supervisor LLM chooses between `suggest_interview_questions`, `interview_analysis`, and `help`. These are native `@tool` definitions; recruitment mutation tools are not registered or bound in this scope. The analysis tool reads saved assessments, requirement coverage and transcript citations, or queues a background update when unavailable/stale. Unsupported requests are explained, not redirected into another workflow or executed. Even a fabricated mutation tool call is rejected before execution.

The question tool delegates to the read-only RAG sub-agent: embed the job title/skills plus the request, retrieve up to six question-bank chunks with cosine similarity of at least 0.25, and ask the configured Gemini model for relevant questions. The full JD (bounded to 16,000 characters) and recent interview chat are included. Candidate contacts and media credentials are not included automatically in either the supervisor or sub-agent. Every suggested question must cite retrieved chunk IDs. Users can expand the cited excerpts. If there is no relevant evidence, the assistant says so rather than silently using generic, uncited questions. Citation validation checks source identity, not the correctness of every generated statement; interviewer review is still needed. The supervisor returns the validated tool answer without an additional prose-generation call, preserving question/source parity. A normal suggestion uses one routing call and one question-generation call; help uses only the routing call.

## Privacy, persistence and boundaries

`GET/POST /api/interview-rooms/{interview_id}/copilot` require an active interviewer JWT and ownership of that schedule. Candidate cookies, candidate JWTs and other interviewers cannot use them. Responses have `Cache-Control: no-store`. The candidate frontend and LiveKit room receive neither section nor messages; deliberate screen sharing is outside these UI/API protections.

This is one central assistant with scoped capabilities, not one globally merged conversation. Interview chat remains saved on `interview_schedules.copilot_messages`, survives reloads, and is removed when that schedule is deleted. Recruiter `SupervisorSession` records are neither created nor changed from the interview room. An independent conversation version rejects stale/concurrent sends without overwriting history. There are at most 50 user turns per interview and 10 requests per minute per interviewer (single-process limiter). Assistant messages record the executed `tool_name`. The assistant can queue owned interview analysis and save chat history; it has no posting, email, ranking, scheduling or media-control capabilities. Analysis-derived messages follow transcript retention/deletion. The existing recruitment mode retains its normal tools, approval flow and final response handling. Scope is a server-side graph argument, never a client/model-supplied permission.

## Try it

1. Open an interview console while signed in as its assigned interviewer.
2. Check candidate information. Screen the CV first if highlights are missing.
3. Click **Suggest questions**, or ask “Suggest three practical questions about the required React skills.”
4. Ask “Make the second question more challenging” and expand **Knowledge sources**.
5. Reload to confirm the saved conversation remains. Open the candidate invitation in another browser: neither private section should appear.

No new API keys or environment files are needed. Existing Gemini and Ollama settings are reused. Schema migration: `0019_interview_copilot`. Normal startup applies it. Never restart the backend during an active interview or pending email delivery to activate this feature.
