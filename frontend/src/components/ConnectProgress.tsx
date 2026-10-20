import { useEffect, useState } from "react";

export function ConnectProgress({ label, percent, startedAt }: { label: string; percent: number; startedAt: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, []);
  const secs = Math.max(0, Math.floor((now - startedAt) / 1000));
  const elapsed = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  const slow = /Downloading|Generating/.test(label);
  return (
    <div className="flex flex-col gap-2" role="status" aria-live="polite">
      <div className="flex items-baseline justify-between gap-3 text-[12.5px] text-[#4B5160] dark:text-[#C9CED8]">
        <span className="min-w-0 flex-grow">{label}</span>
        <span className="flex-shrink-0 font-mono text-[11.5px] text-[#565D70] dark:text-[#9198A8]">{elapsed}</span>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-[#CBD0DC] dark:bg-white/10"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-accent-1 to-accent-2 transition-[width] duration-500"
          style={{ width: `${Math.min(100, Math.max(2, percent))}%` }}
        />
      </div>
      {slow && (
        <p className="m-0 text-[11.5px] leading-relaxed text-[#565D70] dark:text-[#9198A8]">
          First time with this firmware version: downloading its documentation source (about four minutes, one time —
          later connections are instant).
        </p>
      )}
    </div>
  );
}
