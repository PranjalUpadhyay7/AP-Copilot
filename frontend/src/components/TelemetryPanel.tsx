import { useEffect, useRef, useState } from "react";
import { telemetryWebSocketUrl } from "../api/client";
import type { TelemetryEventMessage } from "../api/types";

const RAD_TO_DEG = 180 / Math.PI;

function AttitudeIndicator({ roll, pitch }: { roll: number; pitch: number }) {
  const pitchOffsetPx = Math.max(-30, Math.min(30, pitch * 0.6));
  return (
    <div className="relative mx-auto h-[130px] w-[130px] overflow-hidden rounded-full shadow-[0_6px_20px_rgba(31,36,90,0.15),inset_0_0_0_6px_rgba(255,255,255,0.9)] dark:shadow-[0_6px_20px_rgba(0,0,0,0.4),inset_0_0_0_6px_rgba(255,255,255,0.08)]">
      <div
        className="absolute inset-[-20%]"
        style={{
          background: "linear-gradient(180deg, #6EA8E8 0%, #6EA8E8 50%, #B98A54 50%, #B98A54 100%)",
          transform: `rotate(${-roll}deg) translateY(${pitchOffsetPx}px)`,
        }}
      />
      <div className="absolute left-1/2 top-1/2 h-0.5 w-16 -translate-x-1/2 -translate-y-1/2 bg-white shadow-[0_0_3px_rgba(0,0,0,0.4)]" />
      <div className="absolute left-1/2 top-1/2 h-2.5 w-0.5 -translate-x-1/2 -translate-y-full bg-[#FF5A5A]" />
    </div>
  );
}

function Tile({ label, value, unit, accent }: { label: string; value: string; unit?: string; accent?: string }) {
  return (
    <div className="glass rounded-[14px] p-3 shadow-[0_4px_14px_rgba(31,36,90,0.14)]">
      <div className="mb-1 text-[10px] font-semibold text-[#5B6275] dark:text-[#9198A8]">{label}</div>
      <div className={`font-mono text-[19px] font-semibold ${accent ?? "text-[#1F2430] dark:text-[#E8EAED]"}`}>
        {value}
        {unit && <span className="text-[11.5px] text-[#5B6275] dark:text-[#9198A8]"> {unit}</span>}
      </div>
    </div>
  );
}

export function TelemetryPanel({ sessionId }: { sessionId: string }) {
  const [latest, setLatest] = useState<Record<string, TelemetryEventMessage>>({});
  const [connected, setConnected] = useState(false);
  const [linkUp, setLinkUp] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(telemetryWebSocketUrl(sessionId));
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      const msg: TelemetryEventMessage = JSON.parse(event.data);
      // Synthetic event from the backend: the flight-controller link went down or came back
      if (msg.field === "LINK") {
        setLinkUp(msg.value.up === true);
        return;
      }
      setLatest((prev) => ({ ...prev, [msg.field]: msg }));
    };
    return () => ws.close();
  }, [sessionId]);

  const attitude = latest.ATTITUDE?.value;
  const roll = typeof attitude?.roll === "number" ? attitude.roll * RAD_TO_DEG : null;
  const pitch = typeof attitude?.pitch === "number" ? attitude.pitch * RAD_TO_DEG : null;
  const yaw = typeof attitude?.yaw === "number" ? attitude.yaw * RAD_TO_DEG : null;

  const globalPos = latest.GLOBAL_POSITION_INT?.value;
  const altitude = typeof globalPos?.relative_alt === "number" ? globalPos.relative_alt / 1000 : null;
  const groundspeed =
    typeof globalPos?.vx === "number" && typeof globalPos?.vy === "number"
      ? Math.sqrt(globalPos.vx ** 2 + globalPos.vy ** 2) / 100
      : null;

  const sysStatus = latest.SYS_STATUS?.value;
  const battVoltage = typeof sysStatus?.voltage_battery === "number" ? sysStatus.voltage_battery / 1000 : null;

  const heartbeat = latest.HEARTBEAT?.value;
  const mode = typeof heartbeat?.custom_mode === "number" ? String(heartbeat.custom_mode) : null;

  const knownFields = new Set(["ATTITUDE", "GLOBAL_POSITION_INT", "SYS_STATUS", "HEARTBEAT"]);
  const otherFields = Object.entries(latest).filter(([field]) => !knownFields.has(field));

  return (
    <div className="flex w-[420px] flex-shrink-0 flex-col gap-3.5 overflow-y-auto p-5 pl-0">
      <div className="flex items-center justify-between px-0.5">
        <span className="text-[10.5px] font-bold uppercase tracking-wide text-[#5B6275] dark:text-[#9198A8]">Live telemetry</span>
        <span
          className={`text-[10.5px] font-medium ${
            !connected ? "text-[#5B6275] dark:text-[#9198A8]" : linkUp ? "text-success" : "text-warn-text"
          }`}
        >
          {!connected ? "connecting..." : linkUp ? "● live" : "● link lost — waiting for the vehicle"}
        </span>
      </div>

      {roll !== null && pitch !== null && (
        <div className="glass rounded-[18px] p-4 shadow-[0_4px_16px_rgba(31,36,90,0.14)]">
          <div className="mb-2.5 text-[10.5px] font-bold uppercase tracking-wide text-[#5B6275] dark:text-[#9198A8]">Attitude</div>
          <AttitudeIndicator roll={roll} pitch={pitch} />
          <div className="mt-2.5 flex justify-around">
            <div className="text-center">
              <div className="font-mono text-[12px] font-semibold text-[#1F2430] dark:text-[#E8EAED]">{roll.toFixed(0)}°</div>
              <div className="text-[9.5px] text-[#A2A8B8]">ROLL</div>
            </div>
            <div className="text-center">
              <div className="font-mono text-[12px] font-semibold text-[#1F2430] dark:text-[#E8EAED]">{pitch.toFixed(0)}°</div>
              <div className="text-[9.5px] text-[#A2A8B8]">PITCH</div>
            </div>
            {yaw !== null && (
              <div className="text-center">
                <div className="font-mono text-[12px] font-semibold text-[#1F2430] dark:text-[#E8EAED]">{yaw.toFixed(0)}°</div>
                <div className="text-[9.5px] text-[#A2A8B8]">YAW</div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2.5">
        {altitude !== null && <Tile label="ALTITUDE" value={altitude.toFixed(1)} unit="m" />}
        {groundspeed !== null && <Tile label="GROUNDSPEED" value={groundspeed.toFixed(1)} unit="m/s" />}
        {battVoltage !== null && <Tile label="BATTERY" value={battVoltage.toFixed(1)} unit="V" accent="text-success" />}
        {mode !== null && <Tile label="MODE" value={mode} />}
      </div>

      {otherFields.length > 0 && (
        <>
          <div className="px-0.5 pt-1.5 text-[10.5px] font-bold uppercase tracking-wide text-[#5B6275] dark:text-[#9198A8]">
            Other fields
          </div>
          <div className="flex flex-col gap-1.5">
            {otherFields.map(([field, msg]) => (
              <details key={field} className="glass rounded-xl px-3 py-2">
                <summary className="cursor-pointer font-mono text-[11.5px] text-[#4B5164] dark:text-[#B7BFCA]">
                  {field}
                </summary>
                <pre className="mt-1.5 max-h-40 overflow-auto text-[10.5px] text-[#565D70] dark:text-[#9198A8]">
                  {JSON.stringify(msg.value, null, 2)}
                </pre>
              </details>
            ))}
          </div>
        </>
      )}

      {Object.keys(latest).length === 0 && (
        <p className="px-0.5 text-[12.5px] text-[#5B6275] dark:text-[#9198A8]">Waiting for telemetry...</p>
      )}
    </div>
  );
}
