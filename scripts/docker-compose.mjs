import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const args = process.argv.slice(2);

if (args[0] === "--") {
  args.shift();
}

if (args.length === 0) {
  console.error("Usage: node scripts/docker-compose.mjs <compose arguments>");
  process.exit(1);
}

const dockerConfigDir = join(tmpdir(), "labelos-docker-config");
mkdirSync(dockerConfigDir, { recursive: true });
writeFileSync(join(dockerConfigDir, "config.json"), "{}\n", { flag: "w" });

const env = {
  ...process.env,
  DOCKER_CONFIG: process.env.DOCKER_CONFIG || dockerConfigDir,
};

function run(command, commandArgs, stdio = "inherit") {
  return spawnSync(command, commandArgs, {
    cwd: process.cwd(),
    env,
    stdio,
    shell: process.platform === "win32",
  });
}

const v2Probe = run("docker", ["compose", "version"], "ignore");

if (v2Probe.status === 0) {
  const result = run("docker", ["compose", ...args]);
  process.exit(result.status ?? 1);
}

const legacyProbe = run("docker-compose", ["version"], "ignore");

if (legacyProbe.status === 0) {
  const result = run("docker-compose", args);
  process.exit(result.status ?? 1);
}

console.error("Docker Compose is not available. Install Docker Compose v2 or docker-compose.");
process.exit(1);
