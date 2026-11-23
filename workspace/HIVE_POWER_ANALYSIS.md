# Hive 80-task power analysis (planning note)

Status: corrected planning calculation under architecture lock v1.1. No
held-out benchmark results exist.
The first held-out set is 80 newly authored synthetic tasks, split evenly
across Python, Rust, AIOS, and mixed work. It tests bounded feasibility; it does
not establish transfer to AIOS history. Afterward, a separately frozen
AIOS-history set will test transfer; its size and protocol are undecided. Keep
both sets out of tuning and freeze each before any candidate sees it. Visible
development cases used while tuning the harness cannot estimate power.

## Primary comparison and exact procedure

The primary comparison is Viv with role prompts versus Viv with the Swarm;
Viv alone remains a secondary arm. Each task produces a paired binary outcome
(correct/incorrect). This note calculates power for a two-sided exact McNemar
test at alpha = 0.05: conditional on the observed number of discordant pairs
`D`, use the exact Binomial(`D`, 0.5) tail probability and reject when the
two-sided p-value is at most 0.05. Under the planning model, `D` is
Binomial(`n`, `q`), so power averages that conditional rejection probability
over the random `D`.

The architecture's decision rule also requires an observed paired correctness
gain of at least 10 percentage points. This note computes that as
`(Swarm-only correct − baseline-only correct) / 80 >= 0.10`, alongside the
exact test. It does not treat a paired 95% confidence interval as equivalent:
the preregistration must name the exact test and interval, if an interval is
also reported. For this table, the exact-test rule is primary; no interval rule
is assumed.

## Assumptions and feasibility

Let `p_b` be baseline correctness, `p_s = p_b + Δ` be Swarm correctness, and
`q` be the probability the two arms disagree. `q` is a nuisance parameter
determined by how their errors co-vary on the same tasks; it is not an
independent performance control. Conditional on discordance, the probability
that the Swarm-only arm is correct is `(q + Δ) / (2q)`, and baseline-only is
`(q − Δ) / (2q)`.

For the illustrative `p_b = 0.70` and `Δ = 0.10`, the joint outcome
probabilities are:

| Paired outcome | Probability |
| --- | ---: |
| both correct | `p_b − (q − Δ)/2` |
| Swarm only correct | `(q + Δ)/2` |
| baseline only correct | `(q − Δ)/2` |
| both incorrect | `1 − p_b − (q + Δ)/2` |

All four probabilities must be nonnegative. Thus, with these illustrative
marginal accuracies, `q` must be between 0.10 and 0.50. Independent correctness
errors at 70% and 80% marginal accuracy imply `q = 0.38`; lower values describe
more correlated outcomes. Actual `q` is unknown. A separate non-held-out pilot
may inform the planning range, but a 20–30-task pilot gives a noisy estimate
of `q`; it narrows the uncertainty without settling it. Pilot tasks must not
enter either frozen evaluation set.

## Results for n = 80

The table uses feasible illustrative values, including `q = 0.38` as the
independent-error reference. Percentages are exact enumeration under the
procedure above; they are planning estimates, not measured Viv results.

| Discordance `q` | Power at true gain `Δ = 10 pp`, exact test | Power at 10 pp, test plus observed-gain gate | Minimum `Δ` for 80% power, exact test | Minimum `Δ` for 80% power, both gates |
| ---: | ---: | ---: | ---: | ---: |
| 0.20 | 43.7% | 43.3% | 14.2 pp | 14.3 pp |
| 0.30 | 29.5% | 29.5% | 17.6 pp | 17.6 pp |
| 0.38 | 23.9% | 23.9% | 19.9 pp | 19.9 pp |

For comparison, if exactly 16 discordant pairs were fixed in advance, a 12-to-4
split has two-sided exact p about 0.077. At `q = 0.20`, however, the planning
calculation does not fix `D = 16`; it averages over `D ~ Binomial(80, 0.20)`,
giving 43.7% test power at a true 10-point gain. The 98.0% figure in the prior
version was wrong and is withdrawn. At these assumptions, the observed 10-point
gain gate adds little beyond the exact test; the test itself is the limiting
gate. An 80-task set is underpowered for reliably detecting a true 10-point
gain under these scenarios.

## Decision implications

The Architect's 10-point observed margin remains a practical decision
threshold, but n = 80 should not be described as adequately powered for a true
10-point gain. The primary stance is to preregister n = 80 and the exact
decision procedure, with **inconclusive** an explicit possible outcome; do not
size n from a small pilot estimate of `q`. A non-held-out pilot may refine the
plausible `q` range and planning table, but it cannot settle the power plan:
across `q = 0.20` to `q = 0.38`, the minimum gain for 80% power moves from 14.2
to 19.9 percentage points. The preregistration must preserve the observed
10-point gain criterion and exact test; a non-significant result is not
evidence of no benefit. Any larger follow-up set must be separately frozen
and declared before candidates see it.
