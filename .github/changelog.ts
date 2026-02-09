// Consolidated CHANGELOG + Version Bump Script
// Runs after merge to main/master
// Single atomic commit with both updates

import fs from 'node:fs';
import { execSync, spawnSync } from 'node:child_process';

function safeExec(cmd: string, errorMsg: string): string {
  // Validate command is safe (git/find only, no shell expansion)
  const allowedCommands = /^(git|find)\s/;
  if (!allowedCommands.test(cmd)) {
    throw new Error(`Unsafe command rejected: ${cmd}`);
  }
  try {
    return execSync(cmd, { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
  } catch (error: unknown) {
    const err = error as Error & { stderr?: string };
    console.error(`${errorMsg}: ${err.message}`);
    throw new Error(`${errorMsg}: ${err.stderr || err.message}`);
  }
}

// Get the latest commit message
const commitMsg = safeExec('git log -1 --pretty=format:%B', 'Failed to get commit message').trim();
const commitSubject = commitMsg.split('\n')[0];

// Extract build ID from commit subject
const buildMatch = commitSubject.match(/Build\s+(\d{1,6})/i);
if (!buildMatch) {
  console.log('No build ID found in commit, skipping CHANGELOG update');
  process.exit(0);
}

const buildId = buildMatch[1];
const buildIdNum = parseInt(buildId, 10);
if (buildIdNum < 1 || buildIdNum > 999999) {
  throw new Error(`Invalid build ID: ${buildId} (must be 1-999999)`);
}

// Extract PR number from commit subject, e.g. "feat: auth (#42)" → 42
const prMatch = commitSubject.match(/\(#(\d+)\)/);
const prNumber = prMatch ? prMatch[1] : null;

// Get commit SHA for fallback URL
const commitSha = safeExec('git rev-parse HEAD', 'Failed to get commit SHA').trim();

// Build repo URL from GITHUB_REPOSITORY env var (e.g. "bosmadev/claude")
const githubRepo = process.env.GITHUB_REPOSITORY || '';

// === PART 1: Version Bump ===
console.log('[1/3] Detecting version bump type...');

function detectBumpType(msg: string): 'major' | 'minor' | 'patch' {
  // Strip "Build N: " prefix before checking conventional commit type
  const stripped = msg.replace(/^Build\s+\d+:\s*/i, '');
  const lowerMsg = stripped.toLowerCase();

  // Check for BREAKING CHANGE
  if (lowerMsg.includes('breaking change:') || lowerMsg.includes('breaking-change:')) {
    return 'major';
  }

  // Check for conventional commit with !
  if (/^(feat|fix|refactor|perf)(\(.+\))?!:/.test(lowerMsg)) {
    return 'major';
  }

  // Check for feat (new feature)
  if (/^feat(\(.+\))?:/.test(lowerMsg) || msg.includes('### feat')) {
    return 'minor';
  }

  // Default to patch
  return 'patch';
}

// Find package.json
let pkgPath: string | null = null;
try {
  const result = safeExec('find . -name "package.json" -not -path "*/node_modules/*" | head -1', 'Failed to find package.json').trim();
  if (result) pkgPath = result;
} catch {
  console.log('No package.json found, skipping version bump');
}

let newVersion: string | null = null;
if (pkgPath && fs.existsSync(pkgPath)) {
  const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
  const currentVersion: string = pkg.version || '0.0.0';
  console.log(`Current version: ${currentVersion}`);

  // Validate semver
  const semverRegex = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
  if (!semverRegex.test(currentVersion)) {
    throw new Error(`Invalid semver: ${currentVersion}`);
  }

  const [major, minor, patch] = currentVersion.split('.').map(Number);
  const bumpType = detectBumpType(commitMsg);

  if (bumpType === 'major') {
    newVersion = `${major + 1}.0.0`;
    console.log(`MAJOR bump: ${currentVersion} → ${newVersion}`);
  } else if (bumpType === 'minor') {
    newVersion = `${major}.${minor + 1}.0`;
    console.log(`MINOR bump: ${currentVersion} → ${newVersion}`);
  } else {
    newVersion = `${major}.${minor}.${patch + 1}`;
    console.log(`PATCH bump: ${currentVersion} → ${newVersion}`);
  }

  // Update package.json
  pkg.version = newVersion;
  fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, '\t') + '\n');
  console.log(`✓ Updated ${pkgPath} to v${newVersion}`);
}

// === PART 2: CHANGELOG Update ===
console.log('[2/3] Updating CHANGELOG.md...');

const date = new Date().toISOString().split('T')[0];

// Extract summary
function sanitizeMarkdown(text: string): string {
  return text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

let summary = '';
const lines = commitMsg.split('\n');
const summaryIdx = lines.findIndex(l => l.startsWith('## Summary'));
if (summaryIdx !== -1) {
  let endIdx = lines.findIndex((l, i) => i > summaryIdx && l.startsWith('## '));
  if (endIdx === -1) endIdx = lines.length;
  summary = sanitizeMarkdown(lines.slice(summaryIdx + 1, endIdx).join('\n').trim());
}

// Extract changes - FLATTEN categories (no ### feat, ### fix)
const verbs: Record<string, string> = {
  feat: 'Added',
  fix: 'Fixed',
  refactor: 'Refactored',
  docs: 'Updated',
  test: 'Added tests for',
  chore: 'Updated',
  config: 'Configured',
  cleanup: 'Cleaned up',
  perf: 'Improved',
  style: 'Styled'
};

let changes: string[] = [];
const commitsIdx = lines.findIndex(l => l.startsWith('## Commits') || l.startsWith('## Changes'));
if (commitsIdx !== -1) {
  let endIdx = lines.findIndex((l, i) => i > commitsIdx && l.startsWith('## '));
  if (endIdx === -1) endIdx = lines.length;

  // Extract all bullets, skip ### category headers
  changes = lines.slice(commitsIdx + 1, endIdx)
    .filter(l => {
      const trimmed = l.trim();
      return trimmed.startsWith('-') && !trimmed.startsWith('###');
    })
    .map(l => {
      // Clean up: "b101-1: feat(scope): add X" → "- Added X"
      return l.replace(/^-\s*b\d+-\d+:\s*/, '- ')
              .replace(/^-\s*(feat|fix|refactor|docs|test|chore|config|cleanup|perf|style)(\([^)]+\))?:\s*/i, (_, type: string) => {
                return `- ${verbs[type.toLowerCase()] || 'Updated'} `;
              });
    });
}

// Fallback: if no structured sections found, use commit subject + body bullets
if (!summary && changes.length === 0) {
  // Use commit subject (strip Build ID and conventional prefix for summary)
  summary = commitSubject
    .replace(/Build\s+\d+/i, '')
    .replace(/\(#\d+\)/, '')
    .replace(/^[\s:]+|[\s:]+$/g, '')
    .trim();

  // Extract bullet points from commit body (lines starting with -)
  const bodyLines = lines.slice(1).filter(l => l.trim().startsWith('-'));
  if (bodyLines.length > 0) {
    changes = bodyLines.map(l => l.trim());
  }
}

// Build CHANGELOG entry with badge format
const badgeDate = date.replace(/-/g, '--'); // shields.io escaping
let badgeLabel: string;
let badgeUrl: string;

if (newVersion) {
  badgeLabel = `v${newVersion}`;
} else {
  badgeLabel = `Build_${buildId}`;
}

if (githubRepo) {
  if (prNumber) {
    badgeUrl = `https://github.com/${githubRepo}/pull/${prNumber}`;
  } else {
    badgeUrl = `https://github.com/${githubRepo}/commit/${commitSha}`;
  }
} else {
  badgeUrl = '#';
}

const badge = `[![${badgeLabel}](https://img.shields.io/badge/${badgeLabel}-${badgeDate}-333333.svg)](${badgeUrl})`;

let entry = `---\n\n## ${badge} | Build ${buildId}\n\n`;
if (summary) {
  entry += `${summary}\n\n`;
}
if (changes.length > 0) {
  // Use [x] checkbox style for change items
  const checkboxChanges = changes.map(l => l.replace(/^- /, '- [x] '));
  entry += checkboxChanges.join('\n') + '\n';
}
entry += '\n';

// Update CHANGELOG.md
const changelogPath = 'CHANGELOG.md';
let changelog = '';
if (fs.existsSync(changelogPath)) {
  changelog = fs.readFileSync(changelogPath, 'utf8');

  // Deduplication check
  const duplicateCheck = new RegExp(`Build ${buildId}(\\s|\\||$)`, 'm');
  if (duplicateCheck.test(changelog)) {
    console.log(`Build ${buildId} already in CHANGELOG, skipping duplicate`);
    process.exit(0);
  }
}

// Insert after header or at top
const headerComment = '<!-- DO NOT EDIT MANUALLY';
const headerEnd = '# Changelog';

if (changelog.includes(headerComment)) {
  const headerIdx = changelog.indexOf(headerEnd);
  if (headerIdx !== -1) {
    const insertPoint = changelog.indexOf('\n', headerIdx) + 1;
    changelog = changelog.slice(0, insertPoint) + '\n' + entry + changelog.slice(insertPoint);
  }
} else if (changelog.startsWith('# Changelog')) {
  const insertPoint = changelog.indexOf('\n') + 1;
  changelog = changelog.slice(0, insertPoint) + '\n' + entry + changelog.slice(insertPoint);
} else {
  changelog = `<!-- DO NOT EDIT MANUALLY - Auto-generated by GitHub Actions. Use @claude prepare or /openpr for PR summaries. -->\n# Changelog\n\n${entry}${changelog}`;
}

fs.writeFileSync(changelogPath, changelog);
console.log(`✓ Updated CHANGELOG.md for Build ${buildId}`);

// === PART 3: Commit & Push (Single Atomic Commit) ===
console.log('[3/3] Creating consolidated commit...');

safeExec('git config user.name "github-actions[bot]"', 'Failed to set git user');
safeExec('git config user.email "github-actions[bot]@users.noreply.github.com"', 'Failed to set git email');
safeExec('git add CHANGELOG.md', 'Failed to stage CHANGELOG');
if (pkgPath) {
  safeExec(`git add ${pkgPath}`, 'Failed to stage package.json');
}

try {
  const msg = newVersion
    ? `chore: bump to v${newVersion} and update CHANGELOG for Build ${buildId}`
    : `docs: update CHANGELOG for Build ${buildId}`;

  const result = spawnSync('git', ['commit', '-m', msg], { encoding: 'utf8' });
  if (result.error) throw new Error(`Commit failed: ${result.error.message}`);

  safeExec('git push', 'Push failed');
  console.log(`✓ Pushed consolidated commit`);
  if (newVersion) {
    console.log(`✓ Version bumped: v${newVersion}`);
  }
  console.log(`✓ CHANGELOG updated: Build ${buildId}`);
} catch (commitError: unknown) {
  const err = commitError as Error;
  const status = safeExec('git status --porcelain', 'Failed to get git status');
  if (status.trim() === '') {
    console.log('No changes to commit');
  } else {
    throw new Error(`Git commit/push failed: ${err.message}`);
  }
}
