# Recovery note

`1_10` and `1_16` failed the initial pass. They were retried with `max_chunks=8` and `validation_retries=3`, passed the quality gate, and their successful records and packet JSON files were merged into this run. The original failed records remain in `recovery_attempts.jsonl`; summary token, latency, and cost totals include both the initial and recovery attempts.
