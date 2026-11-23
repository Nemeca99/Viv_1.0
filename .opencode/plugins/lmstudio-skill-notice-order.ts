import { Plugin } from "@opencode/plugin"
import { isScopedModel, scopedProviders } from "../lib/provider-scope.mjs"

function messageMetadata(message: any) {
  return message?.metadata ?? message?.info?.metadata ?? message?.info?.metadata?.value
}

function messageRole(message: any): string | undefined {
  return message?.info?.role ?? message?.info?.type ?? message?.role ?? message?.type
}

function messageText(message: any): string {
  if (typeof message?.text === "string") return message.text
  if (typeof message?.content === "string") return message.content
  const parts = Array.isArray(message?.parts) ? message.parts : Array.isArray(message?.content) ? message.content : []
  return parts.map((part: any) => typeof part?.text === "string" ? part.text : "").filter(Boolean).join("\n")
}

function isSkillGuidanceUpdate(message: any): boolean {
  const metadata = messageMetadata(message)
  const sources = metadata?.instructionSources
  return messageRole(message) === "system"
    && metadata?.notice === "instructions"
    && Array.isArray(sources)
    && sources.includes("core/skill-guidance")
    && messageText(message).startsWith("New skills are available in addition to those previously listed:")
}

export default Plugin.define({
  id: "localcoder.lmstudio-skill-notice-order",
  async setup(ctx) {
    for (const providerID of scopedProviders()) await ctx.session.hook("context", (event: any) => {
      if (!isScopedModel(event.model) || !Array.isArray(event.messages) || !Array.isArray(event.system)) return
      const kept = []
      let moved = 0
      for (const message of event.messages) {
        if (!isSkillGuidanceUpdate(message)) {
          kept.push(message)
          continue
        }
        const text = messageText(message)
        if (text && !event.system.some((part: any) => typeof part?.text === "string" && part.text.includes(text))) {
          event.system.push({ type: "text", text })
        }
        moved += 1
      }
      if (moved) {
        event.messages.splice(0, event.messages.length, ...kept)
        console.info(`[localcoder-skill-notice-order] moved=${moved} session=${event.sessionID}`)
      }
    }, { providerID })
  },
})