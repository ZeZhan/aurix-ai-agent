const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const childProcess = require("child_process");

const extensionRoot = path.resolve(__dirname, "..");
const expectedUvVersion = "0.12.0";
const expectedUvSha256 = "268cd62b99395eb53825795518e067e4b27ec4b445175df343824689f307c807";
const vsceName = process.platform === "win32" ? "vsce.cmd" : "vsce";
const vsceCandidates = [
  path.join(extensionRoot, "node_modules", ".bin", vsceName),
  path.resolve(extensionRoot, "..", "..", "node_modules", ".bin", vsceName),
];

const vscePath = vsceCandidates.find((candidate) => fs.existsSync(candidate));

if (!vscePath) {
  console.error("vsce not found.");
  console.error("Install dependencies in packages/aurix-ai-agent-extension or provide vsce in the repo root node_modules.");
  console.error(`Checked:\n- ${vsceCandidates.join("\n- ")}`);
  process.exit(1);
}

const bundledUvPath = path.join(extensionRoot, "out", "vendor", "uv", "win32-x64", "uv.exe");
const uvCandidates = [
  process.env.AURIX_BUNDLED_UV_PATH,
  path.join(os.homedir(), ".local", "bin", "uv.exe"),
  path.join(os.homedir(), ".cargo", "bin", "uv.exe"),
  process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Microsoft", "WinGet", "Links", "uv.exe"),
].filter(Boolean);

const whereUv = childProcess.spawnSync("where.exe", ["uv"], { encoding: "utf8", windowsHide: true });
if (whereUv.status === 0) {
  uvCandidates.push(...whereUv.stdout.split(/\r?\n/).map((value) => value.trim()).filter(Boolean));
}

const uvSource = uvCandidates.find((candidate) => fs.existsSync(candidate));
if (!uvSource) {
  console.error("uv.exe is required to package the zero-setup Windows VSIX.");
  console.error("Install uv or set AURIX_BUNDLED_UV_PATH to a trusted uv.exe.");
  process.exit(1);
}

const uvVersionResult = childProcess.spawnSync(uvSource, ["--version"], {
  encoding: "utf8",
  windowsHide: true,
});
const uvVersionOutput = uvVersionResult.stdout.trim();
if (uvVersionResult.status !== 0 || !uvVersionOutput.startsWith(`uv ${expectedUvVersion} `)) {
  console.error(`Expected uv ${expectedUvVersion}, received: ${uvVersionOutput || "unavailable"}`);
  process.exit(1);
}

const uvSha256 = crypto.createHash("sha256").update(fs.readFileSync(uvSource)).digest("hex");
if (uvSha256 !== expectedUvSha256) {
  console.error(`uv.exe SHA-256 mismatch. Expected ${expectedUvSha256}, received ${uvSha256}.`);
  process.exit(1);
}

fs.mkdirSync(path.dirname(bundledUvPath), { recursive: true });
fs.copyFileSync(uvSource, bundledUvPath);
console.log(`[package] Bundled uv ${expectedUvVersion}: ${uvSource}`);

const requiredFiles = [
  path.join(extensionRoot, "out", "extension.js"),
  path.join(extensionRoot, "out", "skills", "aurix-cross-vendor-migration", "SKILL.md"),
  path.join(extensionRoot, "server", "aurix-mcp-server-py", "src", "aurix_mcp_server", "__main__.py"),
  path.join(extensionRoot, "server", "aurix-mcp-server-py", "examples.index.json"),
  path.join(extensionRoot, "server", "aurix-mcp-server-py", "examples.manifest.json.gz"),
  bundledUvPath,
  path.join(extensionRoot, "LICENSE"),
  path.join(extensionRoot, "THIRD_PARTY_NOTICES.txt"),
];

const missingFiles = requiredFiles.filter((filePath) => !fs.existsSync(filePath));
if (missingFiles.length > 0) {
  console.error("Missing build output required for packaging:");
  for (const filePath of missingFiles) {
    console.error(`- ${filePath}`);
  }
  process.exit(1);
}

const args = [
  "package",
  "--no-dependencies",
  "--no-rewrite-relative-links",
  // Platform-specific build: bundles the win32-x64 uv executable used to provision Python.
  // VS Code on a non-matching platform will refuse to install this VSIX.
  "--target", "win32-x64",
  "-o", "aurix-ai-agent-extension-win32-x64.vsix",
];

if (process.platform === "win32" && vscePath.toLowerCase().endsWith(".cmd")) {
  childProcess.execFileSync("cmd.exe", ["/c", vscePath, ...args], {
    cwd: extensionRoot,
    stdio: "inherit",
  });
}
else {
  childProcess.execFileSync(vscePath, args, {
    cwd: extensionRoot,
    stdio: "inherit",
  });
}
