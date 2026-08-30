# Missing index and sequential scans

Use `EXPLAIN (FORMAT JSON)` and inspect existing indexes. A sequential scan with many examined
rows and a selective predicate can justify `CREATE INDEX CONCURRENTLY`. If the same index already
exists, take no action.

