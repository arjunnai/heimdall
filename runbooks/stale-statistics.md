# Stale PostgreSQL statistics

Large divergence between estimated and actual row counts can produce a poor plan. Inspect
`pg_stat_user_tables` and last analyze times before proposing ANALYZE through an approved path.

