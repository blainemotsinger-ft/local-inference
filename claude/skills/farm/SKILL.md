---
name: farm
description: Hand a bounded coding task to the local worker on Colibri, then verify its work
argument-hint: <task, the files involved, and the test command>
disable-model-invocation: true
allowed-tools: Bash(claude-local-worker:*)
---

Hand this task to the local worker on Colibri:

$ARGUMENTS

1. Write a brief the worker can act on alone. It cannot see this
   conversation. Name the goal, the exact files, the test or build command
   to run, and what "done" looks like.
2. Run `claude-local-worker "<brief>"` with Bash from the repository root.
   The local model is slow and the first request can take minutes, so run
   it in the background if you can and wait for it to finish; otherwise set
   the Bash timeout to its maximum. Tell the user they can watch each step
   with `tail -F ~/.local/state/claude-local-worker/latest.log`.
3. Verify the work yourself as the lead:
   1. Run `git status` and `git diff`, and read every changed file.
   2. Run the named tests or build, and quote the output.
4. If it passes, report what changed and stop.
5. If it fails, report the exact failure and either fix it yourself or run
   the worker once more with that failure in the brief. If the worker
   stopped partway, read the end of its log for the last step it took.

Do not commit or push without asking.
