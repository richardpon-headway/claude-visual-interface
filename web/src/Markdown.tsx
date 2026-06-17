import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

// Links open in a new tab so following one doesn't navigate away from the surface.
const components: Components = {
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
};

// Renders model-authored markdown — GFM tables/lists/strikethrough plus
// syntax-highlighted code blocks (via rehype-highlight). Styling lives in the
// scoped `.markdown-body` block in styles.css. react-markdown does not render raw
// HTML by default, so this is safe for streamed model output.
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
