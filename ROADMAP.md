# Roadmap

This page lists what is built, what is partly built and what is planned. It goes with the technical appendix of the accompanying Organization Science proposal. Here an agent is a language model (a program trained on vast amounts of text to write likely continuations of the text it receives) given a name, a role and instructions; a run is one complete simulated meeting and debrief (the researcher agent's interview of the team); and P1 to P3 are priority levels, with P1 first. [`docs/GLOSSARY.md`](docs/GLOSSARY.md) explains the terms used here.

## Status

| Part | Status | Notes |
|---|---|---|
| Study modules (question, lens or theory analyzed through, vocabulary, scenario brief (the kind of firm simulated), debrief topics, corpus loader for its documents) | Built | Safeguard tests (checks that the research question does not steer agents) run on any study added to the test list |
| Roles, scenarios (settings of firm, industry context and product type) and workflow set by the study | Planned (P2) | The study's schema (template of required fields) has override fields, but nothing reads them yet. Defaults sit in framework code |
| Deliberation modes (ways the team takes turns) and stop rules (conditions that end a discussion) | Built | Five modes, three stop rules |
| Environmental conditions as a third study dimension | Future study | Today: industry context × product type, and year |
| Grounding (giving agents real documents to cite; unrelated to grounded theory) with citations | Partial | Built on Vertex AI (Google's cloud service) and tested on one firm. Other corpora (document collections), a citation-accuracy threshold and a local vector store (searches by meaning on your own computer) are to come (P1) |
| Researcher agent (observes and debriefs the team): field notes, observation summary, panel debrief (questioning the team) | Built | Safeguards I1–I5 (five rules that keep the research question from steering agents) tested |
| Question screening | Partial | Word list only; paraphrases can pass |
| Model per role, including open-weight models (published so anyone can run them) | Built | The researcher agent is fixed to Gemini Pro (Google's model). Only Gemini has run a full session (a whole run) in the runs reported; other models have run only in the debrief probe (a test on one saved run) |
| Records of messages, documents, private notes and retrieved passages | Built | |
| Reasoning traces (saved copies of a model's working-out) | Planned (P1) | |
| Replication manifest (a file recording what produced a run) | Built | Written to each completed run folder since the short check (`example_runs/short_check/`), with hashes (file fingerprints) of what agents are told. Runs A to D predate it; `example_runs/prompts_as_run/` holds their prompts |
| Method tests beyond the safeguards | Partial | Provenance report (where a run's words first appeared) and role probe (the debrief probe above, so far for ungrounded runs only) built; the rest planned (P1) |
| Practitioner review of roles | Planned (P1) | |
| Run register of all runs, including failed ones; batch runner (starts many runs in one go) | Planned (P1) | |
| End-to-end live tests (on real models, at real cost) | Partial | Written for six provider (model supplier) setups; four runs simulating OpenAI, on Gemini, completed. The current code has unit tests (small automatic checks), a dry run (rehearsal with a stand-in model, at no cost), a live grounded replay (a later stage rerun from a saved run) and a short live run, not yet a full run |
| Documentation for new users | Built | README (a folder's opening page), study guide, reproduction guide, source list |
| Declarative study file (settings in one file rather than code), template study, command-line tool (used by typing commands) | Planned (P2) | |
| Browser interface for designing studies | Planned (P3) | |

## P1: auditability first

- **Reasoning traces.** Save model thinking output (working-out text some models produce before replying) where providers expose it, record whether it is full, summarized or hidden, and pass traces to the researcher agent.
- **Full prompts.** Save each call's full prompt, so a run's records show what agents received.
- **Method tests:**
  - role drift (an agent straying from its role) and missed scenario conditions (settings of a run that agents ignore);
  - firm-specific claims no corpus document supports;
  - reruns with reworded prompts and other models;
  - reruns with firm names masked (hidden), to catch recalled outcomes;
  - the pilot (the earlier study that preceded this framework) interview protocol against the neutral one;
  - retrieval for the role probe, so it can run on grounded runs.
- **Practitioner review.** Practitioners review the role descriptions.
- **Condition text.** Rewrite it in plain words, because its wording can come back as the agents' own analysis (`docs/LEARNINGS.md` L8).
- **Observer.** Set the openness study so its observer enters with the research question (`embedded_observation=True`).
- **Run register.** Every run, including failed ones, with the reason it failed.
- **Connection check.** Before each run, confirm that a test query returns passages, and report any retrieval that returns nothing.
- **Full-length runs.** The limits on deliberation time, actions and debrief exchanges are development settings. Lift them for the main runs, so that we can see whether and how teams and the researcher reach an end on their own, and keep only a high ceiling to stop a runaway run.
- **Batch runner.** Needed for the repeated runs below, so it moves up from P2.
- **Grounding:**
  - build the firm corpora from the source list, with links for all documents;
  - check citation accuracy against agreed thresholds;
  - add a local vector-store option, so grounded runs don't need Google Cloud (Google's rented computing services).
- **Researcher model.** Make it configurable, including open-weight models.
- **Local model route.** Set the context length (the most text a model can take in during one call) on the route to local models, and test that long prompts arrive whole.

## P2: framework and study fully separate

- **Study-owned setup.** Move the default roles, scenarios and workflow out of the framework core and into the study.
- **Declarative study file.** One file sets roles, team size, scenarios and events, workflow, rounds, debrief topics, corpus and repeats. Python (the programming language used here) is needed only for custom phases (numbered stages of a run).
- **Template study** to copy and edit.
- **Command-line tool** to create, validate (safeguard tests plus a dry run with no model calls), run and export studies.
- **Batch runner** cost estimates and concurrency (several runs at once), building on the P1 runner.
- **Second worked example,** a small study unlike the openness study, to prove the separation.
- **Boundary test** that fails if framework code depends on a study.
- **Safeguard tests** that discover studies automatically.

## Before collecting the study's data

The prototype runs (four test runs simulating one firm) are small, so the risks they raised must be tested thoroughly before we collect the data for this paper. We will not start the main data collection until these tests have run and we have reported the results, whatever they show. We will agree what counts as a pass before running them.

- **Repeated runs.** Separate runs per condition on selected scenarios, because answers within one run are not independent, and to set how many repeats the main data need.
- **Mixed models from the start.** Teams that deliberate on different models from their first message, including an open-weight model, compared with single-model teams. Choose and pin (fix the exact versions of) current models first, since the prototype's `gemini-3.1-pro-preview` is no longer Google's newest.
- **Convergence.** Rerun with the consensus wording removed from the prompts, and with roles writing independent first drafts.
- **Role placebos and a single-agent baseline.** Swap roles' titles or make them meaningless. Have one agent with the same firm, documents and task answer once, and report what team runs add beyond it, if anything.
- **Reasoning and agreement.** Code answers for positions, arguments and pushback, by hand or with a checked coder, since similarity scores cannot show these.
- **Problem space.** Pose the problem in the decision task, in neutral words, and check whether teams engage it. Our current task asks only what to develop and bring to market next. If teams still do not engage it, report that as a boundary result.
- **Grounding.** Audit citations and how widely documents are used. Run a neutral search against ours on one firm, and try sources other than CEO talks for non-CEO roles.
- **Recall and framing.** Masked firm names, reworded prompts, and the framing test.
- **Observation.** Compare blind (not told the research question) and embedded (told it) observers on the same deliberation, and test how much of each passage agents should see (now all of it; `TMT_PASSAGE_CHARS` sets a limit).
- **Provenance.** Use the provenance report in the coding scheme.
- **Reasoning traces.** Check them against behavior, since traces are not always faithful.

If a test fails, we revise the design and test again, and we report what failed. The main data then cover the pilot's 20 conditions, repeated, on the pinned model, with key scenarios rerun on other models, including an open-weight one.

## Future study: the firm's environment as a third dimension

The current design crosses context and task. A later study would add conditions the firm faces while deciding, real or hypothetical, arising from competitors, technology, the ecosystem or inside the firm. Researchers could draw them from observed phenomena, from existing theories, or from a mix, and could focus on conditions they notice that existing theories do not explain. Other dimensions of the firm's environment could follow. Conditions would be built into the environment, and not taken from our own pilot, which would be circular.

Today each run is one team deciding once, so we can compare teams across conditions but cannot watch one team change its mind. Observing maneuvering directly needs one team to decide, meet a change, and decide again with memory of its first choice.

## Corpus

The pilot's 127 documents stay as run, and a larger corpus would be a new version. We would first test coverage on one firm, comparing a repeat of the search with a neutral one, and expand only if that finds real gaps. Documents would be tagged by date and type, and a set period held out, because a claim cannot be tested on events the agents were given. Our search included "open" and "closed", so we will not read differences between firms as differences in openness until the neutral search has run.

## P3, later

- A browser interface for designing studies, and an assistant that walks researchers through study design.
- Other research designs: surveys, experiments, and studies with many agents.
- A semantic (meaning-based) check on debrief questions, and summarizing long runs to fit model context limits (the most text a model can take in during one call).
