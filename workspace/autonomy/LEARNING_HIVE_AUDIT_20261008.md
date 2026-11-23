# Learning and Hive audit — 2026-10-08

## Verified observations

- Snapshot: 118 completed receipts, 68 teacher lessons; all 68 teacher actions matched INN proposals, with zero disagreements or rejected teacher lessons. 45 lessons offered multiple candidates. Tools included TILL, SEED, WATER, HARVEST and IDLE.
- State lesson counters matched receipt lesson counts at this snapshot. Engine is `learned-v9`, the linear action-value learner, not the experimental transformer or a language model.
- The frozen fresh-farm 1,000-step evaluation returned current score 98 (107 harvests, 9 decays), versus saved parent score 104 (109 harvests, 5 decays). Current evaluator weights were unchanged by the probe. This is a regression on this probe, not a generalization result.
- SQLite `PRAGMA integrity_check` returned `ok`.
- Process parent IDs show one supervisor launcher/child pair and one worker launcher/child pair, not two independent workers.
- Locked architecture documents and Rust control source matched manifest hashes. Full lock validation failed on `hive_network_proof.py`: expected E790EAD2D126E42FDCB56B0176B01B603AD3F5FCEAB5AF693932A48C61DEC721, actual 88B5DB0432C1A448DBC8FA47C1928A0923222EAD1E676289CD1A2BEFB3911293. The cause/date of this mismatch is unproven; manifest was not modified to hide it.

## Learning defects and limits

1. The integration performs TD updates on teacher actions. It does not train language outputs or teacher rationale, and the INN proposal sentence is a Python template.
2. The teacher sees the student proposal and scores. Perfect agreement cannot establish independent teacher competence or student improvement.
3. Counterfactual utility uses one immediate tick. Productive actions can tie with IDLE; this is not a long-term game mastery oracle.
4. The original Simulation learns pending immediate reward plus the next `begin` world reward. The integration drops delayed world reward from its teacher TD update. Barren penalties and later harvest outcomes are therefore not assigned using the original learner's transition contract.
5. The integration currently hardcodes StabilizedSourceEngine; it does not distill into the experimental transformer.
6. A negative TD reward is not guaranteed to reduce a score: its target also includes bootstrapped future value. The dashboard's imitate/reject label describes the requested signal, not measured resulting behavior.
7. Current state is overwritten atomically, but per-cycle immutable weight checkpoints and before/after behavioral admission gates are absent. Receipt hashes alone do not permit full historical weight replay.

## Hive checks

47 tests across autonomy, chat CLI, network proof and foreman memory: 45 passed, 2 failed. Scheduler default now includes farm_learning where the existing test expects test as the last activity; generic ask_model keep_alive changed from zero to 30m and breaks its prior unload contract.

22 tests across drive stacks, workspace observer and project builder: 19 passed, 3 adapter-readiness subcases failed. Those cases assume C/D/F adapters are absent; the live environment has ready adapters. This failure alone does not prove adapter corruption.

Streamlit dependency repair force-reinstalled dependencies in the shared environment, including NumPy, Click, Pandas and protobuf. Existing dependency conflicts were reported. No full training-package compatibility result exists, so the environment cannot be certified intact from these tests.

## Required repair direction

Restore delayed transition credit, record pre/post weight evidence, evaluate independently against the immutable parent, isolate farm-specific inference residency from generic Hive inference, and distinguish teacher agreement from behavioral gains. A language tokenizer/output architecture and grounded language evaluation remain necessary for learned speech.

This audit does not certify the entire Hive or claim generalized learning.
