import { useEffect, useMemo, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import type { OnMount } from "@monaco-editor/react";

import { toDecorations } from "./decorations";
import type { Finding, OpenFile, Range } from "./viewState";

// Minimal extension → Monaco language map. The renderer phase will replace this
// with proper detection.
const LANGUAGES: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  py: "python",
  rs: "rust",
  go: "go",
  json: "json",
  md: "markdown",
  css: "css",
  html: "html",
  sql: "sql",
};

function languageFor(file: string): string {
  const ext = file.split(".").pop() ?? "";
  return LANGUAGES[ext] ?? "plaintext";
}

type FileState =
  | { status: "loading" }
  | { status: "text"; content: string }
  | { status: "binary" }
  | { status: "too_large" }
  | { status: "missing" };

const OVERLAY_MESSAGE: Record<Exclude<FileState["status"], "text">, string> = {
  loading: "loading…",
  binary: "binary file",
  too_large: "file too large to display",
  missing: "file not found",
};

type MonacoEditor = Parameters<OnMount>[0];
type Monaco = Parameters<OnMount>[1];

export function CodePane({
  surface,
  openFile,
  findings,
  highlights,
  reveal,
}: {
  surface: string;
  openFile: OpenFile | undefined;
  findings: Finding[];
  highlights: Record<string, Range[]>;
  reveal?: { range: Range; nonce: number } | null;
}) {
  const file = openFile?.file;
  const [state, setState] = useState<FileState>({ status: "loading" });

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    setState({ status: "loading" });
    fetch(`/sessions/${encodeURIComponent(surface)}/file?path=${encodeURIComponent(file)}`)
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setState({ status: "missing" });
          return;
        }
        const data: unknown = await res.json();
        const content = (data as { content?: unknown }).content;
        const reason = (data as { reason?: unknown }).reason;
        if (typeof content === "string") setState({ status: "text", content });
        else if (reason === "binary") setState({ status: "binary" });
        else if (reason === "too_large") setState({ status: "too_large" });
        else setState({ status: "missing" });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "missing" });
      });
    return () => {
      cancelled = true;
    };
  }, [surface, file]);

  const decorations = useMemo(
    () => (file ? toDecorations(file, findings, highlights) : []),
    [file, findings, highlights],
  );

  const editorRef = useRef<MonacoEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const [editorReady, setEditorReady] = useState(false);

  // Apply decorations once the editor exists and real content is loaded; re-run
  // when the editor mounts (editorReady), the content changes, or findings move.
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco || state.status !== "text") return;
    const collection = editor.createDecorationsCollection(
      decorations.map((d) => ({
        range: new monaco.Range(d.startLine, 1, d.endLine, 1),
        options: {
          isWholeLine: true,
          className: d.kind === "finding" ? "cvi-finding-line" : "cvi-highlight-line",
        },
      })),
    );
    return () => collection.clear();
  }, [decorations, state, editorReady]);

  // Scroll to a revealed range (a clicked finding's anchor). The reveal carries
  // a nonce so re-selecting the same finding re-fires this; `state` keeps it from
  // firing before the file's content has loaded.
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !reveal || state.status !== "text") return;
    editor.revealRangeInCenter({
      startLineNumber: reveal.range.start,
      startColumn: 1,
      endLineNumber: reveal.range.end,
      endColumn: 1,
    });
  }, [reveal, state, editorReady]);

  if (!openFile || !file) {
    return <Centered>no file open</Centered>;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-3 py-1 font-mono text-xs text-zinc-400">
        {file}
        {openFile.range ? ` (${openFile.range.start}–${openFile.range.end})` : ""}
      </div>
      <div className="relative min-h-0 flex-1">
        <Editor
          height="100%"
          theme="vs-dark"
          path={file}
          language={languageFor(file)}
          value={state.status === "text" ? state.content : ""}
          options={{ readOnly: true, minimap: { enabled: false } }}
          onMount={(editor, monaco) => {
            editorRef.current = editor;
            monacoRef.current = monaco;
            setEditorReady(true);
          }}
        />
        {state.status !== "text" ? (
          <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/80 text-sm text-zinc-500">
            {OVERLAY_MESSAGE[state.status]}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-zinc-500">{children}</div>
  );
}
