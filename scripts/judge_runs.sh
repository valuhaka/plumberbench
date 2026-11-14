#!/usr/bin/env bash
# The runs the judges repeat, through Harbor (needs Docker running and a model key).
#
#   export ANTHROPIC_API_KEY=...          # or OPENAI_API_KEY, GEMINI_API_KEY, ...
#   ./scripts/judge_runs.sh anthropic/MODEL [task]
#
# Order: generate and lint every task, the vision smoke test (stop if it fails), then on the
# chosen task the reference run (oracle), the do-nothing and stop-early
# baselines, the close-the-main exploit, and three agent runs.
#
# OPENCODE_VERSION pins OpenCode (recommended once the smoke test passes with it).
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${1:?usage: judge_runs.sh provider/model [task]}"
TASK="harbor/tasks/${2:-l3-s007-facts}"
AGENT="${AGENT:-opencode}"
AGENT_KW=(--ak disable_web_search=true)
if [ -n "${OPENCODE_VERSION:-}" ]; then AGENT_KW+=(--ak "version=${OPENCODE_VERSION}"); fi
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
if command -v uv >/dev/null 2>&1; then PY=(uv run python3); else PY=(python3); fi

echo "== generate the task folders (harbor/tasks is not committed)"
"${PY[@]}" -m plumberbench.tasks --out harbor/tasks --levels 1 2 3 4 --seeds 0-9 --mode facts vision

echo "== lint"
harbor lint harbor/tasks/* harbor/smoke-vision

echo "== smoke test: do images reach the model, and stay fresh? (oracle, then 3 agent runs)"
harbor run -p harbor/smoke-vision -a oracle
harbor run -p harbor/smoke-vision -a "$AGENT" -m "$MODEL" "${AGENT_KW[@]}" -k 3

echo "== $TASK"
harbor run -p "$TASK" -a oracle
harbor run -p "$TASK" -a nop
harbor run -p "$TASK" -a pb_agents.baselines:StopEarlyAgent
harbor run -p "$TASK" -a pb_agents.baselines:CloseMainAgent
harbor run -p "$TASK" -a "$AGENT" -m "$MODEL" "${AGENT_KW[@]}" -k 3
