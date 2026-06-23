# Claude Visual Interface (CVI)

A local-first visual surface for Claude sessions. A local daemon hosts Claude
sessions and an MCP server; a browser renders the visuals and code the session
pushes, and feeds your input back — all talking to the API directly, no shared
gateway.

It's a single scrolling conversation: ask Claude anything and read the reply top to
bottom, with designs, diagrams, tables, and reports rendered inline as you go.

> Early / work in progress.

## Stack

- **Daemon:** Python — FastAPI + Claude Agent SDK + MCP server + SQLite
- **Web:** TypeScript — React + Vite + Tailwind + Monaco

## Run

    make install   # set up the daemon (and the web client, once it exists)
    make run       # start the daemon on 127.0.0.1:47825 (its log streams in this terminal)

Health check:

    curl http://127.0.0.1:47825/health    # {"status": "ok"}

## Configure

On first run the daemon writes a `config.yaml` (repo root, gitignored — it holds a
machine-specific path) with documented defaults you can edit:

- **`working_dir`** — the directory every chat session is rooted at, so Claude can
  read and edit files under it. Defaults to the parent of the CVI repo, making
  sibling repositories visible. Use an absolute path; a leading `~` is expanded.

Edits take effect on the next session — no daemon restart needed.

## Layout

- `daemon/` — Python FastAPI daemon (SQLite + the MCP render-primitive vocabulary; Agent SDK chat sessions)
- `web/` — TypeScript React client (added in a later phase)
- `skills/` — launcher skills (added in a later phase)
