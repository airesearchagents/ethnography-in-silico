# Frontier-model execution sweep

**Status.** Archived plan from an earlier design, kept for the record. It is not the plan in the proposal, whose method is human coding of the records; scoring (`--judge`) is optional and not part of it. For the current plan see [`ROADMAP.md`](../../../ROADMAP.md). Call counts, model names and prices below date from May 2026; a run now makes about 200 calls, and the OpenAI judge is now `gpt-5.4`.

The design uses frontier models (each company's newest, most capable models). It is a sweep, or planned set of runs: six providers (suppliers of models) × 20 cells (combinations of firm, industry context and product type) × 2 conditions (without and with document search) = 240 runs (a run is one complete simulated meeting and debrief). A smaller design on one TMT (top management team: the six simulated executives) provider, Gemini 3.1 Pro Preview, an early release of Google's language model, via Vertex AI, Google's paid cloud service, is recorded in `DECISIONS.md` §19. The architectural framework (the shared software in this repository) supports either scope without code changes.

This file specifies the per-cell token model (an estimate of usage, not a language model; a token is a small piece of text, often about three-quarters of a word, that providers charge by) derived from the live shakeout runs (early test runs calling real models) in May 2026, and the total cost estimate (covers both the 20-cell single-vendor run and the optional 240-cell six-vendor extension). Terms are defined in [`docs/GLOSSARY.md`](../../../docs/GLOSSARY.md).

**The cost estimates below are out of date and too low.** Later runs on `gemini-3.1-pro-preview` at list prices (published rates) measured about $20 of Google charges for an ungrounded run (no documents) with optional scoring (scoring on other vendors is extra) and about $67 for a grounded run (the simulated executives receive and cite a firm's documents), at 38–90 minutes each, before a fix that brings a grounded run to an estimated $15, and a corpus store (the documents as loaded into Google's search service) also bills while it exists (see [`docs/10_rag_repo_plan.md`](../../../docs/10_rag_repo_plan.md) § Cost). Budget from those figures, which also age quickly.

---

## 1. What the framework last ran

Source: the logs (running records written by the software) `results/runs/_logs/cell_{1,2,3,ollama}_*.log` from 2026-05-23. The most recent live multi-cell sweep used:

| Cell | Provider | Model called | Status |
|---|---|---|---|
| 1 | Google | `gemini-2.5-pro` | Clean run; representative event counts |
| 2 | Anthropic | `claude-sonnet-4-6` | Tier-rate-limited (capped by the provider's limit per minute; only 11 deliberation events) |
| 3 | OpenAI | `gpt-5` | Clean |
| ollama | Local | `qwen3.5:9b` | Clean (local smoke test: a quick first run to confirm nothing breaks) |

Cell 1 produced **109 LLM calls** (one prompt sent to a large language model and one reply back) end-to-end across all five phases. That's the representative shape for the per-cell token model below; Cell 2's truncation by Claude tier limits is treated as a lower bound and addressed in the risk register (§7).

---

## 2. The frontier lineup (May 2026)

Three premium TMT-side providers (cross-vendor robustness), two budget providers (price-floor + reproducibility for labs without GCP, or Google Cloud Platform, credits), one local model (offline-replication reference, running on your own computer). Prices are list prices in dollars per million tokens of input (text sent to the model) and output (text it returns):

| Tier | Provider | Model | Input $/M | Output $/M |
|---|---|---|---:|---:|
| **Premium** | Anthropic | `claude-opus-4-7` (released Apr 16, 2026) | 5.00 | 25.00 |
| **Premium** | OpenAI | `gpt-5.4` (TMT side only) | 2.50 | 15.00 |
| **Premium** | Google | `gemini-3.1-pro-preview` | 2.00 / 4.00¹ | 12.00 |
| **Budget** | DeepSeek | `deepseek-v4` (released Mar 2026) | 0.30 | 0.50 |
| **Budget** | Groq (hosts open-weight models, whose trained numbers are public) | `llama-4-maverick` | 0.50 | 0.77 |
| **Local** | Ollama (runs models on your own computer) | `qwen3.5:9b` | 0 | 0 |
| **Judges (pinned: fixed to these models)** | Anthropic | `claude-opus-4-7` | 5.00 | 25.00 |
| **Judges (pinned)** | OpenAI | `gpt-5.5` | 5.00 | 30.00 |
| **Judges (pinned)** | Google | `gemini-3.1-pro-preview` | 2.00 / 4.00¹ | 12.00 |

¹ Gemini 3.1 Pro is tiered: $2/$12 ≤200K input tokens; $4/$? above. The framework's largest single LLM call (the Phase-3 observer, in which the researcher agent, a language model that watches the team, writes one summary of the discussion) typically stays under 200K, but watch the Phase-5 judge inputs on long debriefings (the researcher agent's interviews of the team).

### Why these models specifically

- **Claude Opus 4.7** is the strongest reasoning model currently available; the methodological-evidence story for premium-tier TMT deliberation rests on it. The April 2026 tokenizer (how a provider splits text into tokens) change means prior Sonnet 4.6 runs are not directly comparable; this sweep re-baselines.

- **GPT-5.4 for TMT, GPT-5.5 for judges.** GPT-5.5's 2× output-token price (vs 5.4) is steep relative to the quality improvement on TMT- side prompts (the text sent to a model) that are largely structured-output (replies forced into fixed, named fields). Pinning the premium GPT-5.5 to the judges keeps the construct-validity claim on the frontier flagship; using 5.4 for the bulk of TMT calls saves ~$30 per sweep.

- **Gemini 3.1 Pro** is Google's current Pro tier; routed through Vertex AI to bill GCP EDU credits (education credits on Google's cloud) rather than an AI Studio key (a secret access code for Google's direct service). 3.5 Flash is newer but Pro-tier is what the methods-section claim needs (the cross-vendor judges are pinned premium).

- **DeepSeek V4** is the cheapest hosted budget option that supports structured output via `json_object` mode (its way of forcing replies into fixed fields). Provides the price-floor data point — *if* the construct can be measured on a 1/50th-cost TMT, the framework is genuinely portable.

- **Llama 4 Maverick on Groq** is open-weight + fast inference (generating replies quickly). The "labs without paid API (the way programs reach a provider's model) budgets can replicate" data point.

- **qwen3.5:9b on Ollama** is the offline-replication reference. Establishes the framework runs without any commercial API.

---

## 3. Per-cell token model (derived from the May-23 run)

From the Cell 1 (`gemini-2.5-pro`) event counts × actual framework prompt sizes:

| Phase | Calls | In tokens / call | Out tokens / call | In subtotal | Out subtotal |
|---|---:|---:|---:|---:|---:|
| 1. Deliberation | ~42 | 2,500 | 350 | 105 k | 14.7 k |
| 2. Artefacts (strategy documents) | 6 | 6,500 | 1,400 | 39 k | 8.4 k |
| 3. Observation | 1 | 12,500 | 2,200 | 12.5 k | 2.2 k |
| 4. Debriefing | ~49 | 4,500 | 400 | 220 k | 19.6 k |
| 5. Judging (×3) | 3 | 25,000 | 3,000 | 75 k | 9 k |
| FieldNoter (the researcher agent's running notes) | ~8 | 2,000 | 300 | 16 k | 2.4 k |
| **Total per cell** | **~109** | | | **~467 k** | **~56 k** |

Ratio ≈ 8:1 input-to-output. Phase 4 and Phase 5 dominate the input side.

With `--rag` (RAG, retrieval-augmented generation: searching documents and adding the passages found to a model's prompt) enabled: add ~312 k input per cell for the REFERENCE MATERIAL prompt blocks (~1.25 k tokens × ~250 retrieval-bearing calls).

---

## 4. Cost estimate — 20 cells per provider (5 firms × 4 cells)

### TMT-side cost per 20-cell sweep

(Without judges; judges add a separate fixed cost — see below.)

| Provider × model | No-RAG | + RAG | Notes |
|---|---:|---:|---|
| Claude Opus 4.7 | ~$100 | ~$142 | × 1.35 multiplier for new tokenizer |
| GPT-5.4 (TMT) | ~$40 | ~$56 | Saves vs GPT-5.5 |
| Gemini 3.1 Pro | ~$32 | ~$45 | EDU-credit billed via Vertex |
| DeepSeek V4 | ~$3.40 | ~$5.00 | Cheapest hosted |
| Llama 4 Maverick (Groq) | ~$5.45 | ~$8.00 | Fast inference |
| qwen3.5:9b (Ollama) | $0 | $0 | Local |

### Judge-ensemble cost (independent of TMT-side provider)

Pinned to (Opus 4.7 + GPT-5.5 + Gemini 3.1 Pro). One ensemble run per cell:

- Per cell: 3 judges × ~25 k input × $5/M average + 3 × ~3 k output × $23/M average ≈ **~$0.96 per cell**
- Per 20-cell sweep: **~$19**
- Per 6-provider × 20-cell sweep: **~$115** (judges run once per cell × 6 providers)

### Total estimated cost

For the full Option B sweep (6 providers × 20 cells × 2 conditions = 240 runs):

| Component | Cost |
|---|---:|
| Premium TMT (Opus + GPT-5.4 + Gemini 3.1 Pro), no-RAG + RAG | ~$245 |
| Budget TMT (DeepSeek V4 + Llama 4 Maverick), no-RAG + RAG | ~$25 |
| Local TMT (qwen3.5:9b) | $0 |
| Judges across 120 cells × 2 conditions (judges always pinned, run on every cell) | ~$115 |
| **Total** | **~$385** |

EDU-credit offset: Gemini 3.1 Pro (TMT + judge) and the Vertex RAG retrieval calls route through GCP. Estimated **EDU credit usage: ~$80–100**; **actual cash spend ~$285** (Anthropic + OpenAI APIs).

Well within the $1k GCP budget. Anthropic and OpenAI APIs spend is the only line that hits cash.

---

## 5. Wall-clock estimate

Wall-clock means real elapsed time. Per cell at default `--max-exchanges 20` (a debrief stops at 20 exchanges, each one question and its replies):

| Provider | Per-cell wall-clock | Notes |
|---|---|---|
| Claude Opus 4.7 | ~30–45 min | Tier-rate-limited under TPM=30k (tokens per minute; Tier 1) |
| GPT-5.4 | ~20–25 min | Better rate limits at tier 1 |
| Gemini 3.1 Pro | ~20–25 min | EDU-credit account has higher limits |
| DeepSeek V4 | ~30 min | Slower-but-cheap |
| Llama 4 Maverick | ~10–15 min | Fastest (Groq's LPU chips) |
| qwen3.5:9b (Ollama) | ~60–120 min | Local CPU/GPU bound (limited by your computer's processors) |

For 20 cells per provider × 2 conditions = 40 runs:

- Premium 3 providers: ~20–30 hours total if sequential per provider, ~10–15 hours if parallel across providers (limited by Claude tier).
- Budget 2 providers: ~10–15 hours total.
- Local: 40–80 hours (this is the slow one).

**Recommended schedule:** start the three premium providers in parallel on Day 1 (overnight); start the two budget providers on Day 2 (overnight); start the local Ollama runs as a background job that can spread over Days 1–4. Total elapsed: **~3–4 days, mostly unattended**.

---

## 6. Code changes the sweep needs

Small. One PR (pull request: a proposed set of code changes):

1. **Bump `_DEFAULTS` in `providers.py`** to current model IDs:

```python
_DEFAULTS = {
    "gemini_pro":   "gemini-3.1-pro-preview",      # was gemini-2.5-pro
    "gemini_flash": "gemini-3.5-flash",            # was gemini-2.5-flash
    "claude":       "claude-opus-4-7",             # was claude-sonnet-4-6
    "openai":       "gpt-5.4",                     # was gpt-5
    "deepseek":     "deepseek/deepseek-chat-v4",   # was deepseek-chat
    "groq":         "groq/llama-4-maverick",       # was llama-3.3-70b-versatile
    "ollama":       "ollama_chat/qwen3.5:9b",      # unchanged
}
```

2. **Add a dedicated judge-side override** so the construct-judge ensemble uses GPT-5.5 while the TMT-side uses GPT-5.4:

```python
# In providers.py
JUDGE_MODEL_OVERRIDES = {
    "openai": "gpt-5.5",   # judges get the premium tier
}

def get_judge_model(provider: str) -> str:
    """Resolve the model for a judge agent — may differ from the team-wide
    `get_model(provider)` to put the strongest model on the construct-
    validity ensemble independent of TMT-side cost choices."""
    return JUDGE_MODEL_OVERRIDES.get(provider, get_model(provider))
```

Then in `roles/construct_judge.py::create_construct_judge_agent`, call `get_judge_model(provider)` instead of `get_model(provider)`.

3. **Add the sweep script** `scripts/run_frontier_sweep.sh`:

```bash
#!/usr/bin/env bash
# Drive the Option B frontier sweep. ~3-4 days total, mostly unattended.
# Source .env.local first to set provider keys + GCP credentials.

set -euo pipefail
FIRMS=(OpenAI Meta Alphabet Anthropic HuggingFace)
CELLS=("Dynamic Novel" "Dynamic Enhancement" "Stable Novel" "Stable Enhancement")
PROVIDERS=(claude openai gemini_pro deepseek groq ollama)

for prov in "${PROVIDERS[@]}"; do
  for firm in "${FIRMS[@]}"; do
    for cell in "${CELLS[@]}"; do
      read ind prod <<< "$cell"
      for rag in "" "--rag"; do
        TMT_PROVIDER=$prov python3 run_research_session.py \
          --company "$firm" --industry-context "$ind" --product-type "$prod" \
          --judge --vertex $rag \
          --out-dir "results/runs" \
        || echo "FAIL $prov $firm $ind $prod $rag"  # continue on failure
      done
    done
  done
done
```

4. **Capture the framework's default model IDs in the manifest** (a file recording what produced a run) so a reviewer can tell whether a given run used the framework's default or an override. Add `default_models: Dict[str, str]` to `ReplicationManifest` populated from `providers._DEFAULTS` at manifest-construction time.

5. **One-cell smoke test per new provider model** before the full sweep — catch any structured-output regression (something that used to work breaking) on DeepSeek V4 / Llama 4 Maverick / Claude Opus 4.7 (the latter has a different tokenizer + ostensibly the same response format, but verify).

These are small mechanical changes. **No methodological code changes** — the orchestrator (the code that runs the phases), schemas (templates of required fields), persistence layer (the code that saves records) all stay. What changes is the model-IDs the framework resolves.

---

## 7. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Claude Opus 4.7 tier-rate-limit** stalls the sweep | High | Phase 1 takes 60+ min/cell | Set the global token-bucket throttle (a limiter on tokens sent per minute; `orchestrator/rate_limit.py`) *before* this sweep starts. |
| **GPT-5.5's 2× output cost** for judges blows budget if Phase 5 outputs are larger than estimate | Medium | Budget +$20–30 | Cap judge output length via prompt instruction; verify on one cell before sweep. |
| **DeepSeek V4 / Llama 4 Maverick** changed structured-output behaviour vs V3 / 3.3 | Medium | Budget cells fail | One-cell smoke per new provider model first. |
| **Vertex RAG corpus quota** if 240 runs × ~250 retrievals each = ~60k retrievals exceeds tier | Low | RAG cells throttle | Pre-warm GCP quota; sequential per provider. |
| **Opus 4.7 35%-more-tokens tokenizer** pushes Phase 5 judge input above 200k (Gemini tier) | Low | Gemini judge cost doubles for that cell | If hit, fall back to Sonnet 4.6 in judges (still cross-vendor; just less premium). |
| **Provider model deprecation** mid-sweep (model IDs occasionally get retired with short notice) | Low | Sweep aborts | Manifest captures resolved model ID at run-time; if deprecation happens, pin the older ID via per-role override env vars (environment variables: named settings held outside the code). |

---

## 8. What the sweep was designed to compare

The design compares six providers and the two document-search conditions: whether judges agree across vendors, which firm excerpts agents drew on with retrieval, and whether cheaper or local models give comparable records.

---

## 9. What to do after this plan is approved

In order:

1. Review this document. Push back on anything that's wrong.
2. Open a small PR with the provider-default bumps + the `get_judge_model` override + the sweep script + the manifest `default_models` field. ~3 hours of work.
3. One-cell smoke tests per new provider model (~$2 total).
4. Set the global token-bucket throttle (`orchestrator/rate_limit.py`).
5. Kick off the full sweep overnight. Three days elapsed.
6. Run `python -m analysis.compare_rag` against the resulting 240 per-run folders. Outputs land in `results/comparisons/<timestamp>/`.
7. Read the per-pair grounded-claims MDs (Markdown files, plain text with simple formatting marks) as your qualitative field-data analysis.

Estimated total wall-clock from approval to coded results: **5–7 days**. Most of that is the sweep itself running unattended.
