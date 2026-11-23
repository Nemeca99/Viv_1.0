# OpenCode compaction and memory continuity — 2026-11-18

Architect reported LM Studio context raised from 32k to 48k. Root OpenCode config was stale at 32,768 for lmstudio/omnicoder-2-9b, with buffer: 2048, keep.tokens: 1024, and agent caps of build=50, drone_build=50, drone_read=6.

Updated root opencode.json: model context 49,152; compaction buffer 10%; retained recent tail 10,000; removed configured step ceilings from build, drone_build, and drone_read. Added permanent STM/LTM continuity rules to root AGENTS.md and initialized .opencode/STM.md.

Existing project integrations retained: aios_router and openpets MCP entries, bridge memory read/append tools, and JSON action receipts. A general SQL LTM search/log/rollover API was not confirmed; no new server or database writes were made. No tests or model runs were performed. Snapshots are in .opencode/snapshots/ with the before-context-memory-tune prefix.
