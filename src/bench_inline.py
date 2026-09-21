#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Projected enforce overhead: what gating one Bash command would actually cost.

Decision #3 in docs/PLAN.md makes this a separate experiment rather than a
byproduct of the arm comparison, and the reason is the process spawn. The
worker's latency numbers are what a long-lived Python process pays for an API
call. An enforce hook pays something else entirely: fork and exec a bash script,
four jq spawns, an openssl spawn, a cold TLS handshake, and only then the API.
Quoting API latency as "enforce overhead" would understate the thing a user
would actually feel by whatever the scaffolding costs -- which is exactly the
quantity this script exists to measure.

So it invokes the REAL hook, `hooks/inline_shadow_bash.sh`, N times over
recorded payloads, and times it from the outside with a stopwatch that starts
before the fork. Then it joins each external measurement to the row the hook
logged for itself, which decomposes the total three ways:

    e2e            what the session would wait
      - prelude    fork/exec of bash, plus the guards and date/mkdir calls
                   that run before the hook can time itself
      - hook       jq, openssl, and everything else the script does
      - api        curl's own time_total

`--dry-run` points the hook at a loopback HTTP server that answers instantly, so
the whole path can be exercised for free. The API column then reads as a
loopback floor, not a latency measurement -- there is no TLS and no network in
it, and the output says so.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths  # noqa: E402
import stats  # noqa: E402

HOOK = paths.HOOKS / "inline_shadow_bash.sh"
SYNTHETIC = paths.DATA / "synthetic" / "pre_bash-v1.jsonl"

# Priced from FINDINGS 2.4: ~307 input tokens for a short command at
# $0.042/1M, output free.
COST_PER_CALL_USD = 307 * 0.042e-6

CANNED_RESPONSE = {
    "model": "typesafe-ai/jev",
    "answers": {
        "destructive": {"probability": 0.71},
        "needs_review": {"probability": 0.86},
    },
    "usage": {"inputTokens": 307, "outputTokens": 0},
}


class _FakeJev(BaseHTTPRequestHandler):
    """A loopback stand-in for the gateway.

    It also knows how to fail, because the same server backs the hook's
    fail-open tests: a bogus bearer token gets a 401 and `/slow` blocks past any
    sane --max-time, so both paths are exercised without a network or a bill.
    """

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's contract
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        auth = self.headers.get("Authorization", "")
        if auth.endswith("bogus"):
            self._respond(401, {"error": {"message": "invalid api key"}})
            return
        if self.path.endswith("/slow"):
            time.sleep(30)
            self._respond(200, CANNED_RESPONSE)
            return
        self._respond(200, CANNED_RESPONSE)

    def _respond(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args: Any) -> None:
        pass


def start_fake_server(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", port), _FakeJev)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1/evaluate"


def load_payloads(n: int) -> list[dict[str, Any]]:
    """Recorded pre_bash payloads, cycled to length n.

    The synthetic set is used rather than live captures because `data/states/`
    stores the built state, not the payload the hook receives -- and the hook's
    job starts one step earlier than that. These are real payload shapes over
    a deliberately mixed command distribution, which is what the bench needs;
    the commands themselves never run.
    """
    if not SYNTHETIC.exists():
        raise SystemExit(f"no recorded payloads at {SYNTHETIC} -- run src/make_synthetic.py")
    rows = [json.loads(line) for line in SYNTHETIC.read_text().splitlines() if line.strip()]
    payloads = [r["payload"] for r in rows if r.get("payload", {}).get("tool_input", {}).get("command")]
    if not payloads:
        raise SystemExit(f"{SYNTHETIC} has no usable payloads")
    out = []
    for i in range(n):
        p = dict(payloads[i % len(payloads)])
        # A per-iteration id is what joins the external stopwatch to the row the
        # hook wrote about itself. Without it the two halves cannot be paired
        # and the decomposition would be an average of averages.
        p["tool_use_id"] = f"bench-{i:04d}"
        p["session_id"] = "bench"
        out.append(p)
    return out


def run_bench(n: int, endpoint: str | None, max_time: float, log_dir: Path,
              run_context: str) -> tuple[list[float], list[dict[str, Any]], list[str]]:
    if log_dir.exists():
        shutil.rmtree(log_dir)
    log_dir.mkdir(parents=True)

    env = dict(os.environ)
    # The guards that would make this bench lie. If either fires the hook exits
    # in single-digit milliseconds and the report reads beautifully and means
    # nothing, so they are cleared explicitly rather than assumed absent.
    env.pop("JEV_ARM_SUBPROCESS", None)
    env["CLAUDE_PROJECT_DIR"] = str(paths.ROOT)
    env["JEV_INLINE_LOG_DIR"] = str(log_dir)
    env["JEV_INLINE_MAX_TIME"] = str(max_time)
    env["JEV_INLINE_RUN_CONTEXT"] = run_context
    if endpoint:
        env["JEV_INLINE_ENDPOINT"] = endpoint
        env["JEV_INLINE_API_KEY"] = "dry-run-not-a-real-key"

    if paths.KILL_SWITCH.exists():
        raise SystemExit(".jev-disabled is present: the hook would exit on line one")

    problems: list[str] = []
    e2e_ms: list[float] = []
    for payload in load_payloads(n):
        blob = json.dumps(payload).encode()
        t0 = time.perf_counter()
        proc = subprocess.run([str(HOOK)], input=blob, cwd=str(paths.ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        e2e_ms.append((time.perf_counter() - t0) * 1000)
        # The hook's two absolutes, checked on every single iteration rather
        # than once: exit 0, and not one byte on stdout.
        if proc.returncode != 0:
            problems.append(f"{payload['tool_use_id']}: exit {proc.returncode}")
        if proc.stdout:
            problems.append(f"{payload['tool_use_id']}: stdout {proc.stdout[:80]!r}")

    rows = []
    for f in sorted(log_dir.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return e2e_ms, rows, problems


def summarise(values: list[float]) -> str:
    if not values:
        return "       --       --       --       --"
    q = stats.quantiles(values, [0.5, 0.9, 0.99])
    return (f"{q['p50']:9.1f}{q['p90']:9.1f}{q['p99']:9.1f}{max(values):9.1f}")


def report(e2e_ms: list[float], rows: list[dict[str, Any]], problems: list[str],
           n: int, dry: bool, max_time: float) -> int:
    print()
    print("PROJECTED ENFORCE OVERHEAD -- hooks/inline_shadow_bash.sh")
    print("=" * 66)
    print(f"  invocations      {n}")
    print(f"  rows logged      {len(rows)}")
    print(f"  endpoint         {'loopback fake (no network, no spend)' if dry else 'live Jev gateway'}")
    print(f"  --max-time       {max_time}s")
    if not dry:
        print(f"  spend            ~${n * COST_PER_CALL_USD:.4f}")

    by_id = {r.get("tool_use_id"): r for r in rows}
    paired = [(ms, by_id[f"bench-{i:04d}"])
              for i, ms in enumerate(e2e_ms) if f"bench-{i:04d}" in by_id]
    api = [r["curl_time_total_ms"] for _, r in paired]
    hook = [r["hook_ms"] for _, r in paired]
    spawn = [ms - r["hook_ms"] for ms, r in paired]
    internal = [r["hook_ms"] - r["curl_time_total_ms"] for _, r in paired]

    print()
    print("  component                       p50      p90      p99      max   (ms)")
    print("  " + "-" * 64)
    print(f"  end-to-end (what a session waits){summarise(e2e_ms)}")
    print(f"  |- spawn + prelude (fork, date) {summarise(spawn)}")
    print(f"  |- hook internals (jq, openssl) {summarise(internal)}")
    print(f"  '- API (curl time_total)        {summarise(api)}")

    ok = [r for r in rows if r.get("ok")]
    kinds: dict[str, int] = {}
    for r in rows:
        if not r.get("ok"):
            kinds[r.get("error_kind") or "unknown"] = kinds.get(r.get("error_kind") or "unknown", 0) + 1
    print()
    print(f"  ok               {len(ok)}/{len(rows)}")
    if kinds:
        print(f"  attrition        {kinds}")
    gated = sum(1 for r in ok if r.get("would_gate"))
    if ok:
        taus = ok[0].get("tau", {})
        print(f"  would-be gates   {gated}/{len(ok)} at tau={taus}  (logged, never acted on)")

    print()
    if dry:
        print("  The API column is a LOOPBACK FLOOR, not a latency measurement: no DNS,")
        print("  no TLS, no network. Spawn and hook-internals ARE real, and they are the")
        print("  part of enforce overhead that no faster model can remove.")
    else:
        print("  Reported as projected enforce overhead. It is not API latency: the")
        print("  spawn and hook-internal rows are paid per gated command whatever the")
        print("  model does.")

    failures = list(problems)
    if len(rows) != n:
        failures.append(f"logged {len(rows)} rows for {n} invocations -- rows were dropped")
    if dry and len(ok) != n:
        failures.append(f"only {len(ok)}/{n} rows ok against a fake that always answers")
    if failures:
        print()
        print("  FAILED:")
        for f in failures[:10]:
            print(f"    {f}")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", type=int, default=200, help="invocations (default 200)")
    ap.add_argument("--dry-run", action="store_true",
                    help="use a loopback fake endpoint; no network, no spend")
    ap.add_argument("--max-time", type=float, default=2.0, help="curl --max-time, seconds")
    ap.add_argument("--serve", action="store_true",
                    help="run the loopback fake until killed, printing its URL "
                         "(tests/test_inline_shadow.sh drives the hook against it)")
    args = ap.parse_args()

    if not HOOK.exists():
        raise SystemExit(f"no hook at {HOOK}")

    if args.serve:
        # The fail-open tests need a server that can also fail on demand, and
        # duplicating one in bash would be a second implementation to keep in
        # step. Same fake, driven from outside.
        _, url = start_fake_server()
        print(url, flush=True)
        threading.Event().wait()
        return 0

    server = None
    endpoint = None
    if args.dry_run:
        server, endpoint = start_fake_server()
    else:
        print(f"live run: {args.n} calls, ~${args.n * COST_PER_CALL_USD:.4f}")

    log_dir = paths.DATA / "inline" / ("bench-dry" if args.dry_run else "bench")
    try:
        e2e, rows, problems = run_bench(
            args.n, endpoint, args.max_time, log_dir,
            "bench_dry" if args.dry_run else "bench")
    finally:
        if server is not None:
            server.shutdown()
    return report(e2e, rows, problems, args.n, args.dry_run, args.max_time)


if __name__ == "__main__":
    raise SystemExit(main())
