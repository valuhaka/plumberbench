# The website

`site/` is a static site served by a Cloudflare Worker (`worker/index.js`, `wrangler.toml`) at [plumberbench.org](https://plumberbench.org).

- `site/main.html` is the pitch, one screen per section; the arrow keys step through them when presenting.
- `site/demo.html` is a step-through replay of the reference plumber on house 7, level 3.
- `site/img/` holds the pictures.

Every figure is drawn from the repo: frames from the demo run (their captions are checked against its log), pictures rendered from the simulator, scores from `results/ladder.json` and `results/models/`.

```bash
uv run -m plumberbench.demo
npx wrangler dev
npx wrangler deploy
```

`demo` rebuilds both pages and the pictures; `wrangler dev` previews at `localhost:8787`; `wrangler deploy` publishes (`npx wrangler login` once first).
