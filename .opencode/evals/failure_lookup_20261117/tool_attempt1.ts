import { Plugin } from "@opencode/plugin"

export default Plugin.define({
  id: "localcoder.failure-lookup",
  async setup(ctx) {
    const tools = []

    await ctx.tool.transform(editor => {
      tools.push(
        editor.add({
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
          outputSchema: {
            type: "object",
            properties: {
              content: { type: ["string"] }
            },
            required: ["content"],
            additionalProperties: false
          },
          execute(input) {
            const limit = input.limit ?? 8
            if (typeof limit !== "number" || !Number.isInteger(limit) || limit < 1 || limit > 20) {
              throw new Error("limit must be an integer between 1 and 20")
            }

            const argv = ["-B", "L:/LocalCoder/workspace/autonomy/receipt_failure_lookup_candidate.py", "--limit", String(limit)]
            if (input.case && typeof input.case === "string" && input.case.length >= 1 && input.case.length <= 120) {
              argv.push("--case", input.case)
            }

            const sourcePath = "L:/LocalCoder/workspace/autonomy/receipt_failure_lookup_candidate.py"
            if (input.source && typeof input.source === "string") {
              // source is passed to lookup_failures via the Python module's --source flag
              argv.push("--source", input.source)
            }

            try {
              const { execFileSync } = await import("node:child_process")
              const stdout = execFileSync(
                "L:/LocalCoder/.venv/Scripts/python.exe",
                argv,
                { cwd: "L:/LocalCoder", encoding: "utf8", timeout: 15000, maxBuffer: 131072, windowsHide: true }
              ).toString()

              const result = JSON.parse(stdout.trim())

              return {
                content: JSON.stringify(result)
              }
            } catch (err) {
              throw new Error(`subprocess failed: ${err.message}`)
            }
          }
        })
      )
    })

    return tools
  }
})
