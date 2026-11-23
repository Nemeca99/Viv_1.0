import { readFileSync } from "node:fs"

// One authoritative answer to "which providers receive the Viv hooks?"
//
// The hooks were previously locked to the literal "lmstudio" in twelve plugin
// registrations plus two in continuity.mjs. Moving the Drone model to another
// provider therefore disarmed every gate silently: the filter never matched,
// and nothing reported the absence.
//
// Behaviour is deliberately fail-closed and loud. If this module cannot produce
// a valid scope, every caller throws at load instead of registering a hook that
// will never fire. A visible startup failure is preferable to an invisible
// reduction in enforcement.

const CONFIG = "L:/LocalCoder/.opencode/provider-scope.json"

let cached

export function scopedProviders() {
  if (cached) return cached
  const enabled = readConfig()?.enabled
  if (!Array.isArray(enabled) || enabled.length === 0)
    throw new Error(
      `Provider scope ${CONFIG} must define a non-empty "enabled" array. ` +
        `An empty scope would silently disarm every Viv hook.`,
    )
  const ids = enabled.map((id) => (typeof id === "string" ? id.trim() : ""))
  if (ids.some((id) => id.length === 0))
    throw new Error(`Provider scope ${CONFIG} "enabled" must contain only non-empty strings.`)
  cached = Object.freeze([...new Set(ids)])
  return cached
}

export function isScoped(providerID) {
  return scopedProviders().includes(providerID)
}

// Inline guards in the plugins read `event.model?.providerID` and previously
// compared it against the literal "lmstudio". A hook can also arrive with no
// model attached; that case is never treated as a scoped provider.
export function isScopedModel(model) {
  return isScoped(model?.providerID)
}

function readConfig() {
  let raw
  try {
    raw = readFileSync(CONFIG, "utf8")
  } catch (error) {
    throw new Error(`Provider scope ${CONFIG} is unreadable: ${error.message}`)
  }
  try {
    return JSON.parse(raw)
  } catch (error) {
    throw new Error(`Provider scope ${CONFIG} is not valid JSON: ${error.message}`)
  }
}
