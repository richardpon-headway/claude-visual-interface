import Editor from "@monaco-editor/react";

import type { OpenFile } from "./viewState";

// Minimal extension → Monaco language map for the skeleton. The renderer phase
// will replace this with proper detection.
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

export function CodePane({ openFile }: { openFile: OpenFile | undefined }) {
  if (!openFile) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-500">
        no file open
      </div>
    );
  }

  // File contents are not served yet (they arrive with the review checkout in a
  // later slice); show the path so the push→render path is visible meanwhile.
  const placeholder = `// ${openFile.file}\n// (file contents render in a later slice)\n`;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-3 py-1 font-mono text-xs text-zinc-400">
        {openFile.file}
        {openFile.range ? ` (${openFile.range.start}–${openFile.range.end})` : ""}
      </div>
      <div className="min-h-0 flex-1">
        <Editor
          height="100%"
          theme="vs-dark"
          path={openFile.file}
          language={languageFor(openFile.file)}
          value={placeholder}
          options={{ readOnly: true, minimap: { enabled: false } }}
        />
      </div>
    </div>
  );
}
