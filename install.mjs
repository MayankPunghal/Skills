#!/usr/bin/env node
/**
 * Installer for MayankPunghal/Skills — zero dependencies, Node 18+.
 *
 *   npx -y github:MayankPunghal/Skills              interactive install (pick skills, agents, global/project)
 *   npx -y github:MayankPunghal/Skills update       reinstall everything recorded in the manifest from the latest repo
 *   npx -y github:MayankPunghal/Skills setup        install the prerequisites (Python packages) of installed skills
 *   npx -y github:MayankPunghal/Skills zips         rebuild the upload-ready zips for the Claude app (opens the folder on Windows)
 *   npx -y github:MayankPunghal/Skills list         show what is installed where
 *   npx -y github:MayankPunghal/Skills uninstall    remove skills this installer put in place
 *
 * Non-interactive flags (for scripts / CI):
 *   --skills=all|a,b   --agents=claude,codex,cursor,copilot   --scope=global|project
 *   --dir=<project dir> (default: current folder)   --yes (accept defaults)   --link (symlink instead of copy)
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import zlib from "node:zlib";
import crypto from "node:crypto";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SKILLS_DIR = path.join(HERE, "skills");
const HOME = os.homedir();
// Optional private source: fetched with git after the public repo. Machines whose Git can't read it (everyone but the
// owner) skip it silently, with interactive sign-in switched off so nobody is asked to log in to a repo they can't see.
const PERSONAL_URL = process.env.MAYANK_SKILLS_PERSONAL_URL || "https://github.com/MayankPunghal/Skills-Personal.git"; // env override: tests only
const PERSONAL_DIR = path.join(HOME, ".mayank-skills", "personal");
const PERSONAL_SKILLS = path.join(PERSONAL_DIR, "skills");
let SKILL_INDEX = null; // name -> { dir, source }
const MANIFEST = path.join(HOME, ".mayank-skills", "manifest.json");
const BACKUP_ROOT = path.join(HOME, ".mayank-skills", "backup");
const SKIP = new Set(["__pycache__", ".DS_Store", "node_modules", ".git", ".impeccable", ".pytest_cache", ".venv"]);

// Where each agent looks for skills. null = that agent has no user-level (global) skills folder.
const AGENTS = {
  claude:  { label: "Claude Code",              detect: ".claude",  global: ".claude/skills",  project: ".claude/skills" },
  codex:   { label: "Codex / .agents (shared)", detect: ".codex",   global: ".agents/skills",  project: ".agents/skills" },
  cursor:  { label: "Cursor",                   detect: ".cursor",  global: null,              project: ".cursor/skills" },
  copilot: { label: "GitHub Copilot",           detect: ".copilot", global: null,              project: ".github/skills" },
};

// Skills that need another skill installed beside them (migration-assessment reuses the documenter's installer and graphify setup).
const DEPENDS = { "migration-assessment": ["codebase-documenter"] };
// A skill that ships this script gets an optional "install prerequisites" step after copying.
const SETUP_SCRIPT = ["scripts", "install_prerequisites.py"];
const MIN_PY = [3, 10]; // the skills' scripts use 3.10+ syntax

// ---------- terminal helpers ----------
const tty = process.stdin.isTTY && process.stdout.isTTY;
const c = (n) => (s) => (process.stdout.isTTY ? `\x1b[${n}m${s}\x1b[0m` : String(s));
const bold = c(1), dim = c(2), green = c(32), yellow = c(33), cyan = c(36), red = c(31);
const say = (s = "") => process.stdout.write(s + "\n");

function args() {
  const out = { cmd: "install", flags: {} };
  for (const a of process.argv.slice(2)) {
    const m = a.match(/^--([^=]+)(?:=(.*))?$/);
    if (m) out.flags[m[1]] = m[2] ?? true;
    else out.cmd = a;
  }
  return out;
}

/** Arrow-key list. multi=true → space toggles, a = all; Enter confirms. Falls back to typed input without a TTY. */
async function choose(title, items, { multi = false, preselect = [] } = {}) {
  if (!tty) {
    say(bold(title));
    items.forEach((it, i) => say(`  ${i + 1}) ${it.label}${it.hint ? dim("  " + it.hint) : ""}`));
    const ans = await ask(multi ? "Numbers, comma separated (Enter = preselected): " : "Number (Enter = 1): ");
    if (!ans.trim()) return multi ? items.filter((it) => preselect.includes(it.value)).map((it) => it.value) : items[0].value;
    const picks = ans.split(",").map((s) => items[parseInt(s, 10) - 1]).filter(Boolean).map((it) => it.value);
    return multi ? picks : picks[0] ?? items[0].value;
  }
  return new Promise((resolve) => {
    let cur = 0;
    const sel = new Set(preselect);
    let drawn = 0;
    const draw = () => {
      if (drawn) process.stdout.write(`\x1b[${drawn}A\x1b[J`);
      const lines = [bold(title) + dim(multi ? "  (↑↓ move · space select · a all · enter confirm)" : "  (↑↓ move · enter select)")];
      items.forEach((it, i) => {
        const pointer = i === cur ? cyan("❯") : " ";
        const box = multi ? (sel.has(it.value) ? green("◉") : dim("◯")) + " " : "";
        const label = i === cur ? cyan(it.label) : it.label;
        lines.push(`${pointer} ${box}${label}${it.hint ? dim("  " + it.hint) : ""}`);
      });
      process.stdout.write(lines.join("\n") + "\n");
      drawn = lines.length;
    };
    readline.emitKeypressEvents(process.stdin);
    process.stdin.setRawMode(true);
    process.stdin.resume();
    const onKey = (_s, key = {}) => {
      if (key.ctrl && key.name === "c") { process.stdin.setRawMode(false); say("\nCancelled."); process.exit(130); }
      if (key.name === "up") cur = (cur - 1 + items.length) % items.length;
      else if (key.name === "down") cur = (cur + 1) % items.length;
      else if (multi && key.name === "space") { const v = items[cur].value; sel.has(v) ? sel.delete(v) : sel.add(v); }
      else if (multi && key.name === "a") { if (sel.size === items.length) sel.clear(); else items.forEach((it) => sel.add(it.value)); }
      else if (key.name === "return") {
        if (multi && sel.size === 0) { sel.add(items[cur].value); }
        process.stdin.off("keypress", onKey);
        process.stdin.setRawMode(false);
        process.stdin.pause();
        process.stdout.write(`\x1b[${drawn}A\x1b[J`);
        const result = multi ? items.filter((it) => sel.has(it.value)) : [items[cur]];
        say(`${green("✔")} ${bold(title)} ${cyan(result.map((r) => r.label).join(", "))}`);
        return resolve(multi ? result.map((r) => r.value) : result[0].value);
      }
      draw();
    };
    process.stdin.on("keypress", onKey);
    draw();
  });
}

function ask(q, def = "") {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(q, (a) => { rl.close(); resolve(a.trim() || def); });
  });
}

// ---------- skill discovery ----------
function skillFolders(root, source) {
  if (!fs.existsSync(root)) return [];
  return fs.readdirSync(root, { withFileTypes: true })
    .filter((d) => d.isDirectory() && fs.existsSync(path.join(root, d.name, "SKILL.md")))
    .map((d) => ({ name: d.name, dir: path.join(root, d.name), source }));
}

/** All installable skills: public ones from this repo, plus personal ones when the private source is present. */
function readSkills() {
  if (!fs.existsSync(SKILLS_DIR)) { say(red(`No skills folder next to the installer (${SKILLS_DIR}).`)); process.exit(1); }
  const byName = new Map();
  for (const s of [...skillFolders(SKILLS_DIR, "public"), ...skillFolders(PERSONAL_SKILLS, "personal")]) byName.set(s.name, s); // personal wins
  SKILL_INDEX = Object.fromEntries([...byName.values()].map((s) => [s.name, s]));
  return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name)).map((s) => {
    const text = fs.readFileSync(path.join(s.dir, "SKILL.md"), "utf8");
    const m = text.match(/^description:\s*(.+)$/m);
    const desc = (m ? m[1] : "").replace(/^["'>|-]+\s*/, "");
    return { name: s.name, source: s.source, desc: desc.length > 70 ? desc.slice(0, 67) + "…" : desc };
  });
}

function skillDir(name) {
  if (!SKILL_INDEX) readSkills();
  return SKILL_INDEX[name]?.dir ?? path.join(SKILLS_DIR, name);
}

// ---------- file operations ----------
function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    if (SKIP.has(e.name) || e.name.endsWith(".pyc")) continue;
    const s = path.join(src, e.name), d = path.join(dst, e.name);
    if (e.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

function backupExisting(target, stamp) {
  if (!fs.existsSync(target)) return null;
  const st = fs.lstatSync(target);
  if (st.isSymbolicLink()) { fs.unlinkSync(target); return "replaced link"; }
  const dest = path.join(BACKUP_ROOT, stamp, target.replace(/[:\\/]+/g, "_"));
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.renameSync(target, dest);
  return dest;
}

function loadManifest() {
  try { return JSON.parse(fs.readFileSync(MANIFEST, "utf8")); } catch { return { installs: [] }; }
}
function saveManifest(m) {
  fs.mkdirSync(path.dirname(MANIFEST), { recursive: true });
  fs.writeFileSync(MANIFEST, JSON.stringify(m, null, 2));
}

function targetFor(agent, scope, projectDir) {
  const a = AGENTS[agent];
  const rel = scope === "global" ? a.global : a.project;
  if (!rel) return null;
  return path.join(scope === "global" ? HOME : projectDir, ...rel.split("/"));
}

const FROM_CACHE = /[\\/]_npx[\\/]|[\\/]npm-cache[\\/]/.test(HERE);

/** Copy (or link) one skill into one skills folder, backing up whatever was there, and record it in the manifest. */
function placeSkill(manifest, { name, base, agent, scope, link, stamp }) {
  const target = path.join(base, name);
  const backed = backupExisting(target, stamp);
  fs.mkdirSync(base, { recursive: true });
  if (link) fs.symlinkSync(skillDir(name), target, "junction");
  else copyDir(skillDir(name), target);
  manifest.installs = manifest.installs.filter((i) => i.path !== target);
  manifest.installs.push({ skill: name, source: SKILL_INDEX?.[name]?.source || "public", agent, scope, path: target, link: !!link, at: new Date().toISOString() });
  say(`${green("✔")} ${name} ${dim("→")} ${target}${backed ? dim(`  (previous version backed up: ${backed})`) : ""}`);
}

function withDeps(skills) {
  const out = [...skills];
  for (const s of skills) for (const dep of DEPENDS[s] || []) {
    if (!out.includes(dep)) { out.push(dep); say(dim(`+ ${dep} added (${s} needs it)`)); }
  }
  return out;
}

function install({ skills, agents, scope, projectDir, link }) {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const manifest = loadManifest();
  // npx runs from a temporary cache, so a symlink into it would break later: links only from a real clone.
  if (link && FROM_CACHE) { say(yellow("! --link ignored: running from the npx cache, copying instead.")); link = false; }
  let done = 0;
  for (const agent of agents) {
    const base = targetFor(agent, scope, projectDir);
    if (!base) { say(yellow(`! ${AGENTS[agent].label} has no global skills folder — skipped (choose project scope for it).`)); continue; }
    for (const name of skills) {
      placeSkill(manifest, { name, base, agent, scope, link, stamp });
      done++;
    }
  }
  saveManifest(manifest);
  return done;
}

// ---------- prerequisites ----------
/** First Python 3.10+ on PATH, as [command, ...prefixArgs], or null. */
function findPython() {
  const candidates = process.platform === "win32" ? [["python"], ["py", "-3"], ["python3"]] : [["python3"], ["python"]];
  for (const [cmd, ...pre] of candidates) {
    const r = spawnSync(cmd, [...pre, "-c", "import sys;print('%d.%d'%sys.version_info[:2])"], { encoding: "utf8" });
    if (r.status !== 0 || !r.stdout) continue;
    const [maj, min] = r.stdout.trim().split(".").map(Number);
    if (maj > MIN_PY[0] || (maj === MIN_PY[0] && min >= MIN_PY[1])) return [cmd, ...pre];
  }
  return null;
}

function skillsWithSetup(names) {
  return names.filter((n) => fs.existsSync(path.join(skillDir(n), ...SETUP_SCRIPT)));
}

/** Runs each skill's install_prerequisites.py once (user-level installs, idempotent). Returns true if all succeeded.
 *  quiet (--yes): a script that offers optional prompts gets --no-key-prompt, so an unattended install never waits for input. */
function runSetup(names, installedPathFor, { quiet = false } = {}) {
  if (!names.length) return true;
  const py = findPython();
  if (!py) {
    say(yellow(`! Python ${MIN_PY.join(".")}+ not found — skipped prerequisites for ${names.join(", ")}.`));
    say(dim("  Install Python (Windows: winget install --id Python.Python.3.14 -e), open a new terminal, then run: … setup"));
    return false;
  }
  let ok = true;
  for (const name of names) {
    const script = path.join(installedPathFor(name) || skillDir(name), ...SETUP_SCRIPT);
    say(bold(`\n▸ Prerequisites for ${name}`) + dim(`  (${py.join(" ")} ${script})`));
    const extra = quiet && fs.existsSync(script) && fs.readFileSync(script, "utf8").includes("--no-key-prompt") ? ["--no-key-prompt"] : [];
    const r = spawnSync(py[0], [...py.slice(1), script, ...extra], { stdio: "inherit" });
    if (r.status === 0) say(green(`✔ ${name} prerequisites ready`));
    else { ok = false; say(yellow(`! ${name} prerequisites reported a problem (exit ${r.status}). Fix it, then run: … setup`)); }
  }
  return ok;
}

// ---------- upload-ready zips (Claude app / claude.ai) ----------
// App chats use skills stored in the claude.ai account, which no installer can reach. So every run also writes one
// zip per skill (the skill folder at the top level, as Settings -> Capabilities -> Skills expects) and reports which
// ones changed since the last build: those are the ones to re-upload.
const ZIP_DIR = path.join(HOME, ".mayank-skills", "zips");
const CRC_TABLE = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc32 = (buf) => { let c = 0xffffffff; for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

function listFiles(dir, base = dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    if (SKIP.has(e.name) || e.name.endsWith(".pyc")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...listFiles(p, base));
    else if (e.isFile()) out.push(p);
  }
  return out;
}

/** Minimal ZIP writer (deflate, no dependencies). Fixed timestamps so identical content gives identical zips. */
function writeZip(srcDir, rootName, outFile) {
  const parts = [], central = [];
  let offset = 0;
  const DOS_TIME = 0, DOS_DATE = (2020 - 1980) << 9 | 1 << 5 | 1; // 2020-01-01: stable output for change detection
  for (const file of listFiles(srcDir)) {
    const name = Buffer.from(rootName + "/" + path.relative(srcDir, file).split(path.sep).join("/"), "utf8");
    const data = fs.readFileSync(file);
    const comp = zlib.deflateRawSync(data, { level: 9 });
    const crc = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(0x0800, 6); local.writeUInt16LE(8, 8);
    local.writeUInt16LE(DOS_TIME, 10); local.writeUInt16LE(DOS_DATE, 12); local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(comp.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(name.length, 26); local.writeUInt16LE(0, 28);
    parts.push(local, name, comp);
    const cen = Buffer.alloc(46);
    cen.writeUInt32LE(0x02014b50, 0); cen.writeUInt16LE(20, 4); cen.writeUInt16LE(20, 6); cen.writeUInt16LE(0x0800, 8); cen.writeUInt16LE(8, 10);
    cen.writeUInt16LE(DOS_TIME, 12); cen.writeUInt16LE(DOS_DATE, 14); cen.writeUInt32LE(crc, 16); cen.writeUInt32LE(comp.length, 20);
    cen.writeUInt32LE(data.length, 24); cen.writeUInt16LE(name.length, 28); cen.writeUInt32LE(offset, 42);
    central.push(cen, name);
    offset += 30 + name.length + comp.length;
  }
  const cenBuf = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(central.length / 2, 8); end.writeUInt16LE(central.length / 2, 10);
  end.writeUInt32LE(cenBuf.length, 12); end.writeUInt32LE(offset, 16);
  const zip = Buffer.concat([...parts, cenBuf, end]);
  fs.writeFileSync(outFile, zip);
  return crypto.createHash("sha256").update(zip).digest("hex").slice(0, 16);
}

/** Build a zip per skill into ~/.mayank-skills/zips and say which changed since the last build. */
function buildZips({ quiet = false } = {}) {
  fs.mkdirSync(ZIP_DIR, { recursive: true });
  const stateFile = path.join(ZIP_DIR, "zips.json");
  let state = {};
  try { state = JSON.parse(fs.readFileSync(stateFile, "utf8")); } catch {}
  const changed = [];
  for (const s of readSkills()) {
    const hash = writeZip(skillDir(s.name), s.name, path.join(ZIP_DIR, `${s.name}.zip`));
    if (state[s.name] !== hash) changed.push(s.name);
    state[s.name] = hash;
  }
  fs.writeFileSync(stateFile, JSON.stringify(state, null, 2));
  if (quiet && !changed.length) return changed;
  say("");
  say(bold("Claude app / claude.ai") + dim(" (phone, web, desktop chats use skills stored in your account)"));
  say(`  Upload-ready zips: ${ZIP_DIR}`);
  say(changed.length
    ? `  ${yellow("Upload these")} in Settings → Capabilities → Skills (replace the old copy): ${changed.map((n) => n + ".zip").join(", ")}`
    : dim("  No skill changed since the last build: nothing to re-upload."));
  return changed;
}

// ---------- commands ----------
async function cmdInstall(flags) {
  const all = readSkills();
  say(bold("\nMayank's Skills installer") + dim(`  ·  ${all.length} skills`));
  say("");
  const yes = !!flags.yes;

  let skills;
  if (flags.skills) skills = flags.skills === "all" ? all.map((s) => s.name) : String(flags.skills).split(",");
  else if (yes) skills = all.map((s) => s.name);
  else skills = await choose("Which skills?", all.map((s) => ({ value: s.name, label: s.name, hint: (s.source === "personal" ? "personal · " : "") + s.desc })), { multi: true, preselect: all.map((s) => s.name) });
  const unknown = skills.filter((s) => !all.some((a) => a.name === s));
  if (unknown.length) { say(red(`Unknown skill(s): ${unknown.join(", ")}`)); process.exit(1); }
  skills = withDeps(skills);

  let scope = flags.scope;
  if (!scope) scope = yes ? "global" : await choose("Install where?", [
    { value: "global", label: "Global", hint: "your user folder — every project on this machine" },
    { value: "project", label: "This project only", hint: process.cwd() },
  ]);
  let projectDir = path.resolve(String(flags.dir || process.cwd()));
  if (scope === "project" && !flags.dir && !yes && tty) projectDir = path.resolve(await ask(`Project folder ${dim(`(${projectDir})`)}: `, projectDir));

  let agents;
  const detected = Object.keys(AGENTS).filter((k) => k === "claude" || fs.existsSync(path.join(HOME, AGENTS[k].detect)));
  if (flags.agents) agents = String(flags.agents).split(",");
  else if (yes) agents = ["claude"];
  else agents = await choose("For which agents?", Object.entries(AGENTS).map(([k, a]) => ({
    value: k, label: a.label,
    hint: (scope === "global" ? (a.global ? "~/" + a.global : "project only") : a.project) + (detected.includes(k) ? "  · detected" : ""),
  })), { multi: true, preselect: ["claude"] });
  const badAgent = agents.filter((a) => !AGENTS[a]);
  if (badAgent.length) { say(red(`Unknown agent(s): ${badAgent.join(", ")}. Use: ${Object.keys(AGENTS).join(", ")}`)); process.exit(1); }

  let link = !!flags.link;
  if (!flags.link && !yes && tty && !/[\\/]_npx[\\/]/.test(HERE)) {
    link = (await choose("Copy or link?", [
      { value: "copy", label: "Copy", hint: "independent files; run update to refresh" },
      { value: "link", label: "Link", hint: "points at ~/.mayank-skills/repo, which every installer run refreshes" },
    ])) === "link";
  }

  const needSetup = skillsWithSetup(skills);
  let doSetup = false;
  if (needSetup.length && !flags["no-setup"]) {
    doSetup = yes || !tty || (await choose(`Install prerequisites for ${needSetup.join(", ")}?`, [
      { value: "yes", label: "Yes, install now", hint: "the tools each skill needs (user-level where possible); skips what's already there" },
      { value: "no", label: "Skip", hint: "run later: npx -y github:MayankPunghal/Skills setup" },
    ])) === "yes";
  }

  say("");
  const n = install({ skills, agents, scope, projectDir, link });
  if (doSetup) {
    const installs = loadManifest().installs;
    runSetup(needSetup, (name) => installs.find((i) => i.skill === name && !i.link)?.path, { quiet: yes });
  }
  say("");
  say(green(bold(`Done — ${n} skill install(s).`)) + " Claude Code picks them up automatically (or run /reload-skills).");
  if (!flags["no-zips"]) buildZips();
  say(dim("Update later: npx -y github:MayankPunghal/Skills update   ·   See installs: … list"));
}

async function cmdUpdate(flags) {
  const m = loadManifest();
  if (!m.installs.length) { say("Nothing recorded yet — run the installer first."); return; }
  const available = readSkills().map((s) => s.name);
  let n = 0;
  for (const it of m.installs) {
    if (it.link) { say(dim(`= ${it.skill} → ${it.path} (linked — already refreshed by this run)`)); continue; }
    if (!available.includes(it.skill)) { say(yellow(`! ${it.skill} no longer in the repo — left as is at ${it.path}`)); continue; }
    if (!fs.existsSync(path.dirname(it.path))) { say(yellow(`! ${it.path} — folder gone, skipped`)); continue; }
    fs.rmSync(it.path, { recursive: true, force: true });
    copyDir(skillDir(it.skill), it.path);
    it.at = new Date().toISOString();
    say(`${green("✔")} ${it.skill} ${dim("→")} ${it.path}`);
    n++;
  }
  saveManifest(m);
  say(green(`\nUpdated ${n} install(s).`));
  if (!flags["no-zips"]) buildZips();

  // Skills added to the repo since the last install: offer them, into the same folders the others went to.
  const have = new Set(m.installs.map((i) => i.skill));
  const fresh = available.filter((s) => !have.has(s));
  if (!fresh.length) return;
  const yes = !!flags.yes;
  let picks;
  if (flags.skills) picks = String(flags.skills).split(",").filter((s) => fresh.includes(s));
  else if (yes) picks = fresh;
  else if (!tty) { say(`\nNew in the repo: ${fresh.join(", ")} — rerun with --yes (or --skills=...) to install.`); return; }
  else {
    say("");
    picks = await choose("New skills in the repo — install them too?", fresh.map((s) => ({ value: s, label: s })), { multi: true, preselect: fresh });
  }
  if (!picks.length) return;
  picks = withDeps(picks).filter((s) => !have.has(s) || picks.includes(s));
  const targets = [];
  for (const it of m.installs) {
    const base = path.dirname(it.path);
    if (fs.existsSync(base) && !targets.some((t) => t.base === base)) targets.push({ base, agent: it.agent, scope: it.scope, link: it.link && !FROM_CACHE });
  }
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const manifest = loadManifest();
  say("");
  for (const t of targets) for (const name of picks) placeSkill(manifest, { name, ...t, stamp });
  saveManifest(manifest);
  const needSetup = skillsWithSetup(picks);
  if (needSetup.length && !flags["no-setup"]) {
    const go = yes || (await choose(`Install prerequisites for ${needSetup.join(", ")}?`, [
      { value: "yes", label: "Yes, install now" }, { value: "no", label: "Skip" }])) === "yes";
    if (go) runSetup(needSetup, (name) => manifest.installs.find((i) => i.skill === name && !i.link)?.path, { quiet: yes });
  }
  say(green(`\nInstalled ${picks.length} new skill(s) into ${targets.length} folder(s).`));
}

function cmdSetup() {
  const installs = loadManifest().installs;
  const names = [...new Set(installs.map((i) => i.skill))];
  const targets = skillsWithSetup(names.length ? names : readSkills().map((s) => s.name));
  if (!targets.length) { say("No installed skill has prerequisites to set up."); return; }
  process.exitCode = runSetup(targets, (name) => installs.find((i) => i.skill === name && !i.link)?.path) ? 0 : 1;
}

function cmdList() {
  const m = loadManifest();
  if (!m.installs.length) { say("No installs recorded."); return; }
  for (const it of m.installs) say(`${bold(it.skill.padEnd(22))} ${AGENTS[it.agent]?.label.padEnd(26) ?? it.agent} ${it.scope.padEnd(8)} ${it.path}${it.link ? dim(" (link)") : ""}`);
}

async function cmdUninstall(flags) {
  const m = loadManifest();
  if (!m.installs.length) { say("No installs recorded."); return; }
  const picks = flags.yes ? m.installs.map((i) => i.path) : await choose("Remove which installs?", m.installs.map((i) => ({ value: i.path, label: `${i.skill}  ${dim(i.path)}` })), { multi: true });
  for (const p of picks) {
    if (fs.existsSync(p) || (() => { try { return fs.lstatSync(p).isSymbolicLink(); } catch { return false; } })()) fs.rmSync(p, { recursive: true, force: true });
    say(`${red("✖")} ${p}`);
  }
  m.installs = m.installs.filter((i) => !picks.includes(i.path));
  saveManifest(m);
}

/**
 * npx keeps a git package in its cache and reuses it without checking GitHub again, so a plain npx run can be stale.
 * Fix: keep our own clone at ~/.mayank-skills/repo, bring it to the latest main on every run, and hand over to the
 * installer inside it. If git can't reach GitHub, carry on with the copy npx gave us.
 */
const REPO_URL = "https://github.com/MayankPunghal/Skills.git";
const REPO_DIR = path.join(HOME, ".mayank-skills", "repo");
function syncAndHandOver(flags) {
  if (process.env.MAYANK_SKILLS_SYNCED || flags["no-sync"]) return;
  const same = (a, b) => { try { return fs.realpathSync(a) === fs.realpathSync(b); } catch { return false; } };
  if (same(HERE, REPO_DIR)) return; // already running from the managed clone (synced by the parent run)
  const git = (...a) => spawnSync("git", a, { encoding: "utf8", stdio: ["inherit", "pipe", "pipe"] });
  let r;
  if (fs.existsSync(path.join(REPO_DIR, ".git"))) {
    r = git("-C", REPO_DIR, "fetch", "--depth", "1", "-q", "origin", "main");
    if (r.status === 0) {
      // The skill publisher commits here; never throw away uncommitted edits or commits not yet on GitHub.
      // The publisher leaves <clone>.pending beside the clone when a commit couldn't be pushed yet.
      const dirty = git("-C", REPO_DIR, "status", "--porcelain").stdout.trim();
      const pending = fs.existsSync(REPO_DIR + ".pending");
      if (dirty || pending) say(yellow(`! ${REPO_DIR} has local work not on GitHub — using it as is (the skill publisher will push it).`));
      else r = git("-C", REPO_DIR, "reset", "--hard", "-q", "origin/main");
    }
  } else {
    fs.mkdirSync(path.dirname(REPO_DIR), { recursive: true });
    r = git("clone", "--depth", "1", "-q", REPO_URL, REPO_DIR);
  }
  const target = path.join(REPO_DIR, "install.mjs");
  if (r.status !== 0 || !fs.existsSync(target)) {
    say(yellow(`! Couldn't fetch the latest repo (${(r.stderr || "git not found").trim().split("\n").pop()}). Using the copy npx provided.`));
    return;
  }
  const child = spawnSync(process.execPath, [target, ...process.argv.slice(2)], { stdio: "inherit", env: { ...process.env, MAYANK_SKILLS_SYNCED: "1" } });
  process.exit(child.status ?? 1);
}

/** Fetch the private source if this machine's Git can read it. Never prompts; never fails the run. */
function syncPersonal(flags) {
  if (flags["no-sync"]) return;
  const env = { ...process.env, GIT_TERMINAL_PROMPT: "0", GCM_INTERACTIVE: "never", GIT_ASKPASS: "", SSH_ASKPASS: "" };
  // 20 s per git call: a reachable GitHub answers in a second or two; this only bounds a hung network
  const git = (...a) => spawnSync("git", ["-c", "credential.interactive=never", ...a], { encoding: "utf8", env, timeout: 20000 });
  let r;
  if (fs.existsSync(path.join(PERSONAL_DIR, ".git"))) {
    r = git("-C", PERSONAL_DIR, "fetch", "--depth", "1", "-q", "origin", "main");
    if (r.status === 0) {
      const dirty = git("-C", PERSONAL_DIR, "status", "--porcelain").stdout?.trim();
      if (!dirty && !fs.existsSync(PERSONAL_DIR + ".pending")) git("-C", PERSONAL_DIR, "reset", "--hard", "-q", "origin/main");
    }
  } else {
    r = git("clone", "--depth", "1", "-q", PERSONAL_URL, PERSONAL_DIR);
    if (r.status !== 0) fs.rmSync(PERSONAL_DIR, { recursive: true, force: true }); // no access: leave no trace
  }
  if (r.status !== 0 && loadManifest().installs.some((i) => i.source === "personal")) {
    say(dim("Note: couldn't refresh your personal skills (Skills-Personal); using the last copy. Check that Git is signed in to GitHub."));
  }
}

const { cmd, flags } = args();
syncAndHandOver(flags);
syncPersonal(flags);
const cmdZips = () => { const c = buildZips(); if (process.platform === "win32" && c.length) spawnSync("explorer", [ZIP_DIR]); };
const run = { install: cmdInstall, update: cmdUpdate, setup: cmdSetup, list: cmdList, uninstall: cmdUninstall, zips: cmdZips }[cmd];
if (!run || flags.help) {
  say("Usage: npx -y github:MayankPunghal/Skills [install|update|setup|zips|list|uninstall] [--skills=all|a,b] [--agents=claude,codex,cursor,copilot] [--scope=global|project] [--dir=PATH] [--link] [--yes] [--no-setup] [--no-zips]");
  process.exit(run ? 0 : 1);
}
Promise.resolve(run(flags)).catch((e) => { say(red(`\n✖ ${e.message}`)); process.exit(1); });
