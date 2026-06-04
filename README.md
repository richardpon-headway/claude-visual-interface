# Claude Visual Interface (CVI)

A local-first visual surface for Claude sessions. A local daemon hosts Claude
sessions and an MCP server; a browser renders code, diffs, and findings the
session pushes, and feeds your input back — all talking to the API directly,
no shared gateway.

First use case: **PR reviews** — see the code and Claude's findings together,
with a single conversation to discuss them.

> Early / work in progress.

## Stack

- **Daemon:** Python — FastAPI + Claude Agent SDK + MCP server + SQLite
- **Web:** TypeScript — React + Vite + Tailwind + Monaco

## Run

    make install   # set up the daemon (and the web client, once it exists)
    make run       # start the daemon on 127.0.0.1:47825 (its log streams in this terminal)

Health check:

    curl http://127.0.0.1:47825/health    # {"status": "ok"}

## Layout

- `daemon/` — Python FastAPI daemon (SQLite, and later the MCP server + Agent SDK sessions)
- `web/` — TypeScript React client (added in a later phase)
- `skills/` — the launcher / review-adapter skills (added in a later phase)
