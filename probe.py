#!/usr/bin/env python3
"""Probe the public AskMyChurch surfaces and update status.json / history.json.

Runs from GitHub Actions (see .github/workflows/monitor.yml) about every five
minutes — deliberately OFF Cloudflare, so the monitor stays up when the thing
it watches is down. Alerts via Pushover on every up->down and down->up
transition (dedupe is the transition itself; a sustained outage pages once).

History is a rolling window: samples older than 30 days are pruned, so the
file stays small enough to serve as the status page's data.
"""
import json, os, time, urllib.parse, urllib.request

TARGETS = [
    {"name": "Assistant platform", "url": "https://askmy.church/health"},
    {"name": "Pricing", "url": "https://askmy.church/pricing"},
    {"name": "Marketing site", "url": "https://visiongenesisai.com/"},
]
WINDOW_DAYS = 30


def probe(url):
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "vg-status-monitor"})
        code = urllib.request.urlopen(req, timeout=15).status
        return {"ok": 200 <= code < 300, "code": code, "ms": int((time.time() - start) * 1000)}
    except Exception as e:  # noqa: BLE001 — a failed probe IS the signal
        return {"ok": False, "code": 0, "ms": int((time.time() - start) * 1000), "err": type(e).__name__}


def pushover(title, message):
    tok, usr = os.environ.get("PUSHOVER_TOKEN"), os.environ.get("PUSHOVER_USER")
    if not (tok and usr):
        return
    try:
        data = urllib.parse.urlencode({"token": tok, "user": usr, "priority": "1",
                                       "title": title, "message": message}).encode()
        urllib.request.urlopen("https://api.pushover.net/1/messages.json", data=data, timeout=15)
    except Exception:  # noqa: BLE001 — alerting must not break monitoring
        pass



now = int(time.time())
prev = {}
if os.path.exists("status.json"):
    try:
        prev = {t["name"]: t["ok"] for t in json.load(open("status.json"))["targets"]}
    except Exception:  # noqa: BLE001
        prev = {}

results = []
for t in TARGETS:
    r = probe(t["url"])
    results.append({"name": t["name"], "url": t["url"], **r})
    was = prev.get(t["name"])
    if was is True and not r["ok"]:
        pushover(f"DOWN: {t['name']}", f"{t['url']} -> {r.get('err') or r['code']}. status: visiongenesis.github.io/vg-status")
    if was is False and r["ok"]:
        pushover(f"recovered: {t['name']}", f"{t['url']} answering again ({r['ms']}ms).")

json.dump({"updated": now, "targets": results}, open("status.json", "w"), indent=1)

history = []
if os.path.exists("history.json"):
    try:
        history = json.load(open("history.json"))
    except Exception:  # noqa: BLE001
        history = []
history.append({"t": now, "s": [1 if r["ok"] else 0 for r in results], "ms": [r["ms"] for r in results]})
cutoff = now - WINDOW_DAYS * 86400
history = [h for h in history if h["t"] >= cutoff]
json.dump(history, open("history.json", "w"))
print(f"probe: " + ", ".join(f"{r['name']}={'up' if r['ok'] else 'DOWN'} {r['ms']}ms" for r in results))
