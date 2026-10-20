const URL_PATTERN = /https?:\/\/[^\s<>]+/g;

export function Linkify({ text }: { text: string }) {
  const parts = text.split(URL_PATTERN);
  const urls = text.match(URL_PATTERN) ?? [];
  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {i < urls.length && (
            <a
              href={urls[i]}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-accent-1 underline underline-offset-2"
            >
              {urls[i]}
            </a>
          )}
        </span>
      ))}
    </>
  );
}
