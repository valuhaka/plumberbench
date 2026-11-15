// Cloudflare Worker for the PlumberBench site: serves the files in ./site,
// with main.html as the page for "/". Configured in wrangler.toml.
// plumberbench.org/play* belongs to the play Worker (worker/online/), whose route takes
// precedence; this one sees /play only while that is not deployed, and says how to play locally.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/") {
      url.pathname = "/main.html";
      return env.ASSETS.fetch(new Request(url, request));
    }
    if (url.pathname === "/play" || url.pathname.startsWith("/play/")) {
      url.pathname = "/play-offline.html";
      const page = await env.ASSETS.fetch(new Request(url, request));
      return new Response(page.body, { status: 503, headers: page.headers });
    }
    return env.ASSETS.fetch(request);
  },
};
