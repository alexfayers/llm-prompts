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

  if (prBody.includes('<!--')) {
    issues.push('Remove every leftover "<!--" placeholder comment');
  }

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
const LOCKFILE = /(^|\/)(package-lock\.json|pnpm-lock\.yaml|uv\.lock)$/;
const TEST_FILE = /(^|\/)(tests?|__tests__)\/|(^|\/)test_[^/]*$|[._-]tests?\.[^/]+$/;

function countWords(prBody) {
  return parseSections(prBody)
    .filter((s) => s.heading === 'What' || s.heading === 'Why')
    .map((s) => stripPlaceholderComments(s.body))
    .join(' ')
    .split(/\s+/)
    .filter(Boolean).length;
}

function countLines(files) {
  const kept = files.filter((f) => !LOCKFILE.test(f.filename));
  const kindOf = (file) => (TEST_FILE.test(file.filename) ? 'test' : 'code');
  const lines = (file, sign) => (file.patch || '').split('\n').filter((l) => l[0] === sign).map((l) => l.slice(1).trim());
  const removed = new Map();
  const counts = { code: { added: 0, deleted: 0 }, test: { added: 0, deleted: 0 } };
  for (const file of kept) {
    for (const text of lines(file, '-')) removed.set(text, [...(removed.get(text) || []), kindOf(file)]);
  }
  for (const file of kept) {
    if (file.patch === undefined) {
      counts[kindOf(file)].added += file.additions;
      counts[kindOf(file)].deleted += file.deletions;
    }
    for (const text of lines(file, '+')) {
      if (removed.get(text)?.length && /\w/.test(text)) removed.get(text).pop();
      else counts[kindOf(file)].added += 1;
    }
  }
  for (const kinds of removed.values()) {
    for (const kind of kinds) counts[kind].deleted += 1;
  }
  return counts;
}

function findYappyTier(words, totalLines) {
  return YAPPY_TIERS.filter((t) => words > t.words || totalLines > t.lines).pop();
}

async function checkYappy({ github, context, body }) {
  const pr = context.payload.pull_request;
  const files = await github.paginate(github.rest.pulls.listFiles, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    pull_number: pr.number,
    per_page: 100,
  });
  const words = countWords(body || '');
  const counts = countLines(files);
  const total = counts.code.added + counts.code.deleted + counts.test.added + counts.test.deleted;
  const tier = findYappyTier(words, total);
  const issue = { owner: context.repo.owner, repo: context.repo.repo, issue_number: pr.number };

  for (const { name } of pr.labels || []) {
    if (name !== tier?.label && YAPPY_TIERS.some((t) => t.label === name)) {
      await github.rest.issues.removeLabel({ ...issue, name });
    }
  }

  const moreTests = counts.test.added > counts.code.added;
  const existing = await findStickyComment(github, context, YAPPY_MARKER);
  if (tier || moreTests) {
    const lines = [];
    if (tier) {
      await github.rest.issues.addLabels({ ...issue, labels: [tier.label] });
      lines.push(`This PR is ${tier.label}.\n`, `- What + Why: ${words} words (${tier.label} above ${tier.words})`);
    }
    const tierSuffix = tier ? `${tier.label} above ${tier.lines} total, ` : '';
    lines.push(`- Changed lines: ${total} (${tierSuffix}moved lines and lockfiles excluded)`);
    for (const [kind, { added, deleted }] of Object.entries(counts)) {
      const net = added - deleted;
      lines.push(`- ${kind[0].toUpperCase()}${kind.slice(1)} lines: +${added} new / -${deleted} old (net ${net > 0 ? '+' : ''}${net})`);
    }
    if (moreTests) lines.push('- More test lines than code is kinda CRAZY');
    await upsertStickyComment(github, context, YAPPY_MARKER, lines.join('\n'), existing);
  } else if (existing) {
    await upsertStickyComment(github, context, YAPPY_MARKER, 'This PR is no longer yappy.', existing);
  }
}

async function check({ github, context, core }) {
  const pr = context.payload.pull_request;
  const body = pr && (await github.rest.pulls.get({ ...context.repo, pull_number: pr.number })).data.body;
  if (pr) {
    try {
      await checkYappy({ github, context, body });
    } catch (error) {
      core.warning(`Yappy check skipped: ${error.message}`);
    }
  }
  if (!pr || pr.user?.type === 'Bot' || !body || !body.trim()) {
    return;
  }

  const templateContent = fs.readFileSync(
    path.join(process.cwd(), '.github', 'PULL_REQUEST_TEMPLATE.md'),
    'utf8'
  );
  const templateSections = parseTemplateSections(templateContent);
  const issues = findBodyIssues(templateSections, body);

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
