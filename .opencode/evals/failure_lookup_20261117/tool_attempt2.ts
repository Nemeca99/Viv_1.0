import { Plugin } from "@opencode/plugin"

export default Plugin.define({
  id: "localcoder.failure-lookup",
  async setup(ctx) {
    const tool = editor.add({
      name: "localcoder_failure_lookup",
      description: "retrieve actual saved receipt failures, code hashes, and current recorded results. Records are engineering evidence; never infer failure causes, per-case resolution, training, or permission from them.",
      inputSchema: {
        type: "object",
        properties: {
          case: { type: ["string"], minLength: 1, maxLength: 120 },
          limit: { type: ["integer"], minimum: 1, maximum: 20 }
        },
        required: [],
        additionalProperties: false
      },
      options: { codemode: false },
      execute(input) {
        const limit = input.limit ?? 8
        if (typeof limit !== "number" || !Number.isInteger(limit) || limit < 1 || limit > 20) {
          throw new Error("limit must be an integer between 1 and 20")
        }

        const argv = ["-B", "L:/.venv/Scripts/python.exe", "L:/LocalCoder/workspace/autonomy/receipt_failure_lookup_candidate.py", "--limit", String(limit)]
        if (input.case && typeof input.case === "string" && input.case.length >= 1 && input.case.length <= 120) {
          argv.push("--case", input.case)
        }

        try {
          const stdout = execFileSync(
            "L:/.venv/Scripts/python.exe",
            argv,
            { cwd: "L:/LocalCoder", encoding: "utf8", timeout: 15000, maxBuffer: 131072, windowsHide: true }
          ).toString()

          const parsed = JSON.parse(stdout.trim())
          if (parsed.schema !== "localcoder_failure_lookup_v1") {
            throw new Error("result schema mismatch")
          }

          return {
            content: JSON.stringify(parsed)
          }
        } catch (err) {
          throw new Error(`subprocess failed: ${err.message}`)
        }
      }
    })

    await ctx.tool.register(tool)
  }
})
