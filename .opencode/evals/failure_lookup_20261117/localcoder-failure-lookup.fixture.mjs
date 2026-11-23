const execFileSync = (...args)=>globalThis.__failureLookupExec(...args);
const Plugin = {
    define: (value)=>value
};
export default Plugin.define({
    id: "localcoder.failure-lookup",
    async setup (ctx) {
        await ctx.tool.transform((editor)=>{
            editor.add({
                name: "localcoder_failure_lookup",
                description: "retrieve actual saved receipt failures, code hashes, and current recorded results. Records are engineering evidence; never infer failure causes, per-case resolution, training, or permission from them.",
                input: {
                    type: "object",
                    properties: {
                        case: {
                            type: "string",
                            minLength: 1,
                            maxLength: 120
                        },
                        limit: {
                            type: "integer",
                            minimum: 1,
                            maximum: 20,
                            default: 8
                        }
                    },
                    required: [],
                    additionalProperties: false
                },
                options: {
                    codemode: false
                },
                execute (input) {
                    if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).some((key)=>key !== "case" && key !== "limit")) {
                        throw new Error("Only case and limit are accepted");
                    }
                    const limit = input.limit === undefined ? 8 : input.limit;
                    if (typeof limit !== "number" || !Number.isInteger(limit) || limit < 1 || limit > 20) {
                        throw new Error("limit must be an integer between 1 and 20");
                    }
                    if (input.case !== undefined && (typeof input.case !== "string" || !input.case.trim() || input.case.length > 120)) {
                        throw new Error("case must be a nonempty string of at most 120 characters");
                    }
                    const argv = [
                        "-B",
                        "L:/LocalCoder/workspace/autonomy/receipt_failure_lookup_candidate.py",
                        "--limit",
                        String(limit)
                    ];
                    if (input.case !== undefined) {
                        argv.push("--case", input.case);
                    }
                    try {
                        const stdout = execFileSync("L:/.venv/Scripts/python.exe", argv, {
                            cwd: "L:/LocalCoder",
                            encoding: "utf8",
                            timeout: 15000,
                            maxBuffer: 131072,
                            windowsHide: true
                        }).toString();
                        const parsed = JSON.parse(stdout.trim());
                        if (!parsed || parsed.schema !== "localcoder_failure_lookup_v1") {
                            throw new Error("result schema mismatch");
                        }
                        return {
                            content: JSON.stringify(parsed)
                        };
                    } catch (err) {
                        throw new Error(`subprocess failed: ${err.message}`);
                    }
                }
            });
        });
    }
});


//# sourceURL=L:/LocalCoder/.opencode/evals/failure_lookup_20261117/localcoder-failure-lookup.candidate.ts