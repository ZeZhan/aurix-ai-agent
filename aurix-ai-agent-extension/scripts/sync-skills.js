const fs = require("fs");
const path = require("path");

const extensionRoot = path.resolve(__dirname, "..");
const sourceRoot = path.resolve(extensionRoot, "..", "skills");
const destinationRoot = path.join(extensionRoot, "out", "skills");

if (!fs.existsSync(sourceRoot)) {
  throw new Error(`Canonical skills directory not found: ${sourceRoot}`);
}

fs.rmSync(destinationRoot, { recursive: true, force: true });
fs.mkdirSync(destinationRoot, { recursive: true });

const copied = [];
for (const entry of fs.readdirSync(sourceRoot, { withFileTypes: true })) {
  if (!entry.isDirectory()) {
    continue;
  }
  const source = path.join(sourceRoot, entry.name, "SKILL.md");
  if (!fs.existsSync(source)) {
    continue;
  }
  const destinationDir = path.join(destinationRoot, entry.name);
  fs.mkdirSync(destinationDir, { recursive: true });
  fs.copyFileSync(source, path.join(destinationDir, "SKILL.md"));
  copied.push(entry.name);
}

if (copied.length === 0) {
  throw new Error(`No SKILL.md files found under: ${sourceRoot}`);
}

console.log(`[skills] Synced ${copied.length} skill template(s): ${copied.join(", ")}`);
