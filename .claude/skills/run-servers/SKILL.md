---
name: run-servers
description: "Launch the companysim dev servers — the FastAPI backend (port 8611) and the Vite/React frontend (port 5173) — wait for readiness, and smoke-test them. Use whenever asked to run, start, restart, or stop the app, the servers, the backend, the API, the frontend, or the webapp; or to check something in the running app rather than in tests."
---

# Run the companysim dev servers

Two processes. Both must be up for the webapp to work: the React frontend
calls the API on `localhost:8611`, and the API's CORS policy only accepts
`localhost:5173`.

| | Command | Port |
|---|---|---|
| Backend | `.venv/Scripts/python -m uvicorn companysim.api.main:app --port 8611` | 8611 |
| Frontend | `cd webapp && npm run dev` | 5173 |

## Start

**Launch each server with the Bash tool's `run_in_background: true`** — one
call per server, both in the same message. Then run `wait.sh`.

```bash
# call 1 (run_in_background: true)
# `set -a` + sourcing .env exports the optional LLM keys/flags if the user
# has created one (see "Optional LLM features"). Harmless when absent —
# without it the app just runs with those features off.
set -a; [ -f .env ] && . ./.env; set +a
.venv/Scripts/python -m uvicorn companysim.api.main:app --port 8611 \
  > .claude/skills/run-servers/logs/api.log 2>&1

# call 2 (run_in_background: true)
cd webapp && npm run dev > ../.claude/skills/run-servers/logs/vite.log 2>&1
```

```bash
# then, foreground — polls readiness and smoke-tests both
bash .claude/skills/run-servers/wait.sh
```

`wait.sh` exits 0 only when both are genuinely serving, and dumps the log
tails when they aren't. Flags: `--api-only`, `--web-only`.

Expected output:

```
=== smoke ===
GET /health          {"status":"ok"}
GET /orgs            HTTP 200
GET /model/status    HTTP 200
GET /src/main.tsx    HTTP 200
```

**Do not background the servers from inside a shell script.** A server
launched that way inherits the script's descriptors under Git Bash/MSYS and
holds it open indefinitely — the script finishes its work but never returns,
so the caller sits until timeout. `nohup`, `< /dev/null` and `disown` were
each tried and none of them release it. The Bash tool's own
`run_in_background` detaches correctly; that is why launching lives in the
caller and only waiting lives in a script.

## Stop

```bash
bash .claude/skills/run-servers/stop.sh          # both
bash .claude/skills/run-servers/stop.sh --api-only
```

Kills whatever holds each port, via `netstat -ano` + `taskkill` (this is
Windows — there is no `lsof`). It kills **by port, never by process-name
pattern**: `pkill -f "node|vite|python"` on a dev box will take out the
agent's own session or an unrelated language server.

Restarting = `stop.sh`, then the start steps above.

## Prerequisites

Both are already satisfied in this repo; check only if something fails.

```bash
.venv/Scripts/python -c "import companysim, fastapi, uvicorn"   # backend deps
ls webapp/node_modules >/dev/null                               # frontend deps
```

If either is missing: `pip install -e ".[dev,ml,viz,api,llm]"` /
`cd webapp && npm install`.

## Things that will bite you

- **The API port is 8611, not uvicorn's default 8000.**
  `webapp/src/api/client.ts:30` hardcodes
  `const API_BASE = "http://localhost:8611"` and there is no env override.
  Start the API on 8000 and the UI renders perfectly, then shows a red
  **"Failed to fetch"** under every panel — which reads like a backend
  crash but is only a wrong port. Check `client.ts` before assuming
  anything else. (This exact mistake shipped in the first version of this
  skill.)
- **Port 5173 is not configurable.** `webapp/vite.config.ts` sets
  `strictPort: true`, and `api/main.py` hardcodes CORS `allow_origins` to
  `localhost:5173`. Change it in one place only and you get a frontend that
  loads fine and then fails every fetch with an opaque CORS error. Change
  both, or neither.
- **The API binds IPv4-only.** Vite listens on `[::1]:5173` but uvicorn
  listens on `127.0.0.1` — `curl "http://[::1]:8611/health"` fails while
  `localhost` works, because both curl and browsers fall back to IPv4.
  Worth knowing when a raw-IPv6 client can't reach the API.
- **The API migrates on startup.** `api/database.py::init_db` runs
  `alembic upgrade head` from the lifespan hook, so the first start after a
  schema change takes a few extra seconds and *mutates `data/app.db`*. If
  the DB matters, back it up first.
- **`data/app.db` is the real seeded demo database**, not a fixture. Driving
  write endpoints (`POST /orgs/{id}/documents/.../apply`, employee PATCH,
  `POST /model/train`) changes data the user can see in the UI. Note the
  original values and restore them, or work against a throwaway org.
- **uvicorn access logs are buffered** in the redirected log file — an empty
  `api.log` after a request does not mean the request failed. Trust the
  `curl` status code, not the log.
- **`curl -F "file=@x.csv"` needs a cwd-relative path** in Git Bash; an
  absolute `/c/Users/...` path fails with exit 26. `cd` to the file's
  directory first.
- **`python` on PATH is the system 3.13, not the venv.** Use
  `.venv/Scripts/python` for anything importing `companysim`.

## Optional LLM features

All off by default; the app works fully without them. Set before launching
the backend (the frontend needs nothing). `.env.example` documents every
variable — copy it to `.env` and the launch command above picks it up.

**Pick a provider**, then set that provider's credentials:

| Variable | Value |
|---|---|
| `COMPANYSIM_LLM_PROVIDER` | `groq` (default) or `bedrock` |

| Groq (default) | AWS Bedrock |
|---|---|
| `GROQ_API_KEY` | `AWS_DEFAULT_REGION` (**required** — no default) |
| | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`, *or* `AWS_PROFILE`, *or* an IAM role |
| | `COMPANYSIM_BEDROCK_MODEL_ID` |

Then turn on whichever features you want:

| Variable | Enables |
|---|---|
| `COMPANYSIM_LLM_EXIT_NOTES=1` | LLM-written exit notes during `/diagnose` |
| `COMPANYSIM_LLM_CHAT=1` | the "Ask Vantage" chat widget |
| `COMPANYSIM_LLM_INGEST=1` | free-text extraction (reviews, letters, offers, CVs) |

Without them, exit notes fall back to the template generator, chat shows a
"not configured" message, and document extraction parks free-text uploads as
`needs_review` — none of these are errors.

**Verify before trusting it:**

```bash
set -a; . ./.env; set +a
.venv/Scripts/python scripts/check_llm_provider.py     # exits 0 when a real call worked
```

Run this on any new machine and after any `.env` change. Every LLM feature
here fails *silently by design* — extraction parks the document, exit notes
use templates, chat reports an outage — so a misconfiguration is otherwise
indistinguishable from a model that declined. The script checks each layer
separately (SDK → credentials → STS identity → model id → live call) and
names the one that broke.

**Bedrock gotchas the script will tell you about:**

- **The region is mandatory.** Bedrock's endpoint is regional and boto3
  raises `NoRegionError` rather than defaulting. `AWS_DEFAULT_REGION=eu-west-2`.
- **EU regions need the `eu.` inference-profile prefix.** A bare
  `anthropic.claude-...` id is rejected with `ValidationException` in
  `eu-west-2`; it has to be `eu.anthropic.claude-...`. List what the
  account can actually call:
  `aws bedrock list-inference-profiles --region eu-west-2`
- **Model access is granted per account**, in the Bedrock console under
  *Model access*. Valid credentials plus an ungranted model still fails.
- **`bedrock:InvokeModel` is a separate permission** from being able to
  authenticate — an `AccessDeniedException` after a good STS identity means
  the IAM policy, not the keys.

## Driving it

Beyond the smoke test, useful checks against a live server:

```bash
curl -s http://localhost:8611/orgs | head -c 300
curl -s http://localhost:8611/model/status
curl -s http://localhost:8611/orgs/<id>/documents/cohort
curl -s http://localhost:8611/orgs/<id>/at-risk
```

Swagger UI at http://localhost:8611/docs lists every route. For the
frontend, `GET /src/main.tsx` returning 200 proves the transform pipeline
works; to actually see rendered UI you need a browser driver, not `curl`.
