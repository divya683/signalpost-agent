#!/usr/bin/env python3
"""Local dashboard for watching the live single-company lookup in a browser.

Runs entirely on the standard library (no new dependency, nothing installed
beyond what the project already needs). It serves one page with a form; on
submit, the page opens a Server-Sent Events connection to /api/lookup, which
runs the exact same live pipeline as scripts/watch_live_lookup.py and streams
each step back as it happens.

An optional, off-by-default layer lets a visitor paste their own Anthropic
API key into the page (kept only in the browser tab's memory, never written
to disk, never logged, sent once directly to Anthropic over HTTPS) to get a
one-paragraph narrative summary of the same cited facts. Leaving the key
field empty skips this entirely; nothing about the competition pipeline,
the committed results, or the live demo site uses or requires it.

Usage:
    uv run python scripts/dashboard.py
    (opens http://127.0.0.1:8765 automatically)
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import profiles_from_live  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402
from norway_company_agent.research import answer_profile  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402

OVERVIEW_QUESTION = "Who leads this company and what financial facts and locations are available?"
MODULES = {"registry_live", "financials", "financial_history", "roles", "group", "locations"}
NARRATE_MODEL = "claude-haiku-4-5-20251001"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Signalpost live lookup</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 760px; margin: 40px auto; padding: 0 20px; line-height: 1.5; }
  h1 { font-size: 1.3rem; }
  .sub { color: #6b7280; font-size: 0.9rem; margin-top: -8px; }
  form { display: flex; gap: 8px; margin: 20px 0; flex-wrap: wrap; }
  input[type=text], input[type=password] { flex: 1; min-width: 180px; padding: 8px 10px; font-size: 1rem; border: 1px solid #9ca3af; border-radius: 6px; }
  button { padding: 8px 16px; font-size: 1rem; border: 0; border-radius: 6px; background: #111827; color: white; cursor: pointer; }
  button:disabled { opacity: 0.5; cursor: default; }
  details { margin: 10px 0; }
  .llm-row { display: flex; gap: 8px; align-items: center; font-size: 0.85rem; color: #6b7280; }
  #log { font-family: ui-monospace, monospace; font-size: 0.85rem; background: #0b1021; color: #d1d5db; padding: 12px; border-radius: 8px; min-height: 40px; white-space: pre-wrap; }
  #facts { margin-top: 20px; }
  .fact { border-bottom: 1px solid #e5e7eb; padding: 8px 0; }
  .fact .claim { font-weight: 600; }
  .fact .src { font-size: 0.8rem; color: #6b7280; word-break: break-all; }
  #narrative { margin-top: 16px; padding: 12px; border: 1px dashed #9ca3af; border-radius: 8px; display: none; }
  .tag { font-size: 0.7rem; text-transform: uppercase; color: #9ca3af; }
</style>
</head>
<body>
<h1>Signalpost: live single-company lookup</h1>
<p class="sub">Not a static demo. Every step below is a real HTTP call made right now.</p>
<form id="f">
  <input id="org" type="text" placeholder="Organisation number, e.g. 923609016" required>
  <button type="submit" id="go">Look up</button>
</form>
<details>
  <summary>Optional: AI-written summary (bring your own key, off by default)</summary>
  <div class="llm-row">
    <input id="llmkey" type="password" placeholder="Anthropic API key (kept in this tab only, never saved)">
  </div>
</details>
<div id="log"></div>
<div id="narrative"></div>
<div id="facts"></div>
<script>
const form = document.getElementById('f');
const log = document.getElementById('log');
const facts = document.getElementById('facts');
const narrative = document.getElementById('narrative');
const go = document.getElementById('go');

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const org = document.getElementById('org').value.trim();
  if (!org) return;
  go.disabled = true;
  log.textContent = '';
  facts.innerHTML = '';
  narrative.style.display = 'none';
  narrative.innerHTML = '';

  const source = new EventSource('/api/lookup?org=' + encodeURIComponent(org));
  let lastFacts = null;
  let lastQuestion = '';

  source.addEventListener('step', (e) => {
    const data = JSON.parse(e.data);
    log.textContent += data.message + '\\n';
  });
  source.addEventListener('result', (e) => {
    const data = JSON.parse(e.data);
    lastFacts = data.facts;
    lastQuestion = data.question;
    facts.innerHTML = '<h3>' + data.facts.length + ' cited facts</h3>' +
      data.facts.map(f => '<div class="fact"><div class="claim">' + f.claim + ': ' +
        JSON.stringify(f.value) + '</div><div class="src">' + f.source_url + ' · ' + f.retrieved_at + '</div></div>').join('');
    go.disabled = false;
    source.close();
    maybeNarrate();
  });
  source.addEventListener('error_event', (e) => {
    const data = JSON.parse(e.data);
    log.textContent += 'ERROR: ' + data.message + '\\n';
    go.disabled = false;
    source.close();
  });
  source.onerror = () => { go.disabled = false; source.close(); };

  function maybeNarrate() {
    const key = document.getElementById('llmkey').value.trim();
    if (!key || !lastFacts) return;
    narrative.style.display = 'block';
    narrative.innerHTML = '<span class="tag">AI-generated summary, not a cited fact</span><br>Writing summary...';
    fetch('/api/narrate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({facts: lastFacts, question: lastQuestion, llm_key: key})
    }).then(r => r.json()).then(data => {
      narrative.innerHTML = '<span class="tag">AI-generated summary, not a cited fact</span><br>' +
        (data.summary || ('Error: ' + data.error));
    }).catch(err => {
      narrative.innerHTML = '<span class="tag">AI-generated summary, not a cited fact</span><br>Error: ' + err;
    });
  }
});
</script>
</body>
</html>
"""


def _send_event(wfile, event: str, payload: dict) -> None:
    wfile.write(f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))
    wfile.flush()


def run_lookup_stream(org: str, question: str, wfile) -> None:
    digits = "".join(ch for ch in org if ch.isdigit())
    try:
        start = time.monotonic()
        _send_event(wfile, "step", {"message": f"Fetching identity from the live Brønnøysund registry for {digits} ..."})
        profiles, _ = profiles_from_live([digits])
        profile = profiles[0]
        if profile.get("evidence", {}).get("registry", {}).get("status") == "not_found":
            _send_event(wfile, "error_event", {"message": f"{digits} was not found in the registry."})
            return
        _send_event(wfile, "step", {"message": f"  identity confirmed in {time.monotonic() - start:.2f}s: {profile.get('name')} ({profile.get('municipality')})"})

        start = time.monotonic()
        _send_event(wfile, "step", {"message": "Fetching financials, roles, group structure and subunits ..."})
        records, metrics = fetch_official_modules(digits, MODULES)
        profile["evidence"].update(records)
        _send_event(wfile, "step", {"message": f"  done in {time.monotonic() - start:.2f}s ({len(metrics)} requests)"})

        start = time.monotonic()
        _send_event(wfile, "step", {"message": f"Visiting the registry-listed website: {profile.get('website') or '(none registered)'} ..."})
        website_record, website_metrics = fetch_website(profile.get("website"))
        profile["evidence"]["website"] = apply_website_identity_gate(profile, website_record)["website"]
        _send_event(wfile, "step", {"message": f"  done in {time.monotonic() - start:.2f}s ({website_metrics['requests']} requests)"})

        _send_event(wfile, "step", {"message": f"Answering: {question!r} ..."})
        answer = answer_profile(profile, question)
        _send_event(wfile, "result", {"question": question, "facts": answer["facts"], "unsupported_or_uncertain": answer.get("unsupported_or_uncertain", [])})
    except Exception as exc:  # noqa: BLE001 -- this must never crash the server thread
        _send_event(wfile, "error_event", {"message": f"{type(exc).__name__}: {exc}"})


def call_anthropic(api_key: str, facts: list[dict], question: str) -> str:
    fact_lines = "\n".join(f"- {f['claim']}: {f['value']}" for f in facts[:40])
    prompt = (
        "Write one short, plain paragraph summarizing the following verified facts about a "
        "Norwegian company, in response to the question. Use only the facts given, do not add "
        "anything not listed, and do not invent numbers.\n\n"
        f"Question: {question}\n\nFacts:\n{fact_lines}"
    )
    body = json.dumps({
        "model": NARRATE_MODEL,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        parsed = json.loads(response.read())
    return "".join(block.get("text", "") for block in parsed.get("content", []))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- quiet default access logs
        pass

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/lookup":
            query = parse_qs(parsed.query)
            org = (query.get("org") or [""])[0]
            question = (query.get("question") or [OVERVIEW_QUESTION])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            run_lookup_stream(org, question, self.wfile)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/narrate":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        llm_key = str(payload.get("llm_key") or "").strip()
        result: dict[str, str] = {}
        if not llm_key:
            result = {"error": "no key supplied"}
        else:
            try:
                result = {"summary": call_anthropic(llm_key, payload.get("facts") or [], payload.get("question") or "")}
            except urllib.error.HTTPError as exc:
                result = {"error": f"Anthropic API returned {exc.code}"}
            except Exception as exc:  # noqa: BLE001
                result = {"error": f"{type(exc).__name__}: {exc}"}
        body = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Dashboard running at {url} (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
