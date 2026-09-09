"""Live sync: push current network health to the website's data branch.

Pipeline:
  collector (this laptop)
      -> JSON payload of current + historical health
      -> GitHub Contents API commits web/data.json on the `data` branch
      -> the deployed site (Vercel) fetches the raw file client-side
         and re-renders itself every 60 s — no rebuilds, no deploy limits

Auth uses the same credential git already has stored (git credential fill).
`sync.anonymize` (default true) pseudonymizes SSIDs before anything leaves
this machine.
"""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

import events as events_mod
import logger as logmod

GITHUB_API = "https://api.github.com"


# ------------------------------------------------------------------
# credential access (never printed, never logged)
# ------------------------------------------------------------------

def _github_token() -> str | None:
    """Pull the stored GitHub credential from git's credential helper."""
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in (proc.stdout or "").splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


def _api(method: str, url: str, token: str, body: dict | None = None, expect_json: bool = True):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "NetPilot/2.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(text) if expect_json and text else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, None
    except Exception:
        return 0, None


# ------------------------------------------------------------------
# payload
# ------------------------------------------------------------------

def _anon_map(networks: list[dict]) -> None:
    mapping: dict[str, str] = {}
    for net in networks:
        ssid = net.get("ssid") or "?"
        if ssid not in mapping:
            mapping[ssid] = f"Network {chr(ord('A') + len(mapping))}"
        net["ssid"] = mapping[ssid]


def build_payload(
    days: int = 7,
    anonymize: bool = True,
    now_state: dict | None = None,
) -> dict:
    """Assemble the full data.json payload from logs + the latest live cycle."""
    import pandas as pd

    payload: dict = {
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "now": now_state,
        "networks": [],
        "incidents": [],
        "availability": None,
    }

    if logmod.LOG_FILE.exists():
        df = pd.read_csv(logmod.LOG_FILE)
        if len(df):
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"])
            cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
            df = df[df["timestamp"] >= cutoff].copy()
            df["hour"] = df["timestamp"].dt.hour
            score_col = "overall_score" if "overall_score" in df.columns else "net_score"

            for ssid, g in df.groupby("ssid"):
                hourly = []
                for h in range(24):
                    rows = g[g["hour"] == h]
                    hourly.append(
                        {
                            "lat": round(float(rows["net_avg_ms"].median()), 1) if len(rows) else None,
                            "loss": round(float(rows["net_loss_pct"].mean()), 1) if len(rows) else None,
                            "score": round(float(rows[score_col].mean()), 1) if len(rows) else None,
                            "n": int(len(rows)),
                        }
                    )
                payload["networks"].append(
                    {
                        "ssid": str(ssid),
                        "samples": int(len(g)),
                        "median_score": round(float(g[score_col].median()), 1) if len(g) else 0,
                        "hourly": hourly,
                    }
                )

    if events_mod.EVENTS_FILE.exists():
        try:
            ev = pd.read_csv(events_mod.EVENTS_FILE)
            ev["timestamp"] = pd.to_datetime(ev["timestamp"], errors="coerce")
            ev = ev.dropna(subset=["timestamp"])
            keep = {"OUTAGE", "WIFI_DOWN", "DNS_FAIL", "AP_ROAM", "NETWORK_CHANGE"}
            ev = ev[ev["type"].isin(keep)]
            payload["incidents"] = [
                {
                    "when": row["timestamp"].strftime("%d %b %H:%M"),
                    "type": str(row["type"]),
                    "detail": str(row["detail"]),
                }
                for _, row in ev.sort_values("timestamp", ascending=False).head(15).iterrows()
            ]
        except Exception:
            pass

    if anonymize:
        _anon_map(payload["networks"])
        if payload.get("now"):
            payload["now"]["ssid"] = "current network"

    return payload


# ------------------------------------------------------------------
# push
# ------------------------------------------------------------------

def ensure_branch(token: str, repo: str, branch: str) -> bool:
    """Create the data branch off main if it doesn't exist yet."""
    status, ref = _api("GET", f"{GITHUB_API}/repos/{repo}/git/ref/heads/{branch}", token)
    if status == 200:
        return True
    status, main_ref = _api("GET", f"{GITHUB_API}/repos/{repo}/git/ref/heads/main", token)
    if status != 200:
        return False
    status, _ = _api(
        "POST",
        f"{GITHUB_API}/repos/{repo}/git/refs",
        token,
        {"ref": f"refs/heads/{branch}", "sha": main_ref["object"]["sha"]},
    )
    return status in (200, 201)


def push_payload(payload: dict, repo: str, branch: str, path: str) -> tuple[bool, str]:
    """Commit the payload JSON to the data branch. Returns (ok, message)."""
    token = _github_token()
    if not token:
        return False, "no GitHub credential available (git credential fill)"

    if not ensure_branch(token, repo, branch):
        return False, f"could not find/create branch '{branch}'"

    status, existing = _api("GET", f"{GITHUB_API}/repos/{repo}/contents/{path}?ref={branch}", token)
    sha = existing.get("sha") if status == 200 else None

    content = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    ).decode("ascii")

    body = {
        "message": f"live update {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": content,
        "branch": branch,
    }
    if sha:
        body["sha"] = sha

    status, resp = _api("PUT", f"{GITHUB_API}/repos/{repo}/contents/{path}", token, body)
    if status in (200, 201):
        return True, f"pushed to {repo}:{branch}/{path}"
    return False, f"push failed (HTTP {status}: {json.dumps(resp)[:120] if resp else 'no body'})"


def sync_once(cfg_sync: dict, now_state: dict | None = None) -> tuple[bool, str]:
    payload = build_payload(
        days=7,
        anonymize=cfg_sync.get("anonymize", True),
        now_state=now_state,
    )
    return push_payload(
        payload,
        cfg_sync.get("repo", "Sainath-Reddy7/netpilot"),
        cfg_sync.get("branch", "data"),
        cfg_sync.get("path", "web/data.json"),
    )


def raw_data_url(cfg_sync: dict) -> str:
    return (
        f"https://raw.githubusercontent.com/{cfg_sync.get('repo', 'Sainath-Reddy7/netpilot')}"
        f"/{cfg_sync.get('branch', 'data')}/{cfg_sync.get('path', 'web/data.json')}"
    )
