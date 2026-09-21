# Diagram plan

Six diagrams for `DRAFT-writeup.md`. All are plain ASCII inside fenced code
blocks, so they render in a GitHub README with no image pipeline and stay
readable on a phone (kept under about 45 characters wide).

Each entry has the diagram, a caption that stands alone, and a note on what a
designer would need to make a real graphic of it.

---

## 1. Where the decision happens

```
  YOU
   │
   ▼
  main session ─────────────▶ reply to you
   │
   │  "go search the repo for X"
   ▼
  ┌─────────────────────────┐
  │  HOOK: pick the model   │◀── 3-row table
  └─────────────────────────┘
   │
   ▼
  subagent runs in background
   │
   └──▶ summary returns to main session
```

**Caption:** The tool is one script in the gap between "delegate this" and
"start the helper". It picks which model the helper uses, then gets out of the
way.

**Designer note:** The one idea to carry is that the hook sits on a single
narrow edge of the graph, not across the whole session. Give the main session and the
subagent distinct shapes, and draw the hook as a small gate on the arrow
between them, visually much smaller than either. The dashed input from the
table should read as "a file a human wrote", not as a service call. Nothing
here is a network request.

---

## 2. Why per-call checking loses and per-delegation routing wins

```
PER TOOL CALL  -- rejected
   call ─▶[check]─▶ run
            ▲          +337 tokens
            │          +557 ms
      every single time, and it
      removes nothing

PER DELEGATION -- shipped
   spawn ─▶[pick tier]─▶ 38 requests
             once          run at the
                           chosen price
   decision cost $0.000014
   saved per downgraded turn $0.0520
```

**Caption:** Checking every tool call adds cost and removes none; choosing a
model once per delegated task spreads one cheap decision over a median of 38
requests.

**Designer note:** The contrast is frequency, so let repetition carry it: a
long chain of many small gates on top, a single gate followed by a long
undifferentiated run below. Do not draw 3,674x as a bar. The repo forbids
compounding it with the 38, and a bar invites exactly that. Keep both numbers
as labels. Sources: `FINDINGS.md` Part 4c and `SPEC.md` section 10.

---

## 3. The 530x gap

```
  how long a delegated task takes
  ████████████████████████ 794.6 s

  how long you actually wait
  ▏ 1.5 s

  the work runs in the background,
  so making it faster changes
  nothing you can feel
```

**Caption:** The median delegated task runs for 794.6 seconds. The median time
a human is blocked on it is 1.5 seconds, which is why this tool makes no speed
claim.

**Designer note:** The most counter-intuitive fact in the project, and the one
most worth a designed graphic. Resist a log axis: the point is that the second
bar is almost invisible, and a log scale destroys it. If 1.5 s is too small to
render, annotate it with a leader line rather than rescaling. The two medians
come from different denominators (33 transcripts against 30 assignments), so
do not present them as a ratio of one measurement.

---

## 4. What happens when it cannot decide

```
  Agent call arrives
    │
    ├ caller already set a model ─▶ leave alone
    ├ no rule for this type      ─▶ leave alone
    ├ breaker open               ─▶ leave alone
    ├ input unreadable           ─▶ leave alone
    │
    ├ rule exists, router errored ─▶ FRONTIER
    │                                (expensive,
    │                                 safe)
    └ rule exists, all fine       ─▶ mapped tier

  Off switch = decides nothing, writes
               nothing (still spawns)
  Uninstall   = gone
```

**Caption:** Almost every way this can fail ends in "change nothing". Only one
narrow path escalates to the expensive model, and a circuit breaker stops that
path repeating during an outage.

**Designer note:** The visual weight has to sit on "leave alone", four of six
branches. A common mistake is to draw this as "fails to frontier", which is
true of one branch only. Colour the frontier branch as caution rather than
danger, and give the breaker its own small inset: after N consecutive failures
the router stops rewriting at all. Worth a footnote in the graphic too: the
off switch is not the same as uninstall.

---

## 5. The ladder: dumb first

```
  [3] classifier
      ships only if it beats [1]
       ▲
  [2] measure on real traffic
      (this is where we are now,
       with nothing measured yet)
       ▲
  [1] static table -- SHIPPED
       ▲
  [0] do nothing -- the control
      every layer is measured against
```

**Caption:** Five independent sources find learned routers often fail to beat
a trivial rule, so the trivial rule ships first and becomes the bar the
clever version has to clear.

**Designer note:** A ladder or staircase, with the current position marked at
step 2 rather than at the top. The honesty of the piece depends on the viewer
seeing that the top rung is unbuilt. Draw step 0 as a rung, not as a floor:
"do nothing" is a measured arm, not an absence. Avoid arrows that imply the
climb is inevitable.

---

## 6. How much of the bill this can reach

```
  whole bill    ████████████████████ 100%
  delegated     █████ ~24%
  v0.1 reaches  █ ~5-8%
  measured      (nothing yet)
```

**Caption:** Routing can only touch delegated work, and version 0.1's rules
cover part of that: roughly 5-8% of spend, none of it measured in production
so far.

**Designer note:** A nested-proportion graphic (three concentric areas, or a
single bar with two inset segments) reads better than four separate bars,
because the sizes are subsets rather than categories. The 5-8% is a range
derived from two cited figures (24% of spend delegated, and the static rule
reaching a fifth to a third of delegated tasks), so label it as a range and do
not average it into a point. The last row is the important one: keep the
"nothing yet" line in the graphic, not in a footnote.

---

## Notes that apply to all six

Every block is under about 45 characters wide, so it does not wrap on a phone
in a GitHub README.

If a designed version drops the source labels, the caption has to carry them
instead. No number should appear without one.

Two pairs of numbers must never be combined. 3,674x and the median 38 requests
are forbidden to multiply (`SPEC.md` section 1). The $2.88 and $5.21 per-task
figures are different windows of the same corpus and do not belong in one
chart (`SPEC.md` section 11).
