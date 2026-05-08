/**
 * ChatMarkdown — renders assistant responses as markdown with syntax-highlighted
 * code blocks. Kept intentionally small: GFM + prism-react-renderer.
 *
 * Styling sticks to the AWS-console Tailwind palette used elsewhere in the panel.
 */

import { memo, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Highlight, themes } from 'prism-react-renderer';

interface CodeBlockProps {
  language: string;
  value: string;
}

function CodeBlock({ language, value }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [value]);

  return (
    <div className="relative my-2 rounded-lg overflow-hidden border border-[#2b3544] bg-[#0f172a]">
      <div className="flex items-center justify-between px-3 py-1 bg-[#1e293b] border-b border-[#2b3544]">
        <span className="text-[10px] uppercase tracking-wide text-slate-400 font-mono">
          {language || 'text'}
        </span>
        <button
          onClick={handleCopy}
          className="text-[10px] text-slate-400 hover:text-white transition-colors font-medium"
          aria-label="Copy code"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <Highlight theme={themes.vsDark} code={value.replace(/\n$/, '')} language={language || 'text'}>
        {({ className, style, tokens, getLineProps, getTokenProps }) => (
          <pre
            className={`${className} text-xs p-3 overflow-x-auto`}
            style={{ ...style, margin: 0, background: 'transparent' }}
          >
            {tokens.map((line, i) => {
              const lineProps = getLineProps({ line });
              return (
                <div key={i} {...lineProps}>
                  {line.map((token, key) => {
                    const tokenProps = getTokenProps({ token });
                    return <span key={key} {...tokenProps} />;
                  })}
                </div>
              );
            })}
          </pre>
        )}
      </Highlight>
    </div>
  );
}

export interface ChatMarkdownProps {
  content: string;
}

/**
 * Renders markdown content. Safe defaults: no raw HTML, no autolink of bare URLs
 * (remark-gfm autolinks, which is fine), tables and task-lists enabled.
 */
export const ChatMarkdown = memo(function ChatMarkdown({ content }: ChatMarkdownProps) {
  return (
    <div className="chat-markdown text-sm text-[#16191f] leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-2 last:mb-0 whitespace-pre-wrap">{children}</p>,
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#0972d3] hover:underline"
            >
              {children}
            </a>
          ),
          ul: ({ children }) => <ul className="list-disc ml-5 my-2 space-y-0.5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal ml-5 my-2 space-y-0.5">{children}</ol>,
          li: ({ children }) => <li className="leading-snug">{children}</li>,
          h1: ({ children }) => <h1 className="text-base font-semibold text-[#16191f] mt-3 mb-1.5">{children}</h1>,
          h2: ({ children }) => <h2 className="text-sm font-semibold text-[#16191f] mt-3 mb-1">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold text-[#16191f] mt-2 mb-1">{children}</h3>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-[#0972d3]/40 pl-3 my-2 text-[#5f6b7a] italic">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-2">
              <table className="text-xs border-collapse border border-[#e9ebed] rounded">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-[#e9ebed] px-2 py-1 bg-[#f2f3f3] text-left font-medium">{children}</th>
          ),
          td: ({ children }) => <td className="border border-[#e9ebed] px-2 py-1">{children}</td>,
          hr: () => <hr className="my-3 border-[#e9ebed]" />,
          code: (props) => {
            // react-markdown v9+ passes an `inline` flag via `node`, but the types treat it as
            // unknown — we detect inline vs block by presence of a className like "language-*".
            const { className, children, ...rest } = props as {
              className?: string;
              children?: React.ReactNode;
            };
            const match = /language-(\w+)/.exec(className || '');
            const codeString = String(children ?? '').replace(/\n$/, '');
            if (!match) {
              return (
                <code
                  className="px-1 py-0.5 rounded bg-[#f2f3f3] text-[#d45b07] font-mono text-[12px] border border-[#e9ebed]"
                  {...rest}
                >
                  {children}
                </code>
              );
            }
            return <CodeBlock language={match[1]} value={codeString} />;
          },
          pre: ({ children }) => <>{children}</>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});

export default ChatMarkdown;
