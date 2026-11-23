"""Apply the Architect's normal-conversation instruction to the OpenCode loop."""
from pathlib import Path
import json
import re

ROOT = Path('L:/LocalCoder')
gate_path = ROOT / '.opencode/plugins/localcoder-drone-assignment-gate.ts'
gate = gate_path.read_text(encoding='utf-8-sig')


def between(text, start, end, replacement=''):
    begin = text.index(start)
    finish = text.index(end, begin + len(start))
    return text[:begin] + replacement + text[finish:]


def remove_function(text, name):
    match = re.search(r'^(?:async )?function ' + re.escape(name) + r'\(', text, re.M)
    assert match, name
    end = re.search(r'^(?:(?:async )?function |export default )', text[match.end():], re.M)
    assert end, name
    return text[:match.start()] + text[match.end() + end.start():]


for name in ('nextAssignedAction', 'evidenceTokensForResult', 'selfPromptEvidenceTokens',
             'completedEvidenceTokens', 'everyFactClauseGrounded', 'appendSelfPromptInstruction',
             'replaceLegacySelfPromptInstruction', 'appendSelfPromptToolInstruction',
             'appendSelfPromptRetryInstruction', 'queueSelfPromptRetry', 'retryRejectedSelfPrompt',
             'visibleSelfPrompt', 'namesOnlyExpectedTool'):
    gate = remove_function(gate, name)
for name in ('SELF_PROMPT_RETRY_MARKER', 'DRONE_SELF_PROMPT_TOOL', 'SELF_PROMPT_INSTRUCTION',
             'SELF_PROMPT_RETRY_INSTRUCTION', 'FINAL_REPORT_RETRY_INSTRUCTION', 'MAX_SELF_PROMPT_RETRIES'):
    gate = re.sub(r'^const ' + name + r' = .*\n', '', gate, flags=re.M)
gate = gate.replace('MAX_VISIBLE_CONTINUATIONS', 'MAX_AUTOMATIC_CONTINUATIONS')
gate = gate.replace('new Set([...names, DRONE_SELF_PROMPT_TOOL])', 'new Set(names)')
gate = gate.replace('  lastAcceptedSelfPrompt?: string\n', '')
gate = re.sub(r'^\s+(?:awaitingSelfPrompt: boolean|selfPromptRetryCount: number)\n', '', gate, flags=re.M)
gate = re.sub(r'\bawaitingSelfPrompt: false,\s*', '', gate)
gate = re.sub(r'\bselfPromptRetryCount: 0,\s*', '', gate)
gate = re.sub(r'^\s+(?:awaitingSelfPrompt: false,|selfPromptRetryCount: 0,)\n', '', gate, flags=re.M)
gate = gate.replace('            awaitingSelfPrompt: previous.awaitingSelfPrompt,\n', '')
gate = gate.replace('        const selfPromptCheckpoint = Boolean(currentState?.awaitingSelfPrompt && assignedNextTool)\n'
                    '        const stepLimit = selfPromptCheckpoint\n          ? 512\n          : 4096',
                    '        const stepLimit = 4096')
gate = gate.replace('          selfPromptCheckpoint,\n', '')
gate = gate.replace('      replaceLegacySelfPromptInstruction(event)\n', '')

instruction = '''function appendTaskInstruction(event: any, state: AssignmentState, next?: string) {
  if (!Array.isArray(event.system)) event.system = []
  const text = state.failed
    ? "The assigned action failed. Report the actual error briefly."
    : next
      ? `Continue the current authorized task with the ${next} tool.`
      : "The assigned actions are complete. Give one brief, factual reply."
  event.system.push({ type: "text", text })
}

'''
gate = gate.replace('export default Plugin.define({', instruction + 'export default Plugin.define({', 1)
gate = gate.replace('      if (isDroneAgent(event.agent)) {\n        for (const name of QUEEN_POSTAL_TOOLS)',
'''      if (isDroneAgent(event.agent)) {
        if (!Array.isArray(event.system)) event.system = []
        event.system.push({ type: "text", text: "Use normal conversation and ordinary tool calls. Continue assigned work, then give one concise factual reply. The Architect removed the old checkpoint templates and report-format requirements; historical examples do not reinstate them." })
        for (const name of QUEEN_POSTAL_TOOLS)''', 1)
gate = between(gate, '      if (prompt.startsWith(SELF_PROMPT_RETRY_MARKER)) {',
               '      if (prompt.startsWith(CONTINUATION_MARKER)) {')
gate = between(gate, '      if (prompt.startsWith(CONTINUATION_MARKER)) {',
               '      if (assignment === undefined) {', '''      if (prompt.startsWith(CONTINUATION_MARKER)) {
        const previous = states.get(sessionID)
        if (!previous || previous.failed || previous.planOnly || previous.pending) {
          keepOnlyCurrentTools(event, [])
          return
        }
        const next = previous.tools[previous.completed.length]
        const granted = Boolean(next && previous.grantedTool === next)
        if (granted && (!restoreToolDefinitions(event, previous, [next!])
            || !constrainAssignedToolInputs(event, previous.assignment, [next!], previous.completed, previous.droneAgentID))) {
          previous.failed = true
          keepOnlyCurrentTools(event, [])
          return
        }
        keepOnlyCurrentTools(event, granted ? [next!] : [])
        optionalizeTrustedRouterInputs(event, granted ? [next!] : [])
        appendTaskInstruction(event, previous, granted ? next : undefined)
        return
      }
''')
gate = between(gate, '      if ((previous?.assignment === assignment || previous?.sourceAssignment === assignment) && !previous.planOnly) {',
               '      const available = Object.keys(event.tools ?? {})', '''      if ((previous?.assignment === assignment || previous?.sourceAssignment === assignment) && !previous.planOnly) {
        const next = previous.failed || previous.pending ? undefined : previous.tools[previous.completed.length]
        const granted = Boolean(next && previous.grantedTool === next)
        if (granted && (!restoreToolDefinitions(event, previous, [next!])
            || !constrainAssignedToolInputs(event, previous.assignment, [next!], previous.completed, previous.droneAgentID))) {
          previous.failed = true
          keepOnlyCurrentTools(event, [])
          return
        }
        keepOnlyCurrentTools(event, granted ? [next!] : [])
        optionalizeTrustedRouterInputs(event, granted ? [next!] : [])
        appendTaskInstruction(event, previous, granted ? next : undefined)
        return
      }
''')
gate = gate.replace('      appendSelfPromptInstruction(event)', '      appendTaskInstruction(event, states.get(sessionID)!, tools[0])')
gate = between(gate, '    await ctx.tool.transform((editor: any) => {', '    await ctx.tool.hook("execute.before",')
gate = between(gate, '      if (String(event.tool) === DRONE_SELF_PROMPT_TOOL) {',
               '      const expected = state.tools[state.completed.length]\n      if (state.failed || state.pending || state.awaitingSelfPrompt')
gate = gate.replace('state.failed || state.pending || state.awaitingSelfPrompt', 'state.failed || state.pending')
# Remove the retired tool's after-hook branch, keeping the ordinary action checks.
after = gate.index('    await ctx.tool.hook("execute.after",')
start = gate.index('      if (String(event.tool) === DRONE_SELF_PROMPT_TOOL) {', after)
finish = gate.index('      if (!state', start)
gate = gate[:start] + gate[finish:]
gate = gate.replace('        state.grantedTool = undefined\n        state.awaitingSelfPrompt = true\n        state.awaitingToolExecution = false',
                    '        state.grantedTool = state.tools[state.completed.length]\n        state.awaitingToolExecution = Boolean(state.grantedTool)')
# Summary capture remains; only successful incomplete tasks may receive one continuation per step.
start = gate.index('        if (state?.awaitingToolExecution && state.grantedTool) {')
finish = gate.index('    })().catch((error: any) => {', start)
gate = gate[:start] + '''        if (!sessionID || !state || state.planOnly || state.failed || state.pending) continue
        const expected = state.tools[state.completed.length]
        if (!expected) {
          await writeGateTrace("assignment_complete", { sessionID, completed: state.completed.length })
          continue
        }
        const stepKey = `${sessionID}:${state.completed.length}`
        if (continuationFlights.has(sessionID)) continue
        if (state.continuedMessageSteps.has(stepKey) || state.continuationCount >= MAX_AUTOMATIC_CONTINUATIONS) {
          state.failed = true
          await writeGateTrace("continuation_stopped", { sessionID, reason: "no_action_progress", nextTool: expected })
          continue
        }
        continuationFlights.add(sessionID)
        state.continuedMessageSteps.add(stepKey)
        state.continuationCount++
        state.grantedTool = expected
        state.awaitingToolExecution = true
        try {
          await ctx.session.prompt({
            sessionID, delivery: "steer",
            text: `${CONTINUATION_MARKER}\\nContinue the current authorized task. Call the ${expected} tool.`,
          })
          await writeGateTrace("continuation_queued", { sessionID, nextTool: expected, count: state.continuationCount })
        } catch (error: any) {
          state.failed = true
          await writeGateTrace("continuation_failed", { sessionID, reason: String(error?.message ?? error) })
        } finally {
          continuationFlights.delete(sessionID)
        }
      }
''' + gate[finish:]
gate = re.sub(r'^\s+(?:awaitingSelfPrompt|selfPromptRetryCount):[^\n]*\n', '', gate, flags=re.M)
for retired in ('DRONE_SELF_PROMPT_TOOL', 'awaitingSelfPrompt', 'selfPromptRetryCount', 'visibleSelfPrompt', 'appendSelfPrompt', 'SELF_PROMPT_RETRY'):
    assert retired not in gate, retired
gate_path.write_text(gate, encoding='utf-8', newline='')

bridge_path = ROOT / '.opencode/plugins/lmstudio-toolbridge.ts'
bridge = bridge_path.read_text(encoding='utf-8-sig')
bridge = bridge.replace('const droneSelfPromptTool = "localcoder_drone_self_prompt"\n', '')
bridge = bridge.replace('    || /^[ \\t]*\\[LOCALCODER PRIVATE DRONE SELF-PROMPT RETRY \\| v1\\][ \\t]*$/m.test(prompt)\n', '')
bridge = between(bridge, '        const trustedSelfPromptControl = String(event.tool) === droneSelfPromptTool',
                 '        const expected = nextExplicitTool(explicitSequence)',
                 '      if (explicitSequence?.tools.length) {\n')
bridge = between(bridge, '      if (event.tool === droneSelfPromptTool',
                 '      if ((event.tool === "aios_router_complete_lane"')
bridge = between(bridge, '        if (isDroneActionPrompt(prompt) && tools.has(droneSelfPromptTool)) {',
                 '        } else if (requestPath.endsWith("/v1/chat/completions") && isDroneActionPrompt(prompt)) {',
                 '')
bridge = bridge.replace('        } else if (requestPath.endsWith("/v1/chat/completions") && isDroneActionPrompt(prompt)) {',
                        '        if (requestPath.endsWith("/v1/chat/completions") && isDroneActionPrompt(prompt)) {', 1)
bridge = bridge.replace("across the gate's private self-prompt continuation.", "across the gate's bounded continuation.")
bridge = bridge.replace('            } else {\n              sequence.tools = requestedSequence\n            }',
'''            }
            if (sequence.tools.join("\\0") !== requestedSequence.join("\\0")) {
              sequence.tools = requestedSequence
              sequence.completed = []
            }''', 1)
assert 'droneSelfPromptTool' not in bridge
bridge_path.write_text(bridge, encoding='utf-8', newline='')

agents_path = ROOT / 'AGENTS.md'
agents = agents_path.read_text(encoding='utf-8-sig')
agents = agents.replace('Use the visible agenda/state/next self-prompt after a tool result without repeating internal deliberation.',
                        'Use normal conversation and ordinary tool calls. Give one concise factual result when the task ends; no verbose checkpoint blocks or mandatory report format.')
agents_path.write_text(agents, encoding='utf-8', newline='')
compact_path = ROOT / '.opencode/prompts/drone-worker-compact.md'
compact = compact_path.read_text(encoding='utf-8-sig')
compact = re.sub(r'^After each non-final tool, show \[DRONE SELF-PROMPT\][^\n]*',
                 'Use normal conversation and ordinary tool calls. Continue the assigned work, then give one brief factual result. No checkpoint blocks, mandatory labels, or report-format retries.', compact, flags=re.M)
compact_path.write_text(compact, encoding='utf-8', newline='')
config_path = ROOT / 'opencode.json'
config = json.loads(config_path.read_text(encoding='utf-8-sig'))
system = config['agents']['build']['system']
system = re.sub(r'4\. After each tool result, self-prompt[^\n]*',
                "4. After each tool result, choose the next necessary action within the assignment. Stop when the task is complete or an action fails.", system)
system = system.replace("SELF-PROMPT AND JOURNAL:\nUse the Monologue Journal's agenda → state → next-step shape, but write only receipt-grounded facts.",
                        'EVIDENCE AND JOURNAL:\nReport only facts supported by actual tool results.')
system += '\n\nNORMAL CONVERSATION:\nUse ordinary chat and tool calls. Finish with one brief factual reply. The Architect removed verbose checkpoints and mandatory report formatting.'
config['agents']['build']['system'] = system
for agent in config['agents'].values():
    if isinstance(agent, dict) and isinstance(agent.get('permissions'), list):
        agent['permissions'] = [rule for rule in agent['permissions'] if rule.get('action') != 'localcoder_drone_self_prompt']
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='')
print(json.dumps({'gate_lines_before': len((ROOT/'.opencode/snapshots/normal-conversation-20261117/localcoder-drone-assignment-gate.ts').read_text(encoding='utf-8-sig').splitlines()),
                  'gate_lines_after': len(gate.splitlines()), 'self_prompt_tool': 'removed', 'final_format_retries': 'removed'}))
