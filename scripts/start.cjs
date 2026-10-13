// `npm start`: the built UI (./out, from `npm run build`) served by the local API, as the installed app runs it.
// Prints the one link that signs the browser in (it holds this run's token). Options: --port N (default 3210).
const { spawn } = require("node:child_process");
const { randomBytes } = require("node:crypto");
const { existsSync } = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const ui = path.join(root, "out");
if (!existsSync(path.join(ui, "index.html"))) { console.error("No build yet: run `npm run build` first."); process.exit(1); }
const at = process.argv.indexOf("--port");
const port = at > 0 ? Number(process.argv[at + 1]) : 3210;
const venv = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const token = randomBytes(32).toString("base64url");
const api = spawn(process.env.PYTHON_BIN || (existsSync(venv) ? venv : "python"), [path.join(root, "worker", "app_api.py"), "--port", String(port), "--ui", ui], {
  cwd: root, env: { ...process.env, AUDIO_API_TOKEN: token }, stdio: ["ignore", "pipe", "inherit"],
});
api.stdout.on("data", (chunk) => { if (String(chunk).includes("AUDIO_API_READY")) console.log(`\nOpen: http://127.0.0.1:${port}/?launch=${token}\n`); });
api.on("exit", (code) => process.exit(code ?? 0));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => { api.kill(); process.exit(0); });
