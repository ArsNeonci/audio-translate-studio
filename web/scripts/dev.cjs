// `npm run dev`: the UI with hot reload, in front of the real local API.
//
//   browser -> proxy (this script, default http://localhost:3000)
//                 /api/*  -> the app's local API (worker/app_api.py), with the per-run token added
//                 the rest -> `next dev` (including its hot-reload WebSocket)
//
// The proxy keeps the Host header unchanged, so the API's origin checks see exactly what the browser used. Because the proxy
// holds the token, the browser needs no launch link. This is for development only: the installed app has no proxy and no
// Next.js at run time (the API serves the built UI and the browser signs in with the launcher's link).
// Options: --port N (the address you open, default 3000).
const { spawn } = require("node:child_process");
const { randomBytes } = require("node:crypto");
const { existsSync } = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const root = path.resolve(__dirname, "..");   // web/: the Next.js project
const repo = path.resolve(root, "..");        // the repository: worker/ (FastAPI) and .venv are beside web/
const at = process.argv.indexOf("--port");
const publicPort = at > 0 ? Number(process.argv[at + 1]) : 3000;
const nextPort = publicPort + 1;
const venv = path.join(repo, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.PYTHON_BIN || (existsSync(venv) ? venv : "python");
const token = randomBytes(32).toString("base64url");

const children = [];
const stop = (code) => { for (const child of children) if (child.exitCode === null) child.kill(); process.exit(code); };
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));

function forward(request, response, port, extra) {
  const upstream = http.request({ host: "127.0.0.1", port, method: request.method, path: request.url, headers: { ...request.headers, ...extra } }, (answer) => {
    response.writeHead(answer.statusCode, answer.headers);
    answer.pipe(response);
  });
  upstream.on("error", () => { if (!response.headersSent) response.writeHead(502, { "Content-Type": "text/plain" }); response.end("The backend is not ready yet."); });
  request.pipe(upstream);
}

function start(apiPort) {
  const nextBin = path.join(root, "node_modules", "next", "dist", "bin", "next");
  const next = spawn(process.execPath, [nextBin, "dev", "-p", String(nextPort), "-H", "127.0.0.1"], { cwd: root, stdio: "inherit" });
  children.push(next);
  next.on("exit", (code) => stop(code ?? 0));
  const server = http.createServer((request, response) => {
    const isApi = request.url === "/api" || request.url.startsWith("/api/") || request.url.startsWith("/api?");
    if (isApi) forward(request, response, apiPort, { "x-audio-api-token": token });
    else forward(request, response, nextPort, {});
  });
  server.on("upgrade", (request, socket, head) => {   // next dev's hot reload
    const upstream = net.connect(nextPort, "127.0.0.1", () => {
      const lines = Object.entries(request.headers).map(([key, value]) => `${key}: ${value}`);
      upstream.write(`${request.method} ${request.url} HTTP/1.1\r\n${lines.join("\r\n")}\r\n\r\n`);
      if (head.length) upstream.write(head);
      upstream.pipe(socket); socket.pipe(upstream);
    });
    upstream.on("error", () => socket.destroy());
    socket.on("error", () => upstream.destroy());
  });
  server.listen(publicPort, "127.0.0.1", () => console.log(`\nUI with hot reload: http://localhost:${publicPort}   (API on 127.0.0.1:${apiPort})`));
}

const api = spawn(python, [path.join(repo, "worker", "app_api.py"), "--port", "0"], {
  cwd: repo, env: { ...process.env, AUDIO_API_TOKEN: token }, stdio: ["ignore", "pipe", "inherit"],
});
children.push(api);
api.on("exit", (code) => { console.error(`local API exited (${code})`); stop(code ?? 1); });
let buffered = "", started = false;
api.stdout.on("data", (chunk) => {
  buffered += chunk;
  const match = /AUDIO_API_READY (\d+)/.exec(buffered);
  if (match && !started) { started = true; start(Number(match[1])); }
});
