import type { SafetyParamEntry } from "../api/types";

export function SafetySnapshotView({ params, text }: { params: SafetyParamEntry[]; text?: string }) {
  return (
    <div>
      <h4 className="m-0 mb-2 text-[12px] font-bold uppercase tracking-wide text-[#5B6275] dark:text-[#9198A8]">Safety parameter snapshot</h4>
      {params.length === 0 ? (
        <p className="m-0 text-[12.5px] text-[#5B6275] dark:text-[#9198A8]">No safety-relevant parameters found on this vehicle.</p>
      ) : (
        <div className="glass max-h-56 overflow-y-auto rounded-xl">
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr className="text-left text-[10.5px] uppercase text-[#5B6275] dark:text-[#9198A8]">
                <th className="px-3 py-2 font-semibold">Parameter</th>
                <th className="px-3 py-2 font-semibold">Value</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {params.map((p) => (
                <tr key={p.name} className="border-t border-black/[0.12] dark:border-white/10">
                  <td className="px-3 py-2 font-mono text-[#1F2430] dark:text-[#E8EAED]">{p.name}</td>
                  <td className="px-3 py-2 font-mono text-[#4B5164] dark:text-[#B7BFCA]">{p.current_value}</td>
                  <td className="px-3 py-2">
                    {!p.documented && (
                      <span className="rounded-md bg-warn-text/15 px-1.5 py-0.5 text-[9.5px] font-semibold text-warn-text">
                        undocumented
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {text && (
        <pre className="mt-2 max-h-40 overflow-auto rounded-xl bg-black/[0.08] p-3 text-[11px] text-[#4B5164] dark:bg-white/5 dark:text-[#9198A8]">
          {text}
        </pre>
      )}
    </div>
  );
}
