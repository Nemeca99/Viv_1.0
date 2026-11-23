/** Select one completed, top-level assistant reply for Viv's speech boundary. */
export function completedReply(rows) {
  if (!Array.isArray(rows)) return null;
  const last = [...rows].reverse().find((row) => row?.info?.role === "assistant");
  if (!last) return null;
  const info = last.info;
  if (!info.id || !info.time?.completed || info.error || info.summary) return null;
  if (info.finish && info.finish !== "stop" && info.finish !== "length") return null;
  const text = (last.parts ?? [])
    .filter((part) => part?.type === "text" && !part.synthetic && !part.ignored)
    .map((part) => part.text ?? "")
    .join("\n\n")
    .trim();
  if (!text) return null;
  return {
    message_id: info.id,
    mode: selectVoiceMode(info),
    model_id: info.modelID ?? "",
    text,
  };
}

/** Viv has one mouth: Mind-only is conversational; any Swarm synthesis is unified. */
export function selectVoiceMode(info = {}) {
  const contributors = Number(info.swarm_contributors ?? 0);
  if (Number.isFinite(contributors) && contributors > 0) return "logic";
  return info.mode === "companion" ? "human" : "logic";
}
