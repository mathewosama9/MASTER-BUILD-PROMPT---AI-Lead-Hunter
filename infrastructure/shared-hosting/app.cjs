// Shared-hosting entry point (Hostinger / LiteSpeed Node.js app). One process does three jobs:
//   1. serves the Next.js site (standalone build in this folder) through Next's request handler;
//   2. proxies /api/* to the FastAPI backend and /telegram/webhook to the bot, both on Unix sockets;
//   3. supervises the backend services (Postgres, Redis, API, Celery worker + beat, Telegram bot): starts any
//      that are not running, now and every minute. They run detached, so they outlive this process when the
//      host recycles it, and the next request (a visitor or a Telegram update) brings everything back.
// Layout (ROOT = ..): rasd.env, pg/, data/, redis/, venv/, src/backend, src/telegram, run/ (sockets, pids), logs/.
"use strict";
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const { parseEnv } = require("node:util");

const ROOT = path.resolve(__dirname, "..");
const RUN = path.join(ROOT, "run");
const LOGS = path.join(ROOT, "logs");
const env = {
  PATH: "/usr/local/bin:/usr/bin:/bin",
  HOME: process.env.HOME || "/home/" + (process.env.USER || ""),
  LANG: "C.UTF-8",
  ...parseEnv(fs.readFileSync(path.join(ROOT, "rasd.env"), "utf8")),
  LD_LIBRARY_PATH: path.join(ROOT, "libs"),
  PYTHONUNBUFFERED: "1",
};
const API_SOCK = path.join(RUN, "api.sock");
const BOT_SOCK = path.join(RUN, "bot.sock");
const venv = (bin) => path.join(ROOT, "venv", "bin", bin);
const backend = path.join(ROOT, "src", "backend");

function alive(pidFile, needle) {
  try {
    const pid = parseInt(fs.readFileSync(pidFile, "utf8").split("\n")[0], 10);
    process.kill(pid, 0);
    const cmd = fs.readFileSync(`/proc/${pid}/cmdline`, "utf8");
    return cmd.includes(needle);
  } catch {
    return false;
  }
}

function launch(name, cmd, args, cwd, extra = {}) {
  const log = fs.openSync(path.join(LOGS, `${name}.log`), "a");
  const child = spawn(cmd, args, { cwd, env: { ...env, ...extra }, detached: true, stdio: ["ignore", log, log] });
  fs.writeFileSync(path.join(RUN, `${name}.pid`), String(child.pid));
  child.unref();
  fs.closeSync(log);
  console.log(`[supervisor] started ${name} (pid ${child.pid})`);
}

const SERVICES = [
  {
    name: "postgres",
    up: () => alive(path.join(ROOT, "data", "pg", "postmaster.pid"), "postgres"),
    start: () =>
      spawnSync(path.join(ROOT, "pg", "bin", "pg_ctl"), ["-D", path.join(ROOT, "data", "pg"), "-l",
        path.join(LOGS, "postgres.log"), "-w", "-t", "30", "start"], { env, stdio: "ignore" }),
  },
  {
    name: "redis",
    up: () => alive(path.join(RUN, "redis.pid"), "redis-server"),
    start: () => spawnSync(path.join(ROOT, "redis", "redis-server"), [path.join(ROOT, "data", "redis.conf")],
      { env, stdio: "ignore" }),
  },
  {
    name: "api",
    up: () => alive(path.join(RUN, "api.pid"), "uvicorn"),
    start: () => {
      fs.rmSync(API_SOCK, { force: true });
      launch("api", venv("uvicorn"), ["app.main:app", "--uds", API_SOCK, "--proxy-headers",
        "--forwarded-allow-ips", "*", "--no-access-log"], backend);
    },
  },
  {
    name: "worker",
    up: () => alive(path.join(RUN, "worker.pid"), "celery"),
    // solo pool: one process, few threads (the host caps threads per account).
    start: () => launch("worker", venv("celery"), ["-A", "app.workers.celery_app", "worker", "-Q",
      "research,default", "--pool", "solo", "--without-gossip", "--without-mingle", "-l", "info"], backend),
  },
  {
    name: "beat",
    up: () => alive(path.join(RUN, "beat.pid"), "celery"),
    start: () => launch("beat", venv("celery"), ["-A", "app.workers.celery_app", "beat", "-l", "info", "-s",
      path.join(ROOT, "data", "celerybeat-schedule"), "--pidfile", ""], backend),
  },
  {
    name: "bot",
    up: () => alive(path.join(RUN, "bot.pid"), "main.py"),
    start: () => {
      fs.rmSync(BOT_SOCK, { force: true });
      launch("bot", venv("python"), ["main.py"], path.join(ROOT, "src", "telegram"));
    },
  },
];

const LOCK = path.join(RUN, "supervisor.lock");
function supervise() {
  try {
    fs.mkdirSync(LOCK); // atomic: only one app process supervises at a time
  } catch {
    try {
      if (Date.now() - fs.statSync(LOCK).mtimeMs < 120000) return;
      fs.rmSync(LOCK, { recursive: true, force: true }); // stale lock from a killed process
      fs.mkdirSync(LOCK);
    } catch {
      return;
    }
  }
  try {
    for (const s of SERVICES) {
      if (!s.up()) {
        try {
          s.start();
        } catch (err) {
          console.error(`[supervisor] ${s.name} failed to start:`, err);
        }
      }
    }
  } finally {
    fs.rmSync(LOCK, { recursive: true, force: true });
  }
}

function proxy(req, res, socketPath) {
  const headers = { ...req.headers, "x-forwarded-proto": "https" };
  const upstream = http.request({ socketPath, path: req.url, method: req.method, headers }, (up) => {
    res.writeHead(up.statusCode || 502, up.headers);
    up.pipe(res);
  });
  upstream.on("error", () => {
    supervise();
    if (!res.headersSent) res.writeHead(503, { "content-type": "application/json", "retry-after": "5" });
    res.end('{"error":{"code":"starting","message":"Rasd is starting, please retry in a few seconds"}}');
  });
  req.pipe(upstream);
}

async function main() {
  fs.mkdirSync(RUN, { recursive: true });
  fs.mkdirSync(LOGS, { recursive: true });
  supervise();
  setInterval(supervise, 60000).unref();

  // Next.js: the standalone build's own server.js holds the serialized config; reuse it with Next's handler.
  const source = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  const config = JSON.parse(source.match(/const nextConfig = (\{.*\})\n/)[1]);
  process.env.NODE_ENV = "production";
  process.env.__NEXT_PRIVATE_STANDALONE_CONFIG = JSON.stringify(config);
  process.chdir(__dirname);
  const next = require("next");
  const app = next({ dev: false, dir: __dirname, conf: config, hostname: "localhost", port: 3000 });
  await app.prepare();
  const handle = app.getRequestHandler();

  http
    .createServer((req, res) => {
      if (req.url.startsWith("/api/")) return proxy(req, res, API_SOCK);
      if (req.url.startsWith("/telegram/webhook")) return proxy(req, res, BOT_SOCK);
      return handle(req, res);
    })
    .listen(process.env.PORT || 3000, () => console.log("[rasd] listening"));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
