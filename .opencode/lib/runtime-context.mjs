const brandedIntro = /^\s*You are (?:opencode\b|an AI agent running in OpenCode\b)[^\r\n]*(?:\r?\n|$)/i
const contextIntro = /^\s*<viv_runtime_context>[\s\S]*?<\/viv_runtime_context>/

export function runtimeSystem(parts, context) {
  let present = false
  const normalized = parts.map(part => {
    if (typeof part.text !== 'string') return part
    let text = part.text.replace(brandedIntro, 'OpenCode is the host runtime and tool transport.\n')
    if (contextIntro.test(text)) { present = true; text = text.replace(contextIntro, context) }
    return text === part.text ? part : { ...part, text }
  })
  return present ? normalized : [...normalized, { type: 'text', text: context }]
}

export function runtimeHeader(text) {
  const match = text.match(/^<viv_runtime_context>[\s\S]*?<\/viv_runtime_context>/)
  if (!match) throw new Error('Canonical runtime context header is missing')
  return match[0]
}
