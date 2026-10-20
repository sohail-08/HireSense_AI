# HireSense LangGraph diagrams

These editable draw.io diagrams cover the five graphs present before Feature 5.
The sixth graph, `InterviewAnalysisGraph`, and its ten actual nodes/eleven edges are
documented in [interview analysis](../interview-analysis.md). The seventh graph,
`ConsolidatedAssessmentGraph`, has seven nodes/eight edges documented in
[consolidated assessments](../consolidated-assessments.md). These two graphs are not
included in these older draw.io bundles. Node identifiers and directed edges below were checked against
`workflow._compiled.get_graph()`; START and END display LangGraph's
`__start__` and `__end__` sentinels.

Open **hiresense-all-langgraphs.drawio** in diagrams.net for all five graphs as
separate pages, or open one of the individual files.

| File | Graph | Source | Registered nodes | Edges |
| --- | --- | --- | --- | --- |
| 01-supervisor.drawio | HireSenseSupervisorGraph | `backend/app/agents/supervisor.py` | 4 | 7 |
| 02-requirement-discovery.drawio | RequirementDiscoveryGraph | `backend/app/agents/requirement_discovery.py` | 6 | 8 |
| 03-job-posting.drawio | JobPostingAssistantGraph | `backend/app/agents/job_posting.py` | 2 | 3 |
| 04-cv-screening.drawio | ScreeningWorkflow | `backend/app/screening/workflow.py` | 5 | 6 |
| 05-candidate-scoring.drawio | CandidateScoringWorkflow | `backend/app/scoring/workflow.py` | 5 | 6 |

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

`backend/app/agents/supervisor_tools.py` defines ten recruitment-scoped `@tool`
functions: requirements, generate_job_description, edit_job_description,
approve_job_description, job_posting, sync_responses, screen_candidates, interviews,
candidate_assessments, and help.
Interview-room scope binds `suggest_interview_questions`, `interview_analysis`, and
`help` instead. These are tools executed inside the existing `tools` node, not extra
LangGraph nodes.

## Specialist graph scope

- Requirement discovery branches from `validate_profile` to `respond`
  or `handle_error`, according to whether `state.error` is set.
- The job-posting graph contains only `interpret_message` and
  `validate_details`. Preview generation, approval handling, and Discord MCP
  publishing occur in service code outside this graph.
- The screening graph processes one application's CV per invocation. Batch
  execution, failure handling, and ranking snapshots occur in service code
  outside this graph.

Service operations and calls between graphs are not added as graph edges.
`../hiresense-langgraph-workflow.drawio` contains the same complete five-page set.

Candidate scoring consumes saved evidence after screening. Its actual nodes are
`category_scoring`, `weighted_scoring`, `written_justification`, `rank_candidates`,
and `persist_scores`. It does not invoke an LLM. An approved configuration is
required for the service to invoke it automatically after a screening batch.
