# Live web latency regression

When guarded synthetics show HTTP success but total-latency p95 exceeds 1,000 ms, compare TTFB with
total latency. High TTFB suggests origin or upstream work; low TTFB with high total time suggests
transfer size or network delivery. Confirm across a longer window and an independent vantage point
before remediation. For a live target, escalate the evidence and propose only—never execute a
restart or configuration change.
