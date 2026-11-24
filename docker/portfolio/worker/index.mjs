export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    url.protocol = "http:";
    url.host = "127.0.0.1:14200";
    // Keep redirects in the browser so credentials stay on this origin.
    return env.PORTFOLIO.fetch(new Request(url, request), { redirect: "manual" });
  },
};
