#!/usr/bin/env bash
# The runs the judges repeat, through Harbor (needs Docker and model credits).
#
#   ./scripts/judge_runs.sh <model> [task]
#   ./scripts/judge_runs.sh provider/model-name l3-s007-facts
#
# Order: the vision smoke test first (stop here if it fails), then on the chosen
# task the reference run (oracle), the do-nothing and stop-early baselines, the
# close-the-main exploit, and three agent runs.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${1:?usage: judge_runs.sh <model> [task]}"
TASK="harbor/tasks/${2:-l3-s007-facts}"
AGENT="${AGENT:-opencode}"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

echo "== smoke test: do images reach the model, and stay fresh? (3 runs)"
harbor run -p harbor/smoke-vision -a oracle
harbor run -p harbor/smoke-vision -a "$AGENT" -m "$MODEL" -k 3

echo "== $TASK"
harbor run -p "$TASK" -a oracle
harbor run -p "$TASK" -a nop
harbor run -p "$TASK" -a pb_agents.baselines:StopEarlyAgent
harbor run -p "$TASK" -a pb_agents.baselines:CloseMainAgent
harbor run -p "$TASK" -a "$AGENT" -m "$MODEL" -k 3
