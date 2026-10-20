import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  p: (p) => <p className="m-0 mb-2.5 last:mb-0" {...strip(p)} />,
  h1: (p) => <h3 className="m-0 mb-2 mt-3 text-[15px] font-bold first:mt-0" {...strip(p)} />,
  h2: (p) => <h3 className="m-0 mb-2 mt-3 text-[15px] font-bold first:mt-0" {...strip(p)} />,
  h3: (p) => <h4 className="m-0 mb-1.5 mt-3 text-[14px] font-bold first:mt-0" {...strip(p)} />,
  h4: (p) => <h4 className="m-0 mb-1.5 mt-3 text-[14px] font-bold first:mt-0" {...strip(p)} />,
  ul: (p) => <ul className="m-0 mb-2.5 list-disc pl-5 last:mb-0" {...strip(p)} />,
  ol: (p) => <ol className="m-0 mb-2.5 list-decimal pl-5 last:mb-0" {...strip(p)} />,
  li: (p) => <li className="mb-1 [&>p]:mb-1" {...strip(p)} />,
  strong: (p) => <strong className="font-semibold" {...strip(p)} />,
  hr: () => <hr className="my-3 border-0 border-t border-black/20 dark:border-white/10" />,
  blockquote: (p) => (
    <blockquote
      className="m-0 mb-2.5 border-l-[3px] border-accent-1 bg-black/[0.05] px-3 py-1.5 dark:bg-white/5"
      {...strip(p)}
    />
  ),
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="font-medium text-accent-1 underline underline-offset-2 break-words">
      {children}
    </a>
  ),
  code: ({ className, children }) =>
    className ? (
      <code className="font-mono text-[12.5px]">{children}</code>
    ) : (
      <code className="rounded bg-black/[0.08] px-1 py-0.5 font-mono text-[12.5px] dark:bg-white/10">{children}</code>
    ),
  pre: (p) => (
    <pre
      className="m-0 mb-2.5 overflow-x-auto rounded-lg bg-black/[0.08] p-3 leading-snug dark:bg-white/10"
      {...strip(p)}
    />
  ),
  table: (p) => (
    <div className="mb-2.5 overflow-x-auto">
      <table className="w-full border-collapse text-[13px]" {...strip(p)} />
    </div>
  ),
  th: (p) => (
    <th
      className="border border-black/20 bg-black/[0.06] px-2.5 py-1.5 text-left font-semibold dark:border-white/10 dark:bg-white/5"
      {...strip(p)}
    />
  ),
  td: (p) => <td className="border border-black/20 px-2.5 py-1.5 align-top dark:border-white/10" {...strip(p)} />,
};

function strip<T extends { node?: unknown }>(props: T): Omit<T, "node"> {
  const { node: _node, ...rest } = props;
  return rest;
}

export function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {text}
    </ReactMarkdown>
  );
}
