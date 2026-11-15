// plumberbench.org/play*: every visitor goes to the same container, which keeps a house
// per visitor (by cookie) and closes houses after 30 idle minutes. Configured in wrangler.toml.
import { Container, getContainer } from "@cloudflare/containers";

export class PlayServer extends Container {
  defaultPort = 8080;
  sleepAfter = "30m";
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/play") {
      url.pathname = "/play/";
      return Response.redirect(url.toString(), 301);
    }
    if (!url.pathname.startsWith("/play/")) {
      return new Response("Not found", { status: 404 });
    }
    url.pathname = url.pathname.slice("/play".length);
    return getContainer(env.PLAY, "main").fetch(new Request(url, request));
  },
};
