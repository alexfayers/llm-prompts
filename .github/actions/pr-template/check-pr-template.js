const fs = require('fs');
const path = require('path');
const { findStickyComment, upsertStickyComment } = require('../../scripts/sticky-comment.js');

const MARKER = '<!-- pr-template-check -->';
const OPTIONAL_SECTIONS = ['Dependencies', 'Issues'];

function parseSections(markdown) {
  const lines = markdown.split('\n');
  const sections = [];
  let current = null;
  for (const line of lines) {
    const match = line.match(/^##\s+(.*?)\s*$/);
    if (match) {
      current = { heading: match[1], body: [] };
      sections.push(current);
    } else if (current) {
      current.body.push(line);
    }
  }
  return sections.map((s) => ({ heading: s.heading, body: s.body.join('\n') }));
}

function stripPlaceholderComments(text) {
  let stripped = text;
  let previous;
  do {
    previous = stripped;
    stripped = stripped.replace(/<!--[\s\S]*?-->/g, '');
  } while (stripped !== previous);
  return stripped.trim();
}

function parseTemplateSections(markdown) {
  return { sections: parseSections(markdown) };
}

function findBodyIssues(templateSections, prBody) {
  const { sections } = templateSections;
  const prSections = parseSections(prBody);
  const issues = [];

  for (const templateSection of sections) {
    if (OPTIONAL_SECTIONS.includes(templateSection.heading)) {
      continue;
    }

    const prSection = prSections.find((s) => s.heading === templateSection.heading);
    if (!prSection) {
      issues.push(`Missing section: "## ${templateSection.heading}"`);
      continue;
    }

    if (stripPlaceholderComments(prSection.body) === '') {
      issues.push(`Section "## ${templateSection.heading}" was left empty`);
    }
  }

  return issues;
}

const YAPPY_MARKER = '<!-- pr-yappy-check -->';
const YAPPY_TIERS = [
  { label: 'slightly yappy', words: 120, lines: 100 },
  { label: 'yappy', words: 200, lines: 200 },
  { label: 'very yappy', words: 300, lines: 400 },
];
const LOCKFILE = /(^|\/)(package-lock\.json|uv\.lock)$/;
const TEST_FILE = /(^|\/)(tests?|__tests__)\/|(^|\/)test_[^/]*$|[._-]tests?\.[^/]+$/;

function countWords(prBody) {
  return parseSections(prBody)
    .filter((s) => s.heading === 'What' || s.heading === 'Why')
    .map((s) => stripPlaceholderComments(s.body))
    .join(' ')
    .split(/\s+/)
    .filter(Boolean).length;
}

function countAddedLines(files) {
  const kept = files.filter((f) => !LOCKFILE.test(f.filename));
  const lines = (file, sign) => (file.patch || '').split('\n').filter((l) => l[0] === sign).map((l) => l.slice(1).trim());
  const removed = new Map();
  for (const text of kept.flatMap((f) => lines(f, '-')).filter((t) => /\w/.test(t))) {
    removed.set(text, (removed.get(text) || 0) + 1);
  }
  const added = { code: 0, test: 0 };
  for (const file of kept) {
    const kind = TEST_FILE.test(file.filename) ? 'test' : 'code';
    if (file.patch === undefined) added[kind] += file.additions;
    for (const text of lines(file, '+')) {
      if (removed.get(text) > 0) removed.set(text, removed.get(text) - 1);
      else added[kind] += 1;
    }
  }
  return added;
}

function findYappyTier(words, addedLines) {
  return YAPPY_TIERS.filter((t) => words > t.words || addedLines > t.lines).pop();
}

async function checkYappy({ github, context }) {
  const pr = context.payload.pull_request;
  const files = await github.paginate(github.rest.pulls.listFiles, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    pull_number: pr.number,
    per_page: 100,
  });
  const words = countWords(pr.body || '');
  const added = countAddedLines(files);
  const tier = findYappyTier(words, added.code + added.test);
  const issue = { owner: context.repo.owner, repo: context.repo.repo, issue_number: pr.number };

  for (const { name } of pr.labels || []) {
    if (name !== tier?.label && YAPPY_TIERS.some((t) => t.label === name)) {
      await github.rest.issues.removeLabel({ ...issue, name });
    }
  }

  if (tier) {
    const existing = await findStickyComment(github, context, YAPPY_MARKER);
    await github.rest.issues.addLabels({ ...issue, labels: [tier.label] });
    await upsertStickyComment(
      github,
      context,
      YAPPY_MARKER,
      `This PR is ${tier.label}.\n\n- What + Why: ${words} words (${tier.label} above ${tier.words})\n- Added lines: ${added.code} code, ${added.test} test (${tier.label} above ${tier.lines} total, lockfiles excluded)`,
      existing
    );
  }
}

async function check({ github, context, core }) {
  const pr = context.payload.pull_request;
  if (pr) {
    try {
      await checkYappy({ github, context });
    } catch (error) {
      core.warning(`Yappy check skipped: ${error.message}`);
    }
  }
  if (!pr || !pr.body || !pr.body.trim()) {
    return;
  }

  const templateContent = fs.readFileSync(
    path.join(process.cwd(), '.github', 'PULL_REQUEST_TEMPLATE.md'),
    'utf8'
  );
  const templateSections = parseTemplateSections(templateContent);
  const issues = findBodyIssues(templateSections, pr.body);

  const existing = await findStickyComment(github, context, MARKER);

  if (issues.length > 0) {
    core.setFailed(`PR template check failed:\n${issues.map((m) => `- ${m}`).join('\n')}`);
    await upsertStickyComment(
      github,
      context,
      MARKER,
      `The PR template is missing required content:\n\n${issues.map((m) => `- ${m}`).join('\n')}`,
      existing
    );
    return;
  }

  if (existing) {
    await upsertStickyComment(github, context, MARKER, 'PR template check passed.', existing);
  }
}

module.exports = { parseTemplateSections, findBodyIssues, check };
