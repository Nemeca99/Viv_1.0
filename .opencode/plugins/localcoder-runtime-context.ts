import { Plugin } from "@opencode/plugin"
import { readFile } from "node:fs/promises"
import { runtimeHeader, runtimeSystem } from "../lib/runtime-context.mjs"
import { scopedProviders } from "../lib/provider-scope.mjs"

export default Plugin.define({
  id: "localcoder.runtime-context",
  async setup(ctx) {
    const normalize = async (event: { system: Array<{ type: string; text?: string }> }) => {
      const context = runtimeHeader(await readFile("L:/LocalCoder/.opencode/prompts/viv-runtime-context.md", "utf8"))
      const parts = runtimeSystem(event.system, context)
      event.system.splice(0, event.system.length, ...parts)
    }
    for (const providerID of scopedProviders()) {
      await ctx.session.hook("context", normalize, { providerID })
      await ctx.session.hook("generate", normalize, { providerID })
      await ctx.session.hook("compaction", normalize, { providerID })
    }
  },
})
