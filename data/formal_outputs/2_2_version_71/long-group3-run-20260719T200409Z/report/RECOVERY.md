# Recovery note

`3_10` initially failed because a Claim referenced Results outside its StudyUnit. It passed after a targeted retry with eight selected chunks and three validation retries; the successful packet and report record were merged into this run. The original failure remains in `recovery_attempts.jsonl`. Two failed validation calls did not retain usage telemetry, so `estimated_cost_usd` remains `null`; `known_estimated_cost_usd` is a lower bound from metered calls only.
