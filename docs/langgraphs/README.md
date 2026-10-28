# HireSense LangGraph inventory and diagrams

The application has **seven distinct graph definitions**:

| Editable diagram | Graph | Source | Registered nodes | Edges |
| --- | --- | --- | --- | --- |
| [01-supervisor.drawio](01-supervisor.drawio) | HireSenseSupervisorGraph | `backend/app/agents/supervisor.py` | 4 | 7 |
| [02-job-posting.drawio](02-job-posting.drawio) | JobPostingAssistantGraph | `backend/app/agents/job_posting.py` | 2 | 3 |
| [03-cv-screening.drawio](03-cv-screening.drawio) | ScreeningWorkflow | `backend/app/screening/workflow.py` | 5 | 6 |
| [04-candidate-scoring.drawio](04-candidate-scoring.drawio) | CandidateScoringWorkflow | `backend/app/scoring/workflow.py` | 5 | 6 |
| [05-interview-analysis.drawio](05-interview-analysis.drawio) | InterviewAnalysisGraph | `backend/app/agents/interview_analysis.py` | 10 | 11 |
| [06-consolidated-assessment.drawio](06-consolidated-assessment.drawio) | ConsolidatedAssessmentGraph | `backend/app/assessments/workflow.py` | 7 | 8 |
| [07-work-sample-generation.drawio](07-work-sample-generation.drawio) | WorkSampleGraph | `backend/app/agents/work_sample.py` | 2 | 3 |

The central and interview-room assistants reuse the same supervisor definition
with different tool scopes; they are not two separate graphs. See also
[interview analysis](../interview-analysis.md) and
[consolidated assessments](../consolidated-assessments.md).

The standalone `RequirementDiscoveryGraph` and its `/api/requirements/chat`
endpoint have been retired. Job descriptions still use RAG through
`DirectJobDescriptionService`, including source validation and follow-up questions
when information is insufficient. It saves a structured `RequirementProfile`
alongside the JD for existing screening, scoring and assessment workflows. The
shared schemas, profiles, historical discovery-session table and supervisor FKs
remain; no database migration or record deletion is required. Legacy supervisor
phases still resume through direct drafting. Removed source is recoverable in Git.

## Open the diagrams

Open [hiresense-all-langgraphs.drawio](hiresense-all-langgraphs.drawio) in
diagrams.net/draw.io for all seven graphs as separate pages. The existing root
bundle [hiresense-langgraph-workflow.drawio](../hiresense-langgraph-workflow.drawio)
contains the identical seven pages. Each individual file above contains one graph.
All nodes, labels and connectors are editable XML, not embedded screenshots.

These files replace the previous five-page bundles and old numbered files. The
retired requirement-discovery page is no longer included; earlier versions are
recoverable through Git. No application code, data or deployment settings change.

Node counts exclude START and END. Solid arrows are unconditional edges.
Dashed arrows are conditional edges. Conditional edge labels use the exact
routing keys from `add_conditional_edges()` (`tools`, `handle_error`, `end`).
Node labels are the actual registered identifiers, not conceptual business steps.
Page headings and count captions are annotations, not additional graph nodes.
No service-to-service connections, implied decision nodes, approval nodes or
extra RAG nodes have been added. The supervisor's real result-to-agent loop is
preserved, and the other six graphs are their actual sequential chains.

## Validate against code

From `backend`, run:

```powershell
.\.venv\Scripts\python.exe scripts/check_langgraph_diagrams.py
```

The read-only checker compiles all seven graphs with offline stubs and compares
their node IDs, source/target edges, conditional flags and routing labels against
every draw.io page. It checks unique IDs, page bounds, non-overlapping vertices,
the absence of obsolete files and identical combined bundles. It never invokes
a graph, calls a provider/tool, connects to a database or changes saved data.
Use `--json` to inspect the compiled node/edge inventory.

## Native supervisor

The supervisor contains exactly these registered nodes:

- `supervisor_agent`: Gemini receives the tools through `bind_tools()`.
- `tools`: LangGraph's native `ToolNode`, shown in purple with its implementation
  type beneath the actual node name.
- `capture_tool_result`: captures the structured result from a `ToolMessage`.
- `handle_error`: reports routing or execution failure and preserves any
  operation that already completed.

The agent chooses a single tool, the ToolNode executes it, and the result returns
to the agent for its final answer. Further tool calls are disabled for that final
answer. Invalid, missing, or multiple initial tool calls cannot execute operations.
If final answer generation fails, completed tool results and refresh/background
signals are retained.

`backend/app/agents/supervisor_tools.py` defines nine recruitment-scoped `@tool`
functions: generate_job_description, edit_job_description,
approve_job_description, job_posting, sync_responses, screen_candidates, interviews,
candidate_assessments, and help.
Interview-room scope binds `suggest_interview_questions`, `interview_analysis`,
`suggest_practical_tasks` and `help` when available. These are tools executed inside the existing `tools` node, not extra
LangGraph nodes.

## Specialist graph scope

- The job-posting graph contains only `interpret_message` and
  `validate_details`. Preview generation, approval handling, and Discord MCP
  publishing occur in service code outside this graph.
- The screening graph processes one application's CV per invocation. Batch
  execution, failure handling, and ranking snapshots occur in service code
  outside this graph.

Service operations and calls between graphs are not added as graph edges.

Candidate scoring consumes saved evidence after screening. Its actual nodes are
`category_scoring`, `weighted_scoring`, `written_justification`, `rank_candidates`,
and `persist_scores`. It does not invoke an LLM. An approved configuration is
required for the service to invoke it automatically after a screening batch.
