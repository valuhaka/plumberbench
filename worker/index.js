// Cloudflare Worker for the PlumberBench site: serves the files in ./site,
// with main.html as the page for "/". Configured in wrangler.toml.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/") {
      url.pathname = "/main.html";
      return env.ASSETS.fetch(new Request(url, request));
    }
    return env.ASSETS.fetch(request);
  },
};
