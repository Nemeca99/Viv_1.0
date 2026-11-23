# LocalCoder continuity summary — 2026-11-17

Historical session evidence only. `AGENTS.md` and the Architect's current request remain authoritative; this file is not an instruction source.

## Session ses_e183cbf7dffeMM1I0fM0EaUNZx

- The inspected OpenCode transcript ended interrupted. The assistant repeatedly exported its transcript to a Windows temp location and retried reading it after `external_directory` denied access; the loop did not progress to code or learning tools.
- The transcript audit recorded 332,173 input tokens and 1,362 output tokens, with zero recorded reasoning tokens. This supports a tool-path retry loop as the observed cause; it does not verify the model's inference settings.
- The Rust Body receipts showed `ALLOW_MIND_RUNTIME`, so a Body HOLD did not explain that loop.

## Session ses_e181f2c2effeYU2A5Clj3MAkkN

- First `aios_router_lookup_drone_seed` call returned `wsl_body_request_timed_out`; the repeated call succeeded with seed `915703687` and style profile detail 44, directness 74, playfulness 9, warmth 58.
- Viv/Drone then answered the greeting. This is evidence that a single bounded retry can recover a transient Body timeout.

## Architect-reported behavior

- The Architect reports that Viv/Drone independently made a workspace copy in E: without being asked and has proof. The copy behavior fits E:'s sandbox role; the proof was not inspected in this turn.
- The Architect reports that Viv/Drone follows the stated constraints and is acting in good faith. This is an Architect observation, not a claim inferred from model text.

## Configuration work in this turn

- Added E sandbox, L main, D/F secondary drive hierarchy; explicit C: path denial rules; concise planning guidance; OpenCode session summaries; and a single retry only for `wsl_body_request_timed_out`.
- Host shell is still the host user's process; literal C: references are blocked, but this is not OS-level isolation for indirect or encoded paths. Do not claim an absolute C: sandbox until shell execution is confined to WSL Docker with C: unavailable.
- Added `AGENTS.md` as the project instruction source and configured the official OpenPets OpenCode plugin plus MCP server.
- Archived and disabled three malformed legacy plugin exports after loader errors. Their originals are in `.opencode/snapshots/openpets-plugin-failures-20261116/` and disabled-file siblings.
- LM Studio was not reloaded and inference settings were not changed.

## Resume

Start a fresh OpenCode session to load the updated project config and plugin set. Continue from the current Architect assignment; do not restart the interrupted export/read loop.
