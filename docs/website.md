# The website

`site/` is a static site served by a Cloudflare Worker (`worker/index.js`, `wrangler.toml`) at [plumberbench.org](https://plumberbench.org).

- `site/main.html` is the pitch, one screen per section; the arrow keys step through them when presenting.
- `site/demo.html` is a step-through replay of the reference plumber on house 7, level 3.
- `site/img/` holds the pictures.
- `/play/` is the game, served by a second Worker (`worker/online/`) in front of a container (`Dockerfile`, `python -m plumberbench.online`). Each visitor gets a house of their own by cookie: level 1 and a random seed, or `?level=1..4&seed=N`.

Every figure is drawn from the repo: frames from the demo run (their captions are checked against its log), pictures rendered from the simulator, scores from `results/ladder.json` and `results/models/`.

```bash
uv run -m plumberbench.demo
npx wrangler dev
npx wrangler deploy
```

`demo` rebuilds both pages and the pictures; `wrangler dev` previews at `localhost:8787`; `wrangler deploy` publishes (`npx wrangler login` once first).

## Online play

The play Worker owns the route `plumberbench.org/play*`, which takes precedence over the site's Worker; until it is deployed, the site answers `/play` with `site/play-offline.html` (the local command). It needs the Workers Paid plan, since Containers are not on the free one, and Docker (or Colima) running to build the image:

```bash
cd worker/online
npm install
npx wrangler deploy
```

The first deploy takes a few minutes while the image is provisioned. To deploy on every push instead, connect a second Worker to the repo in Workers Builds with root directory `worker/online`; its default `npx wrangler deploy` builds the image there. One `standard-1` instance (1/2 vCPU) serves everyone, about 0.4 s per picture, and sleeps after 30 minutes without a request; open houses go with it. The image runs anywhere that runs a Linux container on port 8080:

```bash
docker build -t plumberbench-play .
docker run -p 8080:8080 plumberbench-play
```
