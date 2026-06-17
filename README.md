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

## Layout

- `daemon/` — Python FastAPI daemon (SQLite + the MCP render-primitive vocabulary; Agent SDK chat sessions)
- `web/` — TypeScript React client (added in a later phase)
- `skills/` — launcher skills (added in a later phase)
