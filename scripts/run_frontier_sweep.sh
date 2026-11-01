#!/bin/bash
# Superseded plan, kept for the record. The proposal's method is hand coding of
# the records; scoring (--judge) is optional and not part of it, and every run
# below passes it. For the current plan see ROADMAP.md.
#
# Drive the frontier-model execution sweep specified in
# `studies/openness_maneuvering/docs/03_frontier_sweep_plan.md`:
#
#   5 firms × 4 cells × 2 conditions (no-RAG, RAG) × 6 providers
#   = 240 runs total
#
# Premium TMT providers (cross-vendor robustness):
#   gemini_pro → gemini-3.1-pro-preview (Vertex AI)
#   claude     → claude-opus-4-7    (Anthropic)
#   openai     → gpt-5.4
#
# Budget TMT providers (price-floor + reproducibility):
#   deepseek   → deepseek-v4-flash
#   groq       → llama-4-maverick
#
# Local TMT provider (offline-replication reference):
#   ollama     → qwen3.5:9b
#
# Judges always run on the four-model ensemble in `providers.JUDGE_PROVIDERS`
# (Gemini Pro, Claude, GPT-5.4 and DeepSeek's reasoning model) regardless of which
# provider drove the deliberation. See `providers.JUDGE_MODEL_OVERRIDES`.
#
# Estimated wall-clock: about a week or more one run at a time, at about 40 minutes to an
# hour per run on Gemini. The Claude side is the slowest (its default limit is
# 30K tokens per minute); `orchestrator/rate_limit.py` queues calls to stay under
# each provider's limit.
#
# Estimated cost: far above the plan's old ~$385. One run on
# gemini-3.1-pro-preview measured about $20 ungrounded with optional scoring
# and about $67 grounded, and we now estimate about $15 for a grounded run, so
# 240 runs on such a model is about $3,600 to $4,800 or more,
# plus scoring on other vendors. Model names above follow `providers._DEFAULTS`.
# Needs --yes to start.
#
# Outputs land in `results/runs/<run_id>/` per run; per-cell live
# logs go to `results/runs/_logs/<provider>_<firm>_<cell>_<rag>.log`.

set -uo pipefail   # no -e; we want to continue past individual cell failures

# ----- Provider keys -----------------------------------------------------
if [ -f .env.runlocal ]; then
    set -a
    source .env.runlocal
    set +a
fi
if [ -f .env.local ]; then
    set -a
    source .env.local
    set +a
fi

mkdir -p results/runs/_logs

PY="${PY:-$(command -v python3)}"
if [ ! -x "${PY}" ]; then
    echo "ERROR: Python interpreter not found at ${PY}." >&2
    echo "       Pass PY=/path/to/python3 on the command line." >&2
    exit 1
fi

# ----- Sweep dimensions --------------------------------------------------
FIRMS=(OpenAI Meta Alphabet Anthropic HuggingFace)
CELLS=("Dynamic Novel" "Dynamic Enhancement" "Stable Novel" "Stable Enhancement")

# Provider order — premium first (more interesting failure-mode signal
# if anything regresses), then budget, then local. Each provider runs
# sequentially through all 40 of its cells before moving on; providers
# can be parallelised across separate invocations if you have the
# bandwidth + the rate-limit budget.
PROVIDERS=(claude openai gemini_pro deepseek groq ollama)

# ----- Optional fast-forward arguments -----------------------------------
# Pass --providers=<comma_list> to limit which providers run, useful
# for resuming a partial sweep or for the one-cell smoke test pass.
ONLY_PROVIDERS=""
ONLY_FIRMS=""
DRY_RUN=""
CONFIRMED=""
for arg in "$@"; do
    case "$arg" in
        --providers=*)   ONLY_PROVIDERS="${arg#*=}";;
        --firms=*)       ONLY_FIRMS="${arg#*=}";;
        --dry-run)       DRY_RUN="1";;
        --yes)           CONFIRMED="1";;
        *) echo "Unknown flag: $arg (supported: --providers=..., --firms=..., --dry-run, --yes)"; exit 1;;
    esac
done
if [ -z "$DRY_RUN" ] && [ -z "$CONFIRMED" ]; then
    echo "This starts up to 240 paid runs, about \$4,800 or more at current measures." >&2
    echo "Use --dry-run to list them, or --yes to start." >&2
    exit 1
fi

provider_in_filter() {
    local p="$1"
    if [ -z "$ONLY_PROVIDERS" ]; then return 0; fi
    [[ ",${ONLY_PROVIDERS}," == *",${p},"* ]]
}
firm_in_filter() {
    local f="$1"
    if [ -z "$ONLY_FIRMS" ]; then return 0; fi
    [[ ",${ONLY_FIRMS}," == *",${f},"* ]]
}

# ----- Per-run wrapper ---------------------------------------------------
run_one() {
    local provider="$1"
    local firm="$2"
    local industry="$3"
    local product="$4"
    local rag="$5"   # "" or "--rag"
    local rag_tag
    if [ -n "$rag" ]; then rag_tag="rag"; else rag_tag="norag"; fi
    local label="${provider}_${firm}_${industry}_${product}_${rag_tag}"
    local log="results/runs/_logs/${label}.log"

    if [ -n "$DRY_RUN" ]; then
        echo "DRY-RUN $label"
        return 0
    fi

    {
        echo "===== START $(date -u +'%Y-%m-%dT%H:%M:%SZ') ${label} ====="
        echo "provider=${provider} firm=${firm} industry=${industry} product=${product} rag=${rag:-off}"
        TMT_PROVIDER="${provider}" "${PY}" run_research_session.py \
            --judge \
            --vertex \
            --company "${firm}" \
            --industry-context "${industry}" \
            --product-type "${product}" \
            --out-dir results/runs \
            ${rag} \
        ; local exit_code=$?
        echo "===== END   $(date -u +'%Y-%m-%dT%H:%M:%SZ') ${label} exit=${exit_code} ====="
        return $exit_code
    } > "${log}" 2>&1
}

# ----- Drive the sweep ---------------------------------------------------
TOTAL_RUNS=0
SUCCESSES=0
FAILURES=0
FAILED_LABELS=()

START_TS=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
echo "===== FRONTIER SWEEP START ${START_TS} ====="
echo "Providers:   ${PROVIDERS[*]}"
echo "Firms:       ${FIRMS[*]}"
echo "Cells:       ${CELLS[*]}"
echo "Conditions:  no-RAG, RAG"
echo "Filters:     providers='${ONLY_PROVIDERS:-all}' firms='${ONLY_FIRMS:-all}'"
echo "Dry-run:     ${DRY_RUN:-no}"
echo

for prov in "${PROVIDERS[@]}"; do
    if ! provider_in_filter "$prov"; then continue; fi
    echo "----- Provider: ${prov} -----"
    for firm in "${FIRMS[@]}"; do
        if ! firm_in_filter "$firm"; then continue; fi
        for cell in "${CELLS[@]}"; do
            read -r ind prod <<< "$cell"
            for rag in "" "--rag"; do
                TOTAL_RUNS=$((TOTAL_RUNS+1))
                rag_tag=$([ -n "$rag" ] && echo "rag" || echo "norag")
                label="${prov}_${firm}_${ind}_${prod}_${rag_tag}"
                echo "  [${TOTAL_RUNS}] ${label}"
                if run_one "$prov" "$firm" "$ind" "$prod" "$rag"; then
                    SUCCESSES=$((SUCCESSES+1))
                else
                    FAILURES=$((FAILURES+1))
                    FAILED_LABELS+=("$label")
                fi
            done
        done
    done
done

END_TS=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
echo
echo "===== FRONTIER SWEEP END   ${END_TS} ====="
echo "Total runs:  ${TOTAL_RUNS}"
echo "Successes:   ${SUCCESSES}"
echo "Failures:    ${FAILURES}"
if [ "${FAILURES}" -gt 0 ]; then
    echo "Failed runs (check logs):"
    for f in "${FAILED_LABELS[@]}"; do
        echo "  - ${f}  (log: results/runs/_logs/${f}.log)"
    done
fi
echo
echo "Next step: python -m analysis.compare_rag"
echo "  → emits per-pair MDs + cross-pair summary under results/comparisons/<ts>/"

if [ "${FAILURES}" -gt 0 ]; then exit 1; fi
exit 0
