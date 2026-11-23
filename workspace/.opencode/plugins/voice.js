import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { completedReply } from "../../hive_voice/voice_event.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const python = resolve(root, "hive_voice", ".venv", "Scripts", "python.exe");
const script = resolve(root, "hive_voice", "speak.py");

function speak(request) {
  const requests = resolve(root, "hive_voice", "runtime", "requests");
  mkdirSync(requests, { recursive: true });
  const file = resolve(requests, `${Date.now()}_${randomUUID()}.json`);
  writeFileSync(file, JSON.stringify(request), { encoding: "utf8", flag: "wx" });
  const child = spawn(python, [script, "--request", file], {
    cwd: root,
    stdio: "ignore",
    windowsHide: true,
    shell: false,
    detached: true,
  });
  child.on("error", (error) => console.error(`[viv-voice] worker start failed: ${error.message}`));
  child.unref();
}

export const VivVoicePlugin = async ({ client }) => {
  const seen = new Map();
  const sessionRoot = new Map();
  const parts = new Map();
  function loadSession(sessionID) {
    if (sessionRoot.has(sessionID)) return;
    sessionRoot.set(sessionID, false);
    client.session.get({ path: { id: sessionID } }).then((session) => {
      sessionRoot.set(sessionID, !session.error && !session.data?.parentID);
    }).catch(() => sessionRoot.delete(sessionID));
  }
  return {
    event: async ({ event }) => {
      if (event.type === "session.created") {
        sessionRoot.set(event.properties.info.id, !event.properties.info.parentID);
        return;
      }
      if (event.type === "message.part.updated") {
        const part = event.properties.part;
        if (part.type === "text") {
          const byMessage = parts.get(part.messageID) ?? new Map();
          byMessage.set(part.id, part);
          parts.set(part.messageID, byMessage);
        }
        return;
      }
      if (event.type === "message.updated" && event.properties?.info?.role === "user") {
        loadSession(event.properties.info.sessionID);
        return;
      }
      const completeMessage = event.type === "message.updated" &&
        event.properties?.info?.role === "assistant" &&
        Boolean(event.properties.info.time?.completed) &&
        ["stop", "length"].includes(event.properties.info.finish);
      if (!completeMessage) return;
      if (!existsSync(python) || !existsSync(script)) return;
      const info = event.properties.info;
      const sessionID = info.sessionID;
      if (!sessionRoot.get(sessionID)) return;
      try {
        const reply = completedReply([{ info, parts: [...(parts.get(info.id)?.values() ?? [])] }]);
        parts.delete(info.id);
        if (!reply || seen.get(sessionID) === reply.message_id) return;
        seen.set(sessionID, reply.message_id);
        if (seen.size > 200) seen.delete(seen.keys().next().value);
        const request = { ...reply, session_id: sessionID };
        speak(request);
      } catch (error) {
        console.error(`[viv-voice] event failed: ${error.message}`);
      }
    },
  };
};
