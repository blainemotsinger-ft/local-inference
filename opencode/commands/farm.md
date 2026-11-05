---
description: Farm a bounded task to the local worker, then verify it
agent: build
---

Use the `local-worker` subagent for this task:

$ARGUMENTS

Then verify its work as the lead:

1. Read the diff and every changed file.
2. Run the named tests or build, and quote the output.
3. If it passes, report what changed and stop.
4. If it fails, report the exact failure and either fix it yourself or re-prompt the worker once with that failure.

Do not commit or push without asking.
