# HireSense LangGraph inventory and diagrams

The application has **seven distinct graph definitions**:

| Graph | Source | Registered nodes | Edges |
| --- | --- | --- | --- |
| HireSenseSupervisorGraph | `backend/app/agents/supervisor.py` | 4 | 7 |
| JobPostingAssistantGraph | `backend/app/agents/job_posting.py` | 2 | 3 |
| ScreeningWorkflow | `backend/app/screening/workflow.py` | 5 | 6 |
| CandidateScoringWorkflow | `backend/app/scoring/workflow.py` | 5 | 6 |
| InterviewAnalysisGraph | `backend/app/agents/interview_analysis.py` | 10 | 11 |
| ConsolidatedAssessmentGraph | `backend/app/assessments/workflow.py` | 7 | 8 |
| WorkSampleGraph | `backend/app/agents/work_sample.py` | 2 | 3 |

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

The draw.io files are **historical snapshots**, not a complete current inventory.
`hiresense-all-langgraphs.drawio` and `../hiresense-langgraph-workflow.drawio` retain
the original five pages; their discovery page is marked **RETIRED**. The standalone
`02-requirement-discovery.drawio` is also archival. The other four individual
diagrams cover the supervisor, job posting, screening and CV scoring. Interview
analysis, consolidated assessment and work-sample generation are not included in
those older bundles.

Node counts exclude START and END. Solid arrows are unconditional edges.
Dashed arrows are conditional edges. Conditional edge labels use the exact
routing keys from `add_conditional_edges()`. Hover over edges for routing details.

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
