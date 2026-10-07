// The app answers only on this computer. A browser tab opened at http://127.0.0.1:PORT (the address the launcher opens) and one opened at
// http://localhost:PORT are the same app, but the server may name itself either way, so comparing the Origin header with the server's own
// address rejected the launcher's own page ("Origin rejected": activation, payments, model download and Quit all failed).
// A request is accepted when it carries no Origin (not a browser page), the same origin as the server, or any loopback address with the
// same scheme and port. A page from another website, or another local program on a different port, is still refused.
const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function originAllowed(request: Request): boolean {
  const header = request.headers.get("origin");
  if (!header) return true;
  let origin: URL;
  try { origin = new URL(header); } catch { return false; }
  const self = new URL(request.url);
  if (origin.origin === self.origin) return true;
  return LOOPBACK.has(origin.hostname) && LOOPBACK.has(self.hostname) && origin.protocol === self.protocol && origin.port === self.port;
}
