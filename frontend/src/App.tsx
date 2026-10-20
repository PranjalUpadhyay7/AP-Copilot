import { useEffect, useState } from "react";
import { ChatPane } from "./components/ChatPane";
import { ConfirmationModal } from "./components/ConfirmationModal";
import { ConnectProgress } from "./components/ConnectProgress";
import { RebootDialog } from "./components/RebootDialog";
import { SessionHistoryPanel } from "./components/SessionHistoryPanel";
import { SessionSummary } from "./components/SessionSummary";
import { TelemetryPanel } from "./components/TelemetryPanel";
import { ThemeToggle } from "./components/ThemeToggle";
import { api } from "./api/client";
import { SessionProvider, useSession } from "./state/SessionStore";
import { ThemeProvider } from "./theme/ThemeProvider";
import type { PortInfo, SITLSettings } from "./api/types";

const DEFAULT_SITL_SETTINGS: SITLSettings = {
  vehicle: "copter",
  frame: null,
  instance: 0,
  wipe_eeprom: true,
  speedup: 1,
};

function Logo() {
  return (
    <div className="flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-accent-1 to-accent-2 shadow-[0_4px_12px_rgba(99,102,241,0.35)]">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5">
        <path d="M12 2L2 7l10 5 10-5-10-5z" />
        <path d="M2 17l10 5 10-5M2 12l10 5 10-5" />
      </svg>
    </div>
  );
}

function ConnectScreen({ onOpenHistory }: { onOpenHistory: () => void }) {
  const { connect, connecting, connectProgress, error } = useSession();
  const [mode, setMode] = useState<"simulation" | "hardware">("simulation");
  const [connectionString, setConnectionString] = useState("auto");
  const [customAddress, setCustomAddress] = useState(false);
  const [ports, setPorts] = useState<PortInfo[]>([]);
  const refreshPorts = () => {
    api
      .listPorts()
      .then(setPorts)
      .catch(() => setPorts([]));
  };
  useEffect(() => {
    if (mode === "hardware") refreshPorts();
  }, [mode]);
  const [sitlSettings, setSitlSettings] = useState<SITLSettings>(DEFAULT_SITL_SETTINGS);
  const [showSitlSettings, setShowSitlSettings] = useState(false);

  return (
    <div className="bg-app flex h-full flex-col text-[#1F2430] dark:text-[#E8EAED]">
      <div className="flex items-center justify-between px-7 py-5">
        <div className="flex items-center gap-2.5">
          <Logo />
          <span className="text-[15px] font-semibold tracking-tight">AP-Copilot</span>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button
            type="button"
            onClick={onOpenHistory}
            className="flex items-center gap-1.5 rounded-full border border-black/[0.12] bg-white px-3.5 py-2 text-[12.5px] text-[#5A6072] hover:bg-white dark:border-white/10 dark:bg-white/5 dark:text-[#9AA1B1] dark:hover:bg-white/10"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            History
          </button>
        </div>
      </div>

      <div className="flex flex-grow flex-col items-center justify-center gap-6 px-10 py-5">
        <div className="text-center">
          <h1 className="m-0 mb-2 text-[23px] font-semibold tracking-tight">Connect to a vehicle</h1>
          <p className="m-0 max-w-[420px] text-[13.5px] text-[#565D70] dark:text-[#9198A8]">
            Every parameter change still needs your explicit confirmation — this only opens a read/telemetry link.
          </p>
        </div>

        <form
          className="flex w-full max-w-[420px] flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (mode === "simulation") {
              void connect({ mode: "simulation", sitlSettings });
            } else {
              void connect({ mode: "hardware", connectionString });
            }
          }}
        >
          <div className="glass flex rounded-[13px] p-1 shadow-[0_8px_24px_rgba(31,36,90,0.14)]" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "simulation"}
              onClick={() => setMode("simulation")}
              className={`flex-1 rounded-[10px] py-2.5 text-[13px] font-semibold transition-colors ${
                mode === "simulation"
                  ? "bg-white text-[#1F2430] shadow-[0_2px_8px_rgba(31,36,48,0.08)] dark:bg-white/10 dark:text-[#E8EAED]"
                  : "text-[#5B6275] dark:text-[#9198A8]"
              }`}
            >
              Simulation
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "hardware"}
              onClick={() => setMode("hardware")}
              className={`flex-1 rounded-[10px] py-2.5 text-[13px] font-semibold transition-colors ${
                mode === "hardware"
                  ? "bg-white text-[#1F2430] shadow-[0_2px_8px_rgba(31,36,48,0.08)] dark:bg-white/10 dark:text-[#E8EAED]"
                  : "text-[#5B6275] dark:text-[#9198A8]"
              }`}
            >
              Real Hardware
            </button>
          </div>

          {mode === "hardware" ? (
            <div className="glass flex flex-col gap-3 rounded-2xl p-5 shadow-[0_8px_24px_rgba(31,36,90,0.14)]">
              <p className="m-0 text-[12.5px] leading-relaxed text-[#565D70] dark:text-[#9198A8]">
                Connect to a real flight controller or a SITL instance you started yourself.
              </p>
              <div className="flex gap-2">
                <select
                  value={customAddress ? "__custom__" : connectionString}
                  onChange={(e) => {
                    if (e.target.value === "__custom__") {
                      setCustomAddress(true);
                      setConnectionString("tcp:127.0.0.1:5760");
                    } else {
                      setCustomAddress(false);
                      setConnectionString(e.target.value);
                    }
                  }}
                  className="min-w-0 flex-grow rounded-lg border border-[#C3C9D6] bg-white px-3 py-2.5 text-[13px] text-[#1F2430] outline-none focus:border-accent-1 dark:border-white/10 dark:bg-[#1c1f2b] dark:text-[#E8EAED]"
                >
                  <option value="auto">Auto-detect flight controller</option>
                  {ports.map((p) => (
                    <option key={p.path} value={p.path}>
                      {p.label} — {p.path}
                    </option>
                  ))}
                  <option value="__custom__">Other (type an address)…</option>
                </select>
                <button
                  type="button"
                  onClick={refreshPorts}
                  title="Rescan serial devices"
                  className="rounded-lg border border-[#C3C9D6] px-3 text-[13px] text-[#4B5160] hover:border-accent-1 dark:border-white/10 dark:text-[#C9CED8]"
                >
                  Rescan
                </button>
              </div>
              {customAddress && (
                <input
                  value={connectionString}
                  onChange={(e) => setConnectionString(e.target.value)}
                  className="rounded-lg border border-[#C3C9D6] bg-white px-3 py-2.5 font-mono text-[13px] text-[#1F2430] outline-none focus:border-accent-1 dark:border-white/10 dark:bg-white/5 dark:text-[#E8EAED]"
                />
              )}
              <p className="m-0 text-[11.5px] leading-relaxed text-[#565D70] dark:text-[#9198A8]">
                {ports.length === 0
                  ? "No serial devices detected — plug in the flight controller and press Rescan. "
                  : ""}
                Custom: <span className="font-mono">/dev/ttyUSB0,57600</span> (telemetry radio),{" "}
                <span className="font-mono">tcp:127.0.0.1:5760</span> (a simulator you started).
              </p>
            </div>
          ) : (
            <div className="glass flex flex-col gap-3.5 rounded-2xl p-5 shadow-[0_8px_24px_rgba(31,36,90,0.14)]">
              <p className="m-0 text-[12.5px] leading-relaxed text-[#565D70] dark:text-[#9198A8]">
                The backend launches a simulated vehicle for you automatically — nothing else to start by hand.
              </p>
              <button
                type="button"
                onClick={() => setShowSitlSettings((v) => !v)}
                className="flex w-fit items-center gap-1.5 text-[12.5px] font-semibold text-accent-1"
              >
                {showSitlSettings ? "Hide" : "Show"} simulation settings
                <svg
                  width="11"
                  height="11"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  className={`transition-transform ${showSitlSettings ? "rotate-180" : ""}`}
                >
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </button>
              {showSitlSettings && (
                <div className="flex flex-col gap-3">
                  <div className="grid grid-cols-2 gap-3">
                    <label className="flex flex-col gap-1.5 text-[11.5px] font-medium text-[#565D70] dark:text-[#9198A8]">
                      Vehicle
                      <select
                        value={sitlSettings.vehicle}
                        onChange={(e) => setSitlSettings((s) => ({ ...s, vehicle: e.target.value as "copter" | "plane" }))}
                        className="rounded-lg border border-[#C3C9D6] bg-white px-2.5 py-2 font-mono text-[13px] text-[#1F2430] outline-none dark:border-white/10 dark:bg-white/5 dark:text-[#E8EAED]"
                      >
                        <option value="copter">Copter</option>
                        <option value="plane">Plane</option>
                      </select>
                    </label>
                    <label className="flex flex-col gap-1.5 text-[11.5px] font-medium text-[#565D70] dark:text-[#9198A8]">
                      Frame (optional override)
                      <input
                        value={sitlSettings.frame ?? ""}
                        placeholder={sitlSettings.vehicle === "copter" ? "quad" : "plane"}
                        onChange={(e) => setSitlSettings((s) => ({ ...s, frame: e.target.value || null }))}
                        className="rounded-lg border border-[#C3C9D6] bg-white px-2.5 py-2 font-mono text-[13px] text-[#1F2430] outline-none dark:border-white/10 dark:bg-white/5 dark:text-[#E8EAED]"
                      />
                    </label>
                    <label className="flex flex-col gap-1.5 text-[11.5px] font-medium text-[#565D70] dark:text-[#9198A8]">
                      Instance
                      <input
                        type="number"
                        min={0}
                        value={sitlSettings.instance}
                        onChange={(e) => setSitlSettings((s) => ({ ...s, instance: Number(e.target.value) }))}
                        className="rounded-lg border border-[#C3C9D6] bg-white px-2.5 py-2 font-mono text-[13px] text-[#1F2430] outline-none dark:border-white/10 dark:bg-white/5 dark:text-[#E8EAED]"
                      />
                    </label>
                    <label className="flex flex-col gap-1.5 text-[11.5px] font-medium text-[#565D70] dark:text-[#9198A8]">
                      Speedup
                      <input
                        type="number"
                        min={1}
                        value={sitlSettings.speedup}
                        onChange={(e) => setSitlSettings((s) => ({ ...s, speedup: Number(e.target.value) }))}
                        className="rounded-lg border border-[#C3C9D6] bg-white px-2.5 py-2 font-mono text-[13px] text-[#1F2430] outline-none dark:border-white/10 dark:bg-white/5 dark:text-[#E8EAED]"
                      />
                    </label>
                  </div>
                  <label className="flex items-center gap-2 text-[12.5px] text-[#4B5164] dark:text-[#B7BFCA]">
                    <input
                      type="checkbox"
                      checked={sitlSettings.wipe_eeprom}
                      onChange={(e) => setSitlSettings((s) => ({ ...s, wipe_eeprom: e.target.checked }))}
                      className="accent-accent-1"
                    />
                    Wipe EEPROM on start (fresh parameters)
                  </label>
                </div>
              )}
            </div>
          )}

          <button
            type="submit"
            disabled={connecting}
            className="rounded-[13px] bg-gradient-to-br from-accent-1 to-accent-2 py-3.5 text-[14px] font-bold text-white shadow-[0_8px_22px_rgba(99,102,241,0.3)] transition-transform hover:-translate-y-px disabled:opacity-60"
          >
            {connecting
              ? mode === "simulation"
                ? "Starting simulation..."
                : "Connecting..."
              : mode === "simulation"
                ? "Launch Simulation & Connect"
                : "Connect"}
          </button>
        </form>
        {connecting && connectProgress && <ConnectProgress {...connectProgress} />}
        {error && <p className="text-sm text-danger">{error}</p>}
      </div>

      <div className="flex justify-center gap-5 px-7 py-3">
        {["Validated writes only", "Human-confirmed changes", "Full audit log"].map((label) => (
          <span key={label} className="flex items-center gap-1.5 text-[11px] text-[#5B6275] dark:text-[#9198A8]">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#6366F1" strokeWidth="3">
              <path d="M20 6L9 17l-5-5" />
            </svg>
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

function ConnectedApp() {
  const {
    session,
    restoring,
    error,
    clearError,
    pendingProposal,
    pendingProcedure,
    resolvingProposal,
    confirmProposal,
    rejectProposal,
    reviseProposal,
    startCompassCalibration,
    confirmProcedure,
    rejectProcedure,
  } = useSession();
  const [showSummary, setShowSummary] = useState(false);
  const [showReboot, setShowReboot] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  if (restoring) return null;

  if (!session) return <ConnectScreen onOpenHistory={() => setShowHistory(true)} />;

  return (
    <div className="bg-app flex h-full flex-col text-[#1F2430] dark:text-[#E8EAED]">
      {showReboot && <RebootDialog onClose={() => setShowReboot(false)} />}
      <header className="glass flex flex-shrink-0 items-center justify-between px-6 py-3.5 shadow-[0_1px_0_rgba(31,36,48,0.05)]">
        <div className="flex items-center gap-3.5">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-success shadow-[0_0_0_4px_rgba(34,197,139,0.15)]" />
            <span className="font-mono text-[13px] font-bold">
              {session.frame_label ? `${session.frame_label} · ` : ""}
              {session.vehicle_type} · {session.firmware_version}
            </span>
            {session.board_label && (
              <span className="rounded-full bg-[#EEF0F6] px-2.5 py-1 text-[11px] font-semibold text-[#4B5160] dark:bg-white/10 dark:text-[#C9CED8]">
                on {session.board_label}
              </span>
            )}
          </div>
          {session.read_only && (
            <span className="rounded-full bg-[#FFF1DE] px-2.5 py-1 text-[11px] font-semibold text-warn-text dark:bg-warn-text/15">
              read-only: no metadata for this firmware
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button
            onClick={() => setShowReboot(true)}
            disabled={pendingProposal !== null}
            title={pendingProposal ? "Resolve the pending proposal first" : "Reboot the flight controller"}
            className="flex items-center gap-1.5 rounded-[9px] border border-black/[0.12] bg-white px-3 py-2 text-[12.5px] text-[#4B5164] hover:bg-[#F5F6FA] disabled:opacity-50 dark:border-white/10 dark:bg-white/5 dark:text-[#B7BFCA] dark:hover:bg-white/10"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12a9 9 0 1 1-3-6.7M21 3v6h-6" />
            </svg>
            Reboot
          </button>
          <button
            onClick={() => void startCompassCalibration()}
            className="flex items-center gap-1.5 rounded-[9px] border border-black/[0.12] bg-white px-3 py-2 text-[12.5px] text-[#4B5164] hover:bg-[#F5F6FA] dark:border-white/10 dark:bg-white/5 dark:text-[#B7BFCA] dark:hover:bg-white/10"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
            </svg>
            Compass cal
          </button>
          <button
            onClick={() => setShowSummary((v) => !v)}
            className="flex items-center gap-1.5 rounded-[9px] border border-black/[0.12] bg-white px-3 py-2 text-[12.5px] text-[#4B5164] hover:bg-[#F5F6FA] dark:border-white/10 dark:bg-white/5 dark:text-[#B7BFCA] dark:hover:bg-white/10"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M9 17H4v-2a4 4 0 014-4h1M20 17h-5m0 0v-4a3 3 0 00-3-3H9" />
              <circle cx="9" cy="7" r="3" />
            </svg>
            {showSummary ? "Hide" : "Show"} summary
          </button>
          <button
            onClick={() => setShowHistory(true)}
            className="flex items-center gap-1.5 rounded-[9px] border border-accent-1/20 bg-gradient-to-br from-[#EEF0FF] to-[#F5EDFF] px-3 py-2 text-[12.5px] font-semibold text-[#5457C7] dark:border-accent-1/30 dark:from-accent-1/15 dark:to-accent-2/10 dark:text-[#B4B8FF]"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            History
          </button>
        </div>
      </header>

      <main className="flex min-h-0 flex-grow">
        <ChatPane />
        <TelemetryPanel sessionId={session.session_id} />
      </main>

      {showSummary && <SessionSummary sessionId={session.session_id} />}

      {showHistory && <SessionHistoryPanel onClose={() => setShowHistory(false)} />}

      {}
      {error && (
        <div className="fixed inset-x-0 bottom-6 z-[200] flex justify-center px-6">
          <div className="glass flex max-w-xl items-start gap-3 rounded-2xl border border-danger/25 bg-danger/10 px-4 py-3 shadow-[0_12px_32px_rgba(31,36,90,0.18)]">
            <p className="m-0 flex-1 text-[13px] leading-relaxed text-danger">{error}</p>
            <button
              type="button"
              onClick={clearError}
              aria-label="Dismiss error"
              className="flex-shrink-0 text-[13px] font-semibold text-danger/80 hover:text-danger"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {pendingProposal && (
        <ConfirmationModal
          proposal={pendingProposal}
          resolving={resolvingProposal}
          onConfirm={() => void confirmProposal()}
          onReject={(reason) => void rejectProposal(reason)}
          onRevise={(newValue) => void reviseProposal(newValue)}
        />
      )}

      {pendingProcedure && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-6" role="dialog" aria-modal="true">
          <div className="glass w-full max-w-lg rounded-2xl p-6 shadow-[0_30px_70px_rgba(31,36,90,0.25)]">
            <h3 className="m-0 mb-3 text-[15px] font-semibold">{pendingProcedure.title}</h3>
            <ol className="m-0 mb-4 flex flex-col gap-1.5 pl-5 text-[13.5px]">
              {pendingProcedure.steps.map((step, i) => (
                <li key={i}>
                  {step.description} {!step.manual && <em className="text-[#565D70] dark:text-[#9198A8]">(automatable)</em>}
                </li>
              ))}
            </ol>
            <div className="flex gap-2.5">
              <button
                onClick={() => void confirmProcedure()}
                className="rounded-xl bg-gradient-to-br from-accent-1 to-accent-2 px-4 py-2.5 text-[13.5px] font-semibold text-white"
              >
                Confirm
              </button>
              <button
                onClick={() => void rejectProcedure()}
                className="rounded-xl border border-black/20 bg-white px-4 py-2.5 text-[13.5px] font-semibold text-[#4B5164] dark:border-white/10 dark:bg-white/5 dark:text-[#B7BFCA]"
              >
                Reject
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <SessionProvider>
        <ConnectedApp />
      </SessionProvider>
    </ThemeProvider>
  );
}
