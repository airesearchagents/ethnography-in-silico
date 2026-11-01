#!/bin/bash
# A batch driver from development, not maintained and not the recommended way to
# run (a batch runner is planned; see ROADMAP.md). It starts four paid runs at once,
# with no confirmation step. Scoring (--judge) is optional and not part of the
# method in the proposal.
#
# Drive four live research sessions (one per provider) with the
# Phase-5 openness-judge ensemble enabled.
#
# Each cell pairs a different TMT provider with a different scenario
# from the 2x2 study design:
#
#   cell_1_gemini    OpenAI    / gemini_pro / Dynamic / Novel       / 2030
#   cell_2_claude    Anthropic / claude     / Stable  / Novel       / 2032
#   cell_3_openai    Google    / openai     / Dynamic / Enhancement / 2030
#   cell_4_deepseek  Mistral   / deepseek   / Dynamic / Novel       / 2030
#
# The year column is only logged: the script does not pass it on, so every
# cell runs in the session's default year (2030).
#
# Phase 5 always uses the four judges in `providers.JUDGE_PROVIDERS` (gemini_pro,
# claude, openai and deepseek) regardless of which provider drove the deliberation.
#
# DeepSeek rejects a json_schema `response_format`, so `providers.py` has a
# per-provider structured-output adapter that sends json_object and puts the
# Pydantic schema in the prompt. DeepSeek then runs like any other LiteLLM-routed
# provider.
#
# Outputs land in `results/runs/<run_id>/` per cell; per-cell live
# logs go to `results/runs/_logs/<label>.log`. Tail any of those to
# watch the run in real time.

set -e

# Source the session-local keys (gitignored).
if [ -f .env.runlocal ]; then
    set -a
    source .env.runlocal
    set +a
fi

# Also source the user's existing .env.local if present (typically
# carries GOOGLE_API_KEY for the observer + gemini judge).
if [ -f .env.local ]; then
    set -a
    source .env.local
    set +a
fi

# Ensure the output tree exists.
mkdir -p results/runs/_logs

# Fail fast if any required key is missing.
require_key() {
    local name=$1
    if [ -z "${!name}" ]; then
        echo "ERROR: $name not set; cannot run cells that need it." >&2
        exit 1
    fi
}
require_key GOOGLE_API_KEY     # observer is pinned to gemini_pro
require_key ANTHROPIC_API_KEY  # claude cell + judge ensemble
require_key OPENAI_API_KEY     # openai cell + judge ensemble
require_key DEEPSEEK_API_KEY   # deepseek cell

# Python interpreter that has the project's deps (pydantic, google-adk,
# google-genai, litellm). On this machine that's /Library/Frameworks
# Python 3.10; override via PY=... when invoking the script if your
# layout differs.
PY="${PY:-/Library/Frameworks/Python.framework/Versions/3.10/bin/python3}"
if [ ! -x "${PY}" ]; then
    echo "ERROR: Python interpreter not found at ${PY}." >&2
    echo "       Pass PY=/path/to/python3 on the command line." >&2
    exit 1
fi

# One cell — runs the CLI with --judge and tags the log with a label.
run_cell() {
    local label=$1
    local provider=$2
    local company=$3
    local industry=$4
    local product=$5
    local year=$6
    local log="results/runs/_logs/${label}.log"
    {
        echo "===== START $(date -u +'%Y-%m-%dT%H:%M:%SZ') ${label} ====="
        echo "provider=${provider} company=${company} industry=${industry} product=${product} year=${year}"
        TMT_PROVIDER="${provider}" "${PY}" run_research_session.py \
            --judge \
            --company "${company}" \
            --industry-context "${industry}" \
            --product-type "${product}" \
            --out-dir results/runs
        echo "===== END   $(date -u +'%Y-%m-%dT%H:%M:%SZ') ${label} ====="
    } > "${log}" 2>&1
}

echo "Launching 4 cells in parallel. Monitor with:"
echo "  tail -f results/runs/_logs/cell_1_gemini.log"
echo "  tail -f results/runs/_logs/cell_2_claude.log"
echo "  tail -f results/runs/_logs/cell_3_openai.log"
echo "  tail -f results/runs/_logs/cell_4_deepseek.log"
echo

run_cell cell_1_gemini   gemini_pro OpenAI    Dynamic Novel       2030 &
PID_GEM=$!
run_cell cell_2_claude   claude     Anthropic Stable  Novel       2032 &
PID_CLA=$!
run_cell cell_3_openai   openai     Google    Dynamic Enhancement 2030 &
PID_OAI=$!
run_cell cell_4_deepseek deepseek   Mistral   Dynamic Novel       2030 &
PID_DEE=$!

# Capture each PID so we can report which cell failed (if any).
wait $PID_GEM; STATUS_GEM=$?
wait $PID_CLA; STATUS_CLA=$?
wait $PID_OAI; STATUS_OAI=$?
wait $PID_DEE; STATUS_DEE=$?

echo
echo "===== ALL CELLS COMPLETE ====="
echo "  cell_1_gemini   exit=${STATUS_GEM}  log=results/runs/_logs/cell_1_gemini.log"
echo "  cell_2_claude   exit=${STATUS_CLA}  log=results/runs/_logs/cell_2_claude.log"
echo "  cell_3_openai   exit=${STATUS_OAI}  log=results/runs/_logs/cell_3_openai.log"
echo "  cell_4_deepseek exit=${STATUS_DEE}  log=results/runs/_logs/cell_4_deepseek.log"

# Sum non-zero exits — propagate failure if any cell failed.
TOTAL=$((STATUS_GEM + STATUS_CLA + STATUS_OAI + STATUS_DEE))
if [ "${TOTAL}" -ne 0 ]; then
    echo "WARNING: at least one cell failed; check logs above."
    exit 1
fi
echo "All 4 cells succeeded."
