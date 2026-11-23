export const ContinuityPlugin = async () => {
  return {
    "experimental.session.compacting": async (_input, output) => {
      output.context.push(`
Continuity rules for this session summary:
- Preserve the Architect's active request and whether it is complete, in progress, or blocked.
- Carry forward explicit scope, constraints, decisions, and corrections.
- Distinguish user-stated facts, live observations (with source), and hypotheses.
- Record files actually changed and checks actually run with their results; do not infer success.
- Preserve unresolved questions and real blockers. Do not invent a next action if the request is complete.
- Keep the summary concise and do not promote model-generated claims into memory or fact.
      `.trim());
    },
  };
};
