# Running models without Docker

`plumberbench.agent` starts one MCP server per episode and drives a model through it with the same tools, pictures and text as in Harbor. It is quicker than Harbor, but its agent loop is not OpenCode's, so confirm a few tasks through Harbor.

```bash
export ANTHROPIC_API_KEY=...
uv run -m plumberbench.agent smoke --provider anthropic --model MODEL --repeat 3
uv run -m plumberbench.agent run --provider anthropic --model MODEL --levels 1 2 3 4 --seeds 0-1 --mode facts vision
```

| Provider | What it uses | Needs |
|---|---|---|
| `anthropic` | the Messages API, with prompt caching | `ANTHROPIC_API_KEY` |
| `openai` | any OpenAI-compatible Chat Completions endpoint (`--base-url`, `--key-env`); OpenAI's newer models call tools there only with `--reasoning-effort none` | `OPENAI_API_KEY` or `--key-env` |
| `openai-agents` | the OpenAI Agents SDK over the Responses API: reasoning stays on, pictures arrive inside tool results, runs appear as traces in the OpenAI dashboard | `uv run --extra agents`, `OPENAI_API_KEY` |
| `codex` | `codex exec` against the server, signed in however Codex is (a ChatGPT plan works); shell, sub-agents, web search and your own Codex settings are off, PlumberBench's tools approved; `--model` optional | `npm install -g @openai/codex`, `codex login` |

Gemini through its OpenAI-compatible endpoint:

```bash
uv run -m plumberbench.agent run --provider openai --model MODEL --base-url https://generativelanguage.googleapis.com/v1beta/openai/ --key-env GEMINI_API_KEY
```

`smoke` checks pictures reach the model (PASS, STALE or BLIND). `run` writes `runs/<provider>-<model>-<time>/`: per episode the server log, transcript, replay page and summary, plus a summary table. A run stops at the first job that fails before any tool call (a bad model name, key or sign-in).

## Adding a run to the website

```bash
uv run -m plumberbench.results add runs/codex-MODEL-TIME --label "MODEL (Codex)"
uv run -m plumberbench.results show
uv run -m plumberbench.demo
```

`results/models/<label>.json` collects a model's jobs across runs (adding a run twice replaces it). `show` prints accuracy and spend per model; `demo` redraws the site.
