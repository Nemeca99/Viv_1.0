import { Plugin } from "@opencode/plugin"
import { isScopedModel, scopedProviders } from "../lib/provider-scope.mjs"

const PLAN_MARKER = "[DRONE PLAN ONLY | NO TOOLS]"
const planOnlySessions = new Set<string>()

function roleOf(message: any): string {
  return String(message?.info?.role ?? message?.info?.type ?? message?.role ?? message?.type ?? "")
}

function textOf(message: any): string {
  if (typeof message?.text === "string") return message.text
  if (typeof message?.content === "string") return message.content
  const parts = Array.isArray(message?.parts) ? message.parts : Array.isArray(message?.content) ? message.content : []
  return parts.map((part: any) => typeof part?.text === "string" ? part.text : "").filter(Boolean).join("\n")
}

function latestUserText(messages: any[]): string {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (message?.type === "synthetic" || message?.info?.type === "synthetic") continue
    const text = textOf(message)
    const trimmed = text.trimStart()
    if (trimmed.startsWith("Instructions from: ") || trimmed.startsWith("<system-reminder>")) continue
    if (roleOf(message) === "user") return text
  }
  return ""
}

export default Plugin.define({
  id: "localcoder.drone-plan-only",
  async setup(ctx) {
    for (const providerID of scopedProviders()) await ctx.session.hook("context", (event: any) => {
      const sessionID = String(event.sessionID ?? "")
      if (!sessionID || !isScopedModel(event.model)) return
      const planOnly = latestUserText(Array.isArray(event.messages) ? event.messages : []).includes(PLAN_MARKER)
      if (!planOnly) {
        planOnlySessions.delete(sessionID)
        return
      }
      planOnlySessions.add(sessionID)
      for (const name of Object.keys(event.tools ?? {})) delete event.tools[name]
      while (planOnlySessions.size > 128) planOnlySessions.delete(planOnlySessions.values().next().value!)
      console.info(`[localcoder-drone-plan-only] tools_hidden session=${sessionID}`)
    }, { providerID })

    await ctx.tool.hook("execute.before", (event: any) => {
      const sessionID = String(event.sessionID ?? "")
      if (planOnlySessions.has(sessionID)) {
        throw new Error("Drone plan-only turn: tool execution is denied until the plan is reviewed and a separate Architect assignment is dispatched.")
      }
    })
  },
})