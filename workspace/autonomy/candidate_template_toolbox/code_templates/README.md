# Viv deterministic code-template toolbox

This directory is the authoring surface for the portable template toolbox.

AI and Viv may inspect or propose a source-template improvement here only on an
explicit authoring request. A human must approve every source-template create,
modify, or adopt action. Normal operation changes declared variable values and
selects/reorders already-approved functions; it does not add a function or
template. Normal code creation is performed by
`L:/Continue/Viv/build_tools/template_builder_v1.py`, which indexes the source
and copies exact source spans into immutable generated generations.

The source index and its receipt are stored under
`L:/Continue/Viv/foundation/artifacts/auto/code_templates/`. A source edit must
be re-indexed before it can be published. The builder stages a complete
generation in a private same-root directory, verifies it, atomically promotes
the directory, and atomically replaces `template_current.json`; an existing
generation is never edited in place.

The AI-facing build action is a structured selection request with schema
`viv_code_template_selection_request_v1`:

```json
{
  "schema_version": "viv_code_template_selection_request_v1",
  "templates": [
    {
      "template_id": "fixture.echo",
      "target_pillars": ["rid"],
      "submain_order": []
    }
  ]
}
```

The request contains approved IDs and ordering data, not generated Python,
source paths, or function bodies. It may select a subset of registered
templates, narrow to already-declared target pillars, and permute the complete
declared submain set. Runtime `variable_overrides` may replace only keys that
the selected template already declares; they are data, not source edits.
`cost` and the `build` dry-run report a model-agnostic estimate of
code-emission tokens versus that request; they also report one-time template
context, a break-even build count, and example amortization. Exact billing
requires the active model tokenizer.

## CPU tool-call grammar

The CPU/Jarvis model is trained and evaluated against the separate
`viv_cpu_tool_call_grammar_v1` data protocol recorded in
`python_tool_call_grammar_v1.json`. Its complete output is one of these
frames:

```text
S|0
H|review
V|fixture.echo|message|hello world
```

`S` selects an already-present catalog slot, `H` is an explicit hold, and `V`
changes only a declared runtime variable. The parser rejects source markers,
paths, arbitrary expressions, undeclared variable keys, and malformed frames.
The grammar canary receives metadata only; it never receives Python bodies and
never inserts a template. Its candidate checkpoint and JSON evidence remain in
the isolated artifact tree until a human reviews them.

The next semantic-routing canary uses `viv_cpu_semantic_card_v1` cards. Each
card reduces an approved catalog entry to a domain, arity, operation/object
roles, and dependency depth. The model sees compact labels such as
`a/auth/a1`, not source paths or function bodies. A semantic match means that
the selected approved catalog card has the requested semantic key; it is a
routing measurement, not proof that the underlying implementation is correct.
The canary keeps same-concept and held-out-concept results separate and never
inserts the selected function into a live generation.

## CPU semantic ontology v2

The versioned `viv_cpu_semantic_card_v2` contract extends the v1 cards with
effect class, risk class, pillar-mapping status, dependency shape, and typed
ambiguity labels. The model still receives only compact metadata labels. The
approved catalog ID, target-pillar mapping, and rule IDs remain CPU-side
metadata for deterministic mapping and receipts; source paths and bodies are
never serialized into the model prompt.

Ambiguity is represented as an explicit disposition plus a typed class such as
`unknown_concept`, `ambiguous_tie`, `unsafe_authority`,
`undeclared_variable`, or `malformed_request`. The CPU independently derives
the disposition. A CPU HOLD overrides a model selection, and an unmapped
target pillar is never inferred. The existing `S|`, `H|`, and `V|` grammar is
unchanged for compatibility.

The bounded v2 canary is candidate-only and CPU-only. It uses 128 training
concepts, 64 concept-disjoint concepts, compositional examples, and hard
negatives. It records actual tokenizer counts, CPU/model disposition
conflicts, repeated deterministic digests, and v1 compatibility floors. It
does not activate the migrated catalog, write a production generation, or
change the active pointer.

The explicit no-write CLI form is:

```text
L:/Continue/.venv/Scripts/python.exe L:/Continue/Viv/build_tools/template_builder_v1.py build --dry-run
```

`template_status()` is the read-only AI/Viv view of template coverage,
variables, target pillars, active generation, source drift, bounded lineage,
and Security state. If a requested ID is not already registered, the normal
AIOS coding path returns `template_authoring_required`; it does not accept a
source body or source path. The explicit authoring exception is the source
template surface itself (or `adopt` from an immutable generation). A human
remains in the loop for every source-template creation or modification: AI/Viv
may inspect the current template, explain a proposed improvement, and prepare
an auditable patch, but publication still requires the approved source bytes
to be re-indexed and verified. Adding a new function or template is never an
automatic AI/Viv action.

The normal Viv IDE path follows the same boundary: generic writes into
`sandbox/code` and inline Python shell commands are denied. A coding request
therefore yields `template_status`, a structured template selection, an
explicit runtime execution request, or an auditable authoring hold. The three
foundation mains expose the same read-only status view for RID, AUTO, and UML;
importing the runtime loader never runs `main` or a submain.

The source contract is strict:

1. imports;
2. `# TEMPLATE VARIABLES BEGIN` / `END` containing a literal `VARIABLES` map;
3. exactly one `main(context, variables)`;
4. zero or more `sub_main_*` functions.

Each submain uses the same `(context, variables)` signature and returns a
mapping with exactly the same variable keys. The loader passes that mapping to
the next submain in declared order; after the last submain, `main` runs once.
With zero submains, no merge occurs and `main` receives a copy of the declared
`VARIABLES` mapping unchanged.

The harmless `fixture.echo` template intentionally has zero submains. Its
registry entry targets all three CPU pillars only to exercise discovery; it has
no filesystem, process, network, training, or runtime side effects.

## Candidate-catalog scale and reference rebuild

The migrated catalog is a human-review candidate surface, not an active
registry. The isolated scale tool verifies the current catalog at 1, 10, 100,
and all available modules, compiles copied bytes without importing them, and
records repeated-build hashes and token estimates:

```text
L:/Continue/.venv/Scripts/python.exe L:/Continue/Viv/build_tools/template_scale_rebuild_v1.py scale-test --case-sizes 1,10,100,310 --repeats 2 --seed 42 --receipt-dir L:/Continue/Viv/foundation/artifacts/auto/code_templates/scale_tests
```

The same tool can rebuild a supplied reference Python file in an isolated
output. It preserves all non-function bytes and replaces top-level functions
only with exact decorator-inclusive spans from the candidate catalog. If a
function is absent, the CPU first looks for an indexed catalog body with the
same AST body and parameter contract. It copies the input header and the
approved catalog body as `catalog_body_recreation`; this is deterministic body
transplantation, not synthesis. If no approved body exists, the default
behavior is a hold. With an explicit `--allow-input-fallback`, the developer
authoring surface may copy that function's exact span from the supplied
reference file and records it as a human-review authoring candidate. It never
asks a model for code, registers the function, or publishes a generation:

```text
L:/Continue/.venv/Scripts/python.exe L:/Continue/Viv/build_tools/template_scale_rebuild_v1.py rebuild --input <reference.py> --output <isolated-output.py> --isolated --no-publish --allow-input-fallback --receipt-dir L:/Continue/Viv/foundation/artifacts/auto/code_templates/rebuild_tests
```

The model-facing action is therefore a structured decision and a tool call:
select approved function/template IDs, provide data-only variable values, and
let the CPU copy the approved bytes. Ordinary Python generation is forbidden.
The scale and rebuild receipts explicitly report `synthesis_performed: false`,
the catalog/function-index and built-in-surface hashes, missing functions,
catalog body-recreation provenance, exact fallback spans, compile status, and
unchanged production pointer/registry boundaries.

For the end-to-end random-file operation, use `rebuild-random`. It always
keeps the two safety guards, copies exact catalog spans, and uses only
AST-matched catalog bodies to recreate functions whose names or signatures do
not match. It never enables the input-span fallback:

```text
L:/Continue/.venv/Scripts/python.exe L:/Continue/Viv/build_tools/template_scale_rebuild_v1.py rebuild-random --input <random.py> --output L:/Continue/Viv/sandbox/code/template_rebuilds/random.py --isolated --no-publish --receipt-dir L:/Continue/Viv/foundation/artifacts/auto/code_templates/rebuild_tests
```

If neither an approved catalog span nor a compatible catalog body is usable,
the operation holds and creates no output. The explicit `rebuild
--allow-input-fallback` mode remains available only for a human-authoring
candidate and is not reachable through the normal Viv random-file tool.
Sandbox candidates are still Rust-governed: the normal CLI submits the
hypothetical Python write to the existing Rust membrane before creating the
isolated output. With the current `AUTONOMOUS_PYTHON_WRITE_ENABLED=false`
authority, the normal operation records `HOLD_SECURITY` and creates no Python
file. The self-test's disposable local adapter is test-only evidence and is
never a live AIOS write. Any candidate that passes sandbox review still needs
explicit human approval before `adopt` can insert it into the editable source
layer or active registry.

## Python built-in primitive surface

The attached built-in-function specification is recorded at
`foundation/code_templates/python_builtins_v1.json`. It inventories 31
primitives across core I/O/debugging, type conversion, sequence/length,
mathematical aggregation, logic/validation, functional programming, and
object identity/attributes. Twenty-seven deterministic primitives—including
`print`, `type`, casting/container constructors, sequence helpers, arithmetic
aggregators, validation helpers, `map`, and `filter`—may appear in a
catalog-body recreation when the copied catalog body passes the CPU safety
validator. `input`, `help`, `id`, and `dir` are visible in the manifest but are
review-only: they can be human-authored under the existing permission gate,
but cannot be introduced by an automatic random rebuild. The model supplies
neither source text nor a built-in call list; it selects the path-only tool and
the CPU verifies the indexed bytes.

`inventory` is an optional read-only migration/audit operation. It reports the
existing AIOS functions and exact decorator-inclusive line spans so future
template authoring can be deliberate; it is not required for normal pragmatic
selection or variable execution. It does not import or rewrite the current
RID, AUTO, UML, or foundation modules.

## Existing AIOS function migration

The initial template library is created from the functions already present in
the foundation code by the one-time migration tool:

```text
L:/Continue/.venv/Scripts/python.exe L:/Continue/Viv/build_tools/migrate_aios_functions_to_templates_v1.py --apply
```

The script scans `foundation/rid_main.py`, `foundation/auto_main.py`,
`foundation/uml_main.py`, and `foundation/lib/**/*.py`. It categorizes each
source module into a domain directory, copies the complete source file
byte-for-byte into `source/migrated_domains/<domain>/`, and records the
functions used by each function through the AST call graph, including
resolvable calls imported from other scanned foundation modules. It does not
import, edit, or delete the live AIOS modules. Toolbox infrastructure
(`code_template_runtime.py`, `viv_python_writer.py`, and `__init__.py`) is
excluded from the domain catalog. `--replace` may remove only stale `.py`
files previously generated under the migration output root.

The migration receipts are:

- `foundation/artifacts/auto/code_templates/migration/AIOS_FUNCTION_TEMPLATE_MIGRATION.json`
- `foundation/artifacts/auto/code_templates/migration/domain_index.json`
- `foundation/artifacts/auto/code_templates/migration/function_index.json`

`function_index.json` is the line map: every function has its original source
path and line range, copied template path and line range, source/template
hashes, direct calls, called symbols, local closure, resolved cross-module
calls, and resolved transitive function-use closure. The copied migration
files are authoring candidates and are not silently added to the active
runtime registry. Human review must choose the domain functions and approve
any conversion into an active `(context, variables)` template.
