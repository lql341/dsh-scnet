import { readFile } from "node:fs/promises"
import { execFileSync } from "node:child_process"

const pkg = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"))
if (!pkg.dsh?.bundle?.patch) throw new Error("package.json must declare dsh.bundle.patch")
if (!pkg.files?.includes("skills")) throw new Error("package.json must ship skills/")
if (pkg.dsh.skills !== undefined) throw new Error("dsh.skills is not part of the rc.8 bundle manifest")
const patch = await readFile(new URL("../cordis.patch.yml", import.meta.url), "utf8")
for (const required of ["scnet-skill-filesystem", "@deepseek-ai/dsh-skill-filesystem", "skills/", "id: scnet", "name: dsh-scnet"]) {
  if (!patch.includes(required)) throw new Error(`cordis.patch.yml is missing ${required}`)
}

execFileSync("node", ["--check", "index.mjs"], { stdio: "inherit" })
execFileSync("node", ["--input-type=module", "-e", "import('./index.mjs').then(m => { if (m.name !== 'scnet-hpc' || typeof m.apply !== 'function') process.exit(1) })"], { stdio: "inherit" })
execFileSync("bash", ["-n", "sync.sh"], { stdio: "inherit" })
for (const file of ["skills/scnet-hpc/scripts/_common.sh", "skills/scnet-hpc/scripts/new-job.sh", "skills/scnet-hpc/scripts/setup-ssh.sh", "skills/scnet-hpc/scripts/probe-cluster.sh", "skills/scnet-hpc/scripts/refresh-cluster.sh", "skills/scnet-hpc/scripts/run-compute-probe.sh"]) execFileSync("bash", ["-n", file], { stdio: "inherit" })
execFileSync("python3", ["-c", "compile(open('skills/scnet-hpc/scripts/compute-probe.py', encoding='utf-8').read(), 'compute-probe.py', 'exec')"], { stdio: "inherit" })
execFileSync("npm", ["pack", "--dry-run"], { stdio: "inherit" })
console.log(`validated ${pkg.name}@${pkg.version}`)
