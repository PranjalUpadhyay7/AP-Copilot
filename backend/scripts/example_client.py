#!/usr/bin/env python3
"""Minimal standalone API client."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"


def _request(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
    url = BASE_URL + path
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"{method} {path} -> HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        raise


def main() -> None:
    print("Starting session...")
    session = _request("POST", "/session/start", body={"connection_string": "tcp:127.0.0.1:5760"})
    session_id = session["session_id"]
    print(f"  session_id={session_id} vehicle={session['vehicle_type']} fw={session['firmware_version']} "
          f"read_only={session['read_only']}")

    print("Starting compass calibration procedure...")
    procedure = _request("POST", "/procedures/compass-calibration/start", params={"session_id": session_id})
    print(f"  procedure_id={procedure['procedure_id']} steps={len(procedure['steps'])}")
    for step in procedure["steps"]:
        kind = "automatable" if not step["manual"] else "manual"
        print(f"    [{kind}] {step['description']}")

    print("Confirming procedure (triggers the automatable step against the real vehicle)...")
    decision = _request(
        "POST", f"/procedures/{procedure['procedure_id']}/confirm", body={"session_id": session_id},
    )
    print(f"  outcome={decision['outcome']} detail={decision['detail']}")

    print("Fetching session summary...")
    summary = _request("GET", "/session/summary", params={"session_id": session_id})
    print(f"  applied={summary['applied_count']} rejected={summary['rejected_count']} "
          f"pending={summary['pending_count']}")

    print("Fetching safety snapshot...")
    snapshot = _request("GET", "/safety-snapshot", params={"session_id": session_id})
    print(snapshot["text"])

    print("Ending session...")
    _request("POST", "/session/end", params={"session_id": session_id})
    print("Done.")


if __name__ == "__main__":
    main()
