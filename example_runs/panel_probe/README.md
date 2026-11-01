# Panel probe: are different roles different voices?

We tested whether roles with different job titles really answer differently, or are one voice under different labels. All text is synthetic.

## What we did

We took the saved team from run C and four group questions from its debrief (exchanges 1, 8, 13 and 17). Each of the six roles answered each question twice, starting fresh the second time without seeing its first attempt. A role's second attempt is its repeat answer.

Models never write the same text twice, so the repeat answer gives a yardstick. It shows how much a role varies from itself, which we can compare with how much it differs from other roles. We scored overlap in wording from 0 (none) to 1 (identical), using TF-IDF cosine similarity.

We ran this in three conditions:

- **Baseline:** every role on `gemini-3.1-pro-preview`, seeing the earlier debrief.
- **Isolated:** the same, but each role saw only its own earlier debrief answers.
- **Mixed models:** CTO and COO on `openai/gpt-5.4`, CMO and Product Designer on `deepseek/deepseek-v4-flash`, CEO and Strategist on Gemini.

## Results

| Compared | Baseline | Isolated | Mixed models |
|---|---|---|---|
| Different roles, same question | 0.10 | 0.11 | 0.09 |
| Same role, repeat answer to the same question | 0.26 | 0.27 | 0.21 |

No answers were lost. `probe.json` holds all 144 answers, and `probe.md` adds the measures.

## How to read it

A role's repeat answer is closer to its first answer than to other roles' answers, which shows that changing the prompt changes the wording. Roles differ in title, notes, draft and document, so this does not show that the title alone did it. Hiding other roles' answers barely changed this. Mixing models lowered similarity only slightly, but only at the debrief stage: every role remembered a deliberation and notes written on Gemini.

## The same test by meaning

Wording can hide shared ideas, so `analysis/semantic_similarity.py` also compares the answers by meaning, using `text-embedding-005` embeddings, at a very small cost. Results are in `semantic.json`.

| Measure | Compared | Baseline | Isolated | Mixed models |
|---|---|---|---|---|
| Answer similarity (cosine) | Different roles, other questions | 0.77 | 0.77 | 0.76 |
| | Same role, other questions | 0.79 | 0.78 | 0.78 |
| | Different roles, same question | 0.84 | 0.84 | 0.84 |
| | Same role, repeat answer | 0.91 | 0.91 | 0.90 |
| Idea coverage: share of sentences with a close match (cosine at least 0.8) | Different roles, same question | 8% | 10% | 6% |
| | Same role, repeat answer | 34% | 32% | 21% |
| Topic overlap across 12 clustered topics (0 to 1) | Between roles | 0.78 | 0.75 | 0.78 |
| | Same role, repeat answers | 0.89 | 0.91 | 0.90 |

By meaning, roles are much closer than wording suggested: answering the same question moves similarity about as much as being the same role does (0.77 to 0.84, then 0.84 to 0.91). Roles cover overlapping ground, yet few of their specific sentences match: about 8% between roles, against 34% for a role with itself. So they talk about similar things and bring different specifics. Hiding others' answers again changed little. Mixing models also changed little, but this only changed who answered the debrief: every role remembered a deliberation and notes written on Gemini, so it does not test a team that deliberates on mixed models.

The full runs show the same pattern for different roles on the same question: 0.87, 0.86, 0.83 and, for grounded run D, 0.87 (`semantic_full_runs/`). They have no repeat answers, so they have no direct yardstick.

## Is the difference significant?

Within these answers, yes, but it is small. A role's repeat answer beat its similarity to other roles by 0.07 on average, in 23 of 24 role-question pairs (permutation p below 0.001, 95% interval 0.04 to 0.11). This comes from one saved deliberation, four questions and two samples per role. Answers within one run are not independent, so it does not generalize to other teams; that takes many separate runs. `statistics.md` has the detail, including a check for convergence during deliberation, and `analysis/role_statistics.py` reproduces it.

## What it does not show

- Neither measure tests reasoning or agreement. Roles could mean similar things and disagree, or mean different things and share one logic. Testing that would need coding answers for positions and arguments.
- Embedding scores run high for texts on one subject, so compare them with the yardstick, not with zero. The 0.8 match threshold and 12 topics are our choices, and no person checked the matches.
- Each role has its own notes and draft from the saved run, which could explain part of the gap.
- As the code stood when this ran, a role's session within a sample also held its own answers to the earlier probe questions, so the two samples' prompts are strictly identical only at the first question.
- All conditions share the same saved deliberation, and retrieval is absent.
- It is one small sample from one run, so it shows direction, not an effect size.

## The calculation

Write r for a role, q for a question and k for a sample (1 or 2), and A(r, q, k) for the answer.

- **What each condition sees.** At baseline, a role sees the saved debrief up to that question. With others' answers hidden, it sees only its own earlier debrief answers and the researcher's earlier questions, some of which relay what other roles said, and it still remembers the shared deliberation. Questions are spread as evenly as possible across the eight group questions in run C's debrief.
- **Wording.** Lowercase each answer, split it into words and drop common stop words. With tf(w, a) the count of word w in answer a, N = 48 answers in a condition and df(w) the number of those answers containing w, the weight is x(w, a) = tf(w, a) × ln[(1 + N) / (1 + df(w))]. The similarity of two answers is the cosine of their weight vectors.
- **Meaning.** Each answer goes to `text-embedding-005` with the task type `SEMANTIC_SIMILARITY`. The vector is scaled to length 1, so the similarity is the dot product of the two vectors.
- **The two rows.** "Same role, repeat answer" is the mean of sim(A(r, q, 1), A(r, q, 2)) over 24 pairs. "Different roles, same question" is the mean of sim(A(r, q, k), A(r′, q, k)) over 15 role pairs, 4 questions and 2 samples, which is 120 pairs. In `probe.json` the wording rows are the fields `between_roles_same_sample` and `same_role_second_sample`.
- **The gap.** On the meaning measure, G(r, q) = sim(A(r, q, 1), A(r, q, 2)) − (1/10) × [sum over the five other roles r′ and k = 1, 2 of sim(A(r, q, k), A(r′, q, k))]. Its mean over the 24 combinations equals, apart from rounding, the difference between the two meaning rows.
- **The p-value.** A two-sided sign-flip test: in each of 20,000 draws, give each of the 24 values a random sign and take the signed mean M. Then p = (1 + the number of draws with |M| ≥ |mean gap|) / 20,001. The test treats the values as independent, and they are not, since they share questions and roles.
- **The interval.** 5,000 times, draw four questions and six roles with replacement and take the mean of G over the resulting grid. The interval runs from the 2.5th to the 97.5th percentile of those means.
- **Reproducing the figures.** One random generator, seeded once with 11, runs through the conditions in the order baseline, isolated, mixed, drawing the interval and then the p-value for each, so the exact figures reproduce only in that order. `statistics.md` holds the results.

The code is in `analysis/provenance.py`, `analysis/panel_probe.py`, `analysis/semantic_similarity.py` and `analysis/role_statistics.py`. The wording scores can be recomputed from `probe.json` with no model calls. The meaning scores, the gap and its statistics need calls to the embedding model.

To rerun it: `python -m analysis.panel_probe --run-dir example_runs/run_C --vertex --allow-version-mismatch --questions 4 --mix CTO=openai,COO=openai,CMO=deepseek,Product_Designer=deepseek`.
