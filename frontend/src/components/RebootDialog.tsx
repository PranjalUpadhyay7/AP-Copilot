import { useEffect, useState } from "react";
import { useSession } from "../state/SessionStore";
import { ConnectProgress } from "./ConnectProgress";

export function RebootDialog({ onClose }: { onClose: () => void }) {
  const { rebootVehicle, rebootProgress, rebootError } = useSession();
  const [started, setStarted] = useState(false);
  const running = rebootProgress !== null;
  // Closes itself shortly after the same chat reconnects
  const finishedOk = started && !running && !rebootError;

  useEffect(() => {
    if (!finishedOk) return;
    const id = setTimeout(onClose, 1500);
    return () => clearTimeout(id);
  }, [finishedOk, onClose]);

  const btn = "rounded-lg px-4 py-2 text-[13px] font-semibold";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" role="dialog" aria-modal="true">
      <div className="glass flex w-full max-w-[460px] flex-col gap-4 rounded-2xl bg-white p-6 shadow-xl dark:bg-[#1c1f2b]">
        <h2 className="m-0 text-[16px] font-bold">Reboot the flight controller</h2>

        {!started && (
          <>
            <p className="m-0 text-[13px] leading-relaxed text-[#4B5160] dark:text-[#C9CED8]">
              The link will drop for roughly 10–30 seconds, then this same chat reconnects automatically. Only possible
              while the vehicle is <b>disarmed</b>, with no proposal waiting for your decision.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} className={`${btn} border border-[#C3C9D6] dark:border-white/10`}>
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  setStarted(true);
                  void rebootVehicle();
                }}
                className={`${btn} bg-gradient-to-br from-accent-1 to-accent-2 text-white`}
              >
                Reboot now
              </button>
            </div>
          </>
        )}

        {running && rebootProgress && (
          <>
            <div
              data-testid="link-badge"
              className={`w-fit rounded-full px-3 py-1 text-[12px] font-semibold ${
                rebootProgress.link === "up"
                  ? "bg-[#E3F7EE] text-[#157F54]"
                  : "bg-[#FFF1DE] text-warn-text"
              }`}
            >
              Link: {rebootProgress.link === "up" ? "connected" : "down — waiting for the vehicle"}
            </div>
            <ConnectProgress label={rebootProgress.label} percent={rebootProgress.percent} startedAt={rebootProgress.startedAt} />
          </>
        )}

        {finishedOk && <p className="m-0 text-[13px] text-[#157F54]">Reconnected. Chat and telemetry continue.</p>}

        {rebootError && (
          <>
            <p className="m-0 text-[13px] leading-relaxed text-danger">{rebootError}</p>
            <div className="flex justify-end">
              <button type="button" onClick={onClose} className={`${btn} border border-[#C3C9D6] dark:border-white/10`}>
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
