import { copyFileSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function run(cmd, args, opts = {}) {
  const result = spawnSync(cmd, args, {
    stdio: "inherit",
    shell: process.platform === "win32",
    cwd: root,
    ...opts,
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function copyIfMissing(from, to) {
  if (existsSync(to)) {
    console.log(`skip: ${path.relative(root, to)} already exists`);
    return;
  }
  copyFileSync(from, to);
  console.log(`created: ${path.relative(root, to)} (edit with your real values)`);
}

console.log("==> Copy env templates");
copyIfMissing(path.join(root, ".env.example"), path.join(root, ".env"));
copyIfMissing(
  path.join(root, "frontend", ".env.example"),
  path.join(root, "frontend", ".env"),
);

console.log("\n==> Install root dev deps (concurrently)");
run("npm", ["install"]);

console.log("\n==> Install backend (uv sync)");
run("uv", ["sync", "--project", "backend"]);

console.log("\n==> Install frontend");
run("npm", ["install"], { cwd: path.join(root, "frontend") });

console.log("\nDone. Next steps:");
console.log("  1. Fill in .env and frontend/.env with real values");
console.log("  2. Run products.sql in Supabase + sync Knowledge Base");
console.log("  3. npm run dev");
