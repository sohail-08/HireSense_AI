# Shared MCP client configuration

HireSense's two Python MCP clients read the single repository-root `mcp.json`. Both use Streamable HTTP:

| Registry entry | Client | Purpose |
| --- | --- | --- |
| `job_posting` | `DiscordMCPPublisher` | Discord status checks and explicitly approved posting |
| `interview_scheduling` | `InterviewMCPClient` | Authenticated selection, scheduling, invitations and rescheduling |

## Registry fields

Each `mcpServers` entry contains:

- `type`: `http` only. This application does not launch arbitrary `stdio` commands from JSON.
- `url`: address used with the Docker profile, e.g. `http://interview-mcp:8002/mcp`.
- `localUrl`: optional address for native development, e.g. `http://localhost:8002/mcp`. If omitted, `url` is used in both profiles.
- `timeoutSeconds`: numeric request deadline from 1 to 600 seconds. Publishing defaults to 30 and scheduling to 120 in the committed registry. Interview HTTP requests and the overall tool-call deadline both use it.

`localUrl` and `timeoutSeconds` are HireSense-specific extensions to the familiar `mcpServers` shape, not a claim that this file is universally portable to every MCP client. Both application entries are required. Additional entries can be stored, but merely adding an entry does not register new supervisor tools or grant permissions.

## Environment and Docker

`MCP_PROFILE` selects `local` (native default) or `docker`. `MCP_CONFIG_FILE` optionally selects the registry file. Native default is the repository-root file; relative overrides are resolved against the repository root, never the shell working directory.

Docker Compose explicitly sets `MCP_PROFILE=docker` and `MCP_CONFIG_FILE=/app/mcp.json` and mounts the root file read-only into the backend. Missing host files cause deployment to fail rather than creating an empty directory. The JSON is intentionally not duplicated inside the backend build context. A bare `docker run` must mount the registry and set these selectors itself.

The old `JOB_POSTING_MCP_URL`, `JOB_POSTING_MCP_TIMEOUT_SECONDS`, `INTERVIEW_MCP_URL` and `INTERVIEW_MCP_TIMEOUT_SECONDS` settings no longer override client configuration. Edit the root JSON for endpoints and deadlines. Existing explicit Python constructor overrides remain available for isolated tests.

Compose still starts the independent `job-posting-mcp` and `interview-mcp` services. Server code still defines their listen ports and registered tools. `INTERVIEW_BACKEND_URL` is the scheduling server's destination for backend REST calls, not an MCP endpoint. Discord channel/bot settings, SMTP configuration, JWT secrets and other business settings stay in the root `.env`/scoped container environment. This registry centralizes client connections; it does not replace server deployment or merge the two services.

For native development, start the two server processes on localhost ports 8001 and 8002, or use an intentionally configured reachable endpoint. Docker's internal service names work only on its network; the existing Compose setup does not publish those MCP ports to the host.

## Validation and safety

`app/mcp_config.py` validates the registry and returns an immutable resolved connection to each client. Backend startup validates both entries before initializing business data or recovering confirmed deliveries; it does not call MCP tools during validation. Unknown transport types/fields, missing servers, malformed URLs, duplicate keys, oversized files and invalid timeouts fail closed with a sanitized configuration error. There is no hidden environment-URL fallback. URL user information, query parameters and fragments are rejected to discourage credentials in tracked JSON. Do not add tokens, authorization headers or secrets to this file. Use trusted endpoints only: scheduling credentials are forwarded to the configured scheduling service.

Interviewer authentication remains generated dynamically from the authenticated user for each MCP request. It is not read from JSON or supplied by the LLM. Approval gates, candidate ownership checks, tool allowlists and uncertain-delivery handling are unchanged. Treat the registry as trusted deployment configuration: it is editable by the project maintainer, not by the chatbot or candidates.

New client instances read the registry; existing in-flight calls retain their resolved settings. After editing deployment addresses, recreate the backend with the current public-origin overlay preserved and only after active interviews and pending email deliveries have been resolved. No schema migration, new credentials or Google Form changes are required.

## Tests

`tests/test_mcp_config.py` covers Docker/native resolution, both client integrations, relative paths, edited files, invalid/secret-bearing content, lack of legacy environment fallbacks and runtime JWT/timeout propagation. Live connectivity checks should use only read-only tools (`get_discord_posting_status` and `list_interview_schedules`); never publish or send invitations merely to test configuration.
