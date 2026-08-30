# Connection pool exhaustion

Confirm saturation in pool utilization metrics and acquisition timeout logs. Correlate the start
with a deploy. Prefer rollback for a clear regression; otherwise verify database headroom before
increasing the pool. Never restart the database as a first response.

