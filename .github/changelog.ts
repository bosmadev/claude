// Consolidated CHANGELOG + Version Bump Script
// Runs after push to main/master via GitHub Actions
//
// KEY DESIGN: Processes ALL new commits since the last changelog bot commit,
// not just HEAD. This prevents commits from being silently lost when multiple
// commits are pushed in a single push event (e.g., rapid-fire commits, batch push).

import { execSync, spawnSync } from "node:child_process";
import fs from "node:fs";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function safeExec(cmd: string, errorMsg: string): string {
  const allowedCommands = /^(git|find)\s/;
  if (!allowedCommands.test(cmd)) {
    throw new Error(`Unsafe command rejected: ${cmd}`);
  }
  try {
    return execSync(cmd, { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] });
  } catch (error: unknown) {
    const err = error as Error & { stderr?: string };
    console.error(`${errorMsg}: ${err.message}`);
    throw new Error(`${errorMsg}: ${err.stderr || err.message}`);
  }
}

function sanitizeMarkdown(text: string): string {
  return text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function detectBumpType(msg: string): "major" | "minor" | "patch" {
  const stripped = msg.replace(/^Build\s+\d+:\s*/i, "");
  const lowerMsg = stripped.toLowerCase();
  if (lowerMsg.includes("breaking change:") || lowerMsg.includes("breaking-change:")) return "major";
  if (/^(feat|fix|refactor|perf)(\(.+\))?!:/.test(lowerMsg)) return "major";
  if (/^feat(\(.+\))?:/.test(lowerMsg) || msg.includes("### feat")) return "minor";
  return "patch";
}

function isTrivia(line: string): boolean {
  const triviaPatterns = [
    /\bremov(e|ed|ing)\b.*\b(todo|fixme|hack|xxx)\b.*\bcomment/i,
    /\bremov(e|ed|ing)\b.*\binline\b.*\bcomment/i,
    /\bclean(ed|ing)?\s*up\b.*\bcomment/i,
    /\b(add|remov|updat)(e|ed|ing)\b.*\b(todo|fixme)\b/i,
    /\b(updat|correct|fix)(e|ed|ing)\b.*\bCLAUDE\.md\b/i,
    /\b(updat|correct|fix)(e|ed|ing)\b.*\bSKILL\.md\b/i,
    /\b(updat|correct|fix)(e|ed|ing)\b.*\bagent\s+(config|description)/i,
    /\bhook\s+(count|summary)\b.*\bCLAUDE\.md\b/i,
    /\bwhitespace\b/i,
    /\bformatting\s+only\b/i,
    /\bremov(e|ed|ing)\b.*\bredundant\b.*\b(ternary|comment|whitespace|import)\b/i,
    /\breview\s+agent\b.*\b(finding|addressed)\b/i,
    /\bfindings\s+addressed\b/i,
  ];
  return triviaPatterns.some((p) => p.test(line));
}

const verbs: Record<string, string> = {
  feat: "Added", fix: "Fixed", refactor: "Refactored", docs: "Updated",
  test: "Added tests for", chore: "Updated", config: "Configured",
  cleanup: "Cleaned up", perf: "Improved", style: "Styled",
};

function getHighestBuildId(): number {
  const changelogPath = "CHANGELOG.md";
  let highest = 0;
  if (fs.existsSync(changelogPath)) {
    const changelog = fs.readFileSync(changelogPath, "utf8");
    for (const match of changelog.matchAll(/\|\s*Build\s+(\d{1,6})/gi)) {
      const num = parseInt(match[1], 10);
      if (num > highest) highest = num;
    }
  }
  // Also check recent git log for Build IDs not yet in CHANGELOG
  try {
    const log = safeExec("git log --oneline -50", "Failed to read git log");
    for (const match of log.matchAll(/Build\s+(\d{1,6})/gi)) {
      const num = parseInt(match[1], 10);
      if (num > highest) highest = num;
    }
  } catch { /* ignore */ }
  return highest;
}

// ---------------------------------------------------------------------------
// Commit discovery: find ALL new commits needing CHANGELOG entries
// ---------------------------------------------------------------------------

interface CommitInfo {
  sha: string;
  subject: string;
  body: string;
  fullMessage: string;
  buildId: string | null; // from commit message, or null for auto-assign
}

function discoverNewCommits(): CommitInfo[] {
  // Find the last changelog bot commit (our anchor point)
  let lastBotSha = "";
  try {
    lastBotSha = safeExec(
      'git log --format=%H --author=github-actions --grep="update CHANGELOG" -1',
      "Failed to find last bot commit",
    ).trim();
  } catch { /* no bot commits yet */ }

  // Get all commits between last bot commit and HEAD
  // If no bot commit exists, use HEAD~20 as a reasonable limit
  let range: string;
  if (lastBotSha) {
    range = `${lastBotSha}..HEAD`;
  } else {
    range = "HEAD~20..HEAD";
  }

  console.log(`Commit discovery range: ${range}${lastBotSha ? ` (since ${lastBotSha.slice(0, 8)})` : " (no bot commits found)"}`);

  let logOutput: string;
  try {
    // Use %x00 as record separator, %x01 as field separator
    logOutput = safeExec(
      `git log ${range} --format=%H%x01%s%x01%b%x00 --reverse`,
      "Failed to get commit log",
    ).trim();
  } catch {
    // Fallback: just process HEAD
    const sha = safeExec("git rev-parse HEAD", "Failed to get HEAD").trim();
    const msg = safeExec("git log -1 --pretty=format:%B", "Failed to get commit").trim();
    const subject = msg.split("\n")[0];
    const body = msg.split("\n").slice(1).join("\n").trim();
    const buildMatch = subject.match(/Build\s+(\d{1,6})/i);
    return [{ sha, subject, body, fullMessage: msg, buildId: buildMatch ? buildMatch[1] : null }];
  }

  if (!logOutput) {
    console.log("No new commits found since last CHANGELOG update");
    process.exit(0);
  }

  const commits: CommitInfo[] = [];
  const records = logOutput.split("\0").filter((r) => r.trim());

  for (const record of records) {
    const fields = record.trim().split("\x01");
    if (fields.length < 2) continue;

    const sha = fields[0].trim();
    const subject = fields[1].trim();
    const body = (fields[2] || "").trim();

    // Skip bot commits (changelog updates, version bumps)
    if (/^(chore|docs):\s*(bump to v|update CHANGELOG)/i.test(subject)) continue;

    const buildMatch = subject.match(/Build\s+(\d{1,6})/i);
    commits.push({
      sha,
      subject,
      body,
      fullMessage: `${subject}\n\n${body}`.trim(),
      buildId: buildMatch ? buildMatch[1] : null,
    });
  }

  return commits;
}

// ---------------------------------------------------------------------------
// Extract summary + changes from a single commit message
// ---------------------------------------------------------------------------

function extractCommitContent(commit: CommitInfo): { summary: string; changes: string[] } {
  const lines = commit.fullMessage.split("\n");
  let summary = "";
  let changes: string[] = [];

  // Try structured ## Summary section
  const summaryIdx = lines.findIndex((l) => l.startsWith("## Summary"));
  if (summaryIdx !== -1) {
    let endIdx = lines.findIndex((l, i) => i > summaryIdx && l.startsWith("## "));
    if (endIdx === -1) endIdx = lines.length;
    summary = sanitizeMarkdown(lines.slice(summaryIdx + 1, endIdx).join("\n").trim());
  }

  // Try structured ## Commits / ## Changes section
  const commitsIdx = lines.findIndex((l) => l.startsWith("## Commits") || l.startsWith("## Changes"));
  if (commitsIdx !== -1) {
    let endIdx = lines.findIndex((l, i) => i > commitsIdx && l.startsWith("## "));
    if (endIdx === -1) endIdx = lines.length;
    changes = lines
      .slice(commitsIdx + 1, endIdx)
      .filter((l) => l.trim().startsWith("-") && !l.trim().startsWith("###"))
      .map((l) =>
        l.replace(/^-\s*b\d+-\d+:\s*/, "- ").replace(
          /^-\s*(feat|fix|refactor|docs|test|chore|config|cleanup|perf|style)(\([^)]+\))?:\s*/i,
          (_, type: string) => `- ${verbs[type.toLowerCase()] || "Updated"} `,
        ),
      );
  }

  // Fallback: use commit subject + body bullets
  if (!summary && changes.length === 0) {
    summary = commit.subject
      .replace(/Build\s+\d+/i, "")
      .replace(/\(#\d+\)/, "")
      .replace(/^[\s:]+|[\s:]+$/g, "")
      .trim();
    const bodyLines = lines.slice(1).filter((l) => l.trim().startsWith("-"));
    if (bodyLines.length > 0) {
      changes = bodyLines.map((l) => l.trim());
    }
  }

  // Filter trivia
  changes = changes.filter((l) => !isTrivia(l));

  return { summary, changes };
}

// ---------------------------------------------------------------------------
// Build a CHANGELOG entry for one commit
// ---------------------------------------------------------------------------

function buildChangelogEntry(
  commit: CommitInfo,
  buildId: string,
  version: string | null,
  githubRepo: string,
): string {
  const date = new Date().toISOString().split("T")[0];
  const badgeDate = date.replace(/-/g, "--");

  const badgeLabel = version ? `v${version}` : `Build_${buildId}`;
  const prMatch = commit.subject.match(/\(#(\d+)\)/);
  const prNumber = prMatch ? prMatch[1] : null;
  let badgeUrl = "#";
  if (githubRepo) {
    badgeUrl = prNumber
      ? `https://github.com/${githubRepo}/pull/${prNumber}`
      : `https://github.com/${githubRepo}/commit/${commit.sha}`;
  }

  const badge = `[![${badgeLabel}](https://img.shields.io/badge/${badgeLabel}-${badgeDate}-333333.svg)](${badgeUrl})`;

  const { summary, changes } = extractCommitContent(commit);

  let entry = `---\n\n## ${badge} | Build ${buildId}\n\n`;
  if (summary) entry += `${summary}\n\n`;
  if (changes.length > 0) {
    const checkboxChanges = changes.map((l) =>
      /^- \[x\]/.test(l) ? l : l.replace(/^- /, "- [x] "),
    );
    entry += `${checkboxChanges.join("\n")}\n`;
  }
  entry += "\n";
  return entry;
}

// ---------------------------------------------------------------------------
// Insert entry into CHANGELOG content (returns updated content)
// ---------------------------------------------------------------------------

function insertIntoChangelog(changelog: string, entry: string): string {
  const headerComment = "<!-- DO NOT EDIT MANUALLY";
  const headerEnd = "# Changelog";

  if (changelog.includes(headerComment)) {
    const headerIdx = changelog.indexOf(headerEnd);
    if (headerIdx !== -1) {
      const insertPoint = changelog.indexOf("\n", headerIdx) + 1;
      return changelog.slice(0, insertPoint) + "\n" + entry + changelog.slice(insertPoint);
    }
  } else if (changelog.startsWith("# Changelog")) {
    const insertPoint = changelog.indexOf("\n") + 1;
    return changelog.slice(0, insertPoint) + "\n" + entry + changelog.slice(insertPoint);
  }
  return `<!-- DO NOT EDIT MANUALLY - Auto-generated by GitHub Actions. -->\n# Changelog\n\n${entry}${changelog}`;
}

// ===========================================================================
// Main
// ===========================================================================

// Discover all new commits
const commits = discoverNewCommits();
if (commits.length === 0) {
  console.log("No new user commits found, nothing to update");
  process.exit(0);
}

console.log(`Found ${commits.length} new commit(s) to process`);

// Read current CHANGELOG for dedup + highest Build ID
const changelogPath = "CHANGELOG.md";
let changelog = fs.existsSync(changelogPath)
  ? fs.readFileSync(changelogPath, "utf8")
  : "";

const githubRepo = process.env.GITHUB_REPOSITORY || "";
let highestBuild = getHighestBuildId();
let combinedBumpType: "major" | "minor" | "patch" = "patch";
const processedBuildIds: string[] = [];

// Process commits oldest-first (already reversed in discovery)
for (const commit of commits) {
  // Determine Build ID: use commit's own or auto-assign
  let buildId: string;
  if (commit.buildId) {
    buildId = commit.buildId;
  } else {
    highestBuild++;
    buildId = String(highestBuild);
    console.log(`Auto-assigned Build ${buildId} to: ${commit.subject.slice(0, 60)}`);
  }

  const buildIdNum = parseInt(buildId, 10);
  if (buildIdNum < 1 || buildIdNum > 999999) {
    console.warn(`Skipping invalid build ID ${buildId} for ${commit.sha}`);
    continue;
  }

  // Dedup: skip if Build ID already in CHANGELOG
  const duplicateCheck = new RegExp(`^## .*Build ${buildId}(\\s|\\||$)`, "m");
  if (duplicateCheck.test(changelog)) {
    console.log(`Build ${buildId} already in CHANGELOG, skipping: ${commit.subject.slice(0, 60)}`);
    continue;
  }

  // Track highest bump type across all commits (for version bump)
  const bt = detectBumpType(commit.fullMessage);
  if (bt === "major") combinedBumpType = "major";
  else if (bt === "minor" && combinedBumpType !== "major") combinedBumpType = "minor";

  // Build and insert CHANGELOG entry (no version in badge — version determined after all entries)
  const entry = buildChangelogEntry(commit, buildId, null, githubRepo);
  changelog = insertIntoChangelog(changelog, entry);
  processedBuildIds.push(buildId);

  // Update highest for next iteration
  if (buildIdNum > highestBuild) highestBuild = buildIdNum;

  console.log(`✓ Added CHANGELOG entry for Build ${buildId}: ${commit.subject.slice(0, 60)}`);
}

if (processedBuildIds.length === 0) {
  console.log("All commits already in CHANGELOG, nothing to update");
  process.exit(0);
}

// === Version Bump (single bump for all new entries) ===
console.log("[2/3] Version bump...");

let pkgPath: string | null = null;
try {
  const result = safeExec(
    'find . -name "package.json" -not -path "*/node_modules/*" | head -1',
    "Failed to find package.json",
  ).trim();
  if (result) pkgPath = result;
} catch {
  console.log("No package.json found, skipping version bump");
}

let newVersion: string | null = null;
if (pkgPath && fs.existsSync(pkgPath)) {
  const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
  const currentVersion: string = pkg.version || "0.0.0";
  const semverRegex = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
  if (!semverRegex.test(currentVersion)) {
    throw new Error(`Invalid semver: ${currentVersion}`);
  }

  const [major, minor, patch] = currentVersion.split(".").map(Number);

  if (combinedBumpType === "major") {
    newVersion = `${major + 1}.0.0`;
  } else if (combinedBumpType === "minor") {
    newVersion = `${major}.${minor + 1}.0`;
  } else {
    newVersion = `${major}.${minor}.${patch + 1}`;
  }

  console.log(`${combinedBumpType.toUpperCase()} bump: ${currentVersion} → ${newVersion}`);
  pkg.version = newVersion;
  fs.writeFileSync(pkgPath, `${JSON.stringify(pkg, null, "\t")}\n`);
  console.log(`✓ Updated ${pkgPath} to v${newVersion}`);

  // Patch the latest CHANGELOG entry badge with the version
  if (newVersion) {
    const latestBuild = processedBuildIds[processedBuildIds.length - 1];
    changelog = changelog.replace(
      new RegExp(`Build_${latestBuild}`, "g"),
      `v${newVersion}`,
    );
  }
}

// Write CHANGELOG
fs.writeFileSync(changelogPath, changelog);
console.log(`✓ Updated CHANGELOG.md for Build(s) ${processedBuildIds.join(", ")}`);

// === Commit & Push ===
console.log("[3/3] Creating consolidated commit...");

safeExec('git config user.name "github-actions[bot]"', "Failed to set git user");
safeExec('git config user.email "github-actions[bot]@users.noreply.github.com"', "Failed to set git email");
safeExec("git add CHANGELOG.md", "Failed to stage CHANGELOG");
if (pkgPath) {
  safeExec(`git add ${pkgPath}`, "Failed to stage package.json");
}

const latestBuild = processedBuildIds[processedBuildIds.length - 1];
const msg = newVersion
  ? `chore: bump to v${newVersion} and update CHANGELOG for Build ${latestBuild}`
  : `docs: update CHANGELOG for Build ${latestBuild}`;

const commitResult = spawnSync("git", ["commit", "-m", msg], { encoding: "utf8" });
if (commitResult.status !== 0) {
  const status = safeExec("git status --porcelain", "Failed to get git status");
  if (status.trim() === "") {
    console.log("No changes to commit (working tree clean)");
    process.exit(0);
  }
  throw new Error(`Commit failed: ${commitResult.stderr || commitResult.stdout}`);
}
console.log(`✓ Committed: ${msg}`);

// Pull --rebase to handle queued changelog runs
const pullResult = spawnSync("git", ["pull", "--rebase", "origin", "main"], { encoding: "utf8" });
if (pullResult.status !== 0) {
  console.warn(`⚠ Pull --rebase failed (may be first push): ${pullResult.stderr || ""}`);
}

// Push
const pushResult = spawnSync("git", ["push"], { encoding: "utf8" });
if (pushResult.status !== 0) {
  const errMsg = pushResult.stderr || pushResult.stdout || "Unknown push error";
  console.error(`✗ Push failed: ${errMsg}`);
  throw new Error(`Push failed (branch protection?): ${errMsg}`);
}

console.log(`✓ Pushed consolidated commit`);
if (newVersion) console.log(`✓ Version bumped: v${newVersion}`);
console.log(`✓ CHANGELOG updated: Build(s) ${processedBuildIds.join(", ")}`);
