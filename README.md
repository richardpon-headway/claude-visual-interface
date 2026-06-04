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

    make run    # start the daemon (its log streams in this terminal)
