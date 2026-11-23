import assert from "node:assert/strict";
import { completedReply, selectVoiceMode } from "./voice_event.mjs";

const completed = (mode, parts) => [{
  info: { id: "msg_1", role: "assistant", mode, modelID: "qwen3:8b-local-32k", time: { completed: 1 }, finish: "stop" },
  parts,
}];

assert.deepEqual(completedReply(completed("companion", [{ type: "text", text: "Hello." }])), {
  message_id: "msg_1", mode: "human", model_id: "qwen3:8b-local-32k", text: "Hello.",
});
assert.equal(completedReply(completed("build", [{ type: "text", text: "Ready." }]))?.mode, "logic");
assert.equal(completedReply(completed("build", [{ type: "text", text: "hidden", synthetic: true }])), null);
assert.equal(completedReply([{ info: { id: "msg_2", role: "assistant", mode: "build", time: {} }, parts: [{ type: "text", text: "partial" }] }]), null);
assert.equal(selectVoiceMode({ mode: "companion", swarm_contributors: 0 }), "human");
assert.equal(selectVoiceMode({ mode: "companion", swarm_contributors: 1 }), "logic");
assert.equal(selectVoiceMode({ mode: "companion", swarm_contributors: 10 }), "logic");
console.log("voice selection: 7 cases passed");
