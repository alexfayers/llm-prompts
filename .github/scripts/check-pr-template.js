const fs = require('fs');
const path = require('path');

const MARKER = '<!-- pr-template-check -->';

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
  return text.replace(/<!--[\s\S]*?-->/g, '').trim();
}

function extractChecklistItems(body) {
  const items = [];
  for (const line of body.split('\n')) {
    const match = line.match(/^\s*-\s*\[[ xX]\]\s*(.+?)\s*$/);
    if (match) {
      items.push(match[1]);
    }
  }
  return items;
}

function parseTemplateSections(markdown) {
  const sections = parseSections(markdown);
  const checksSection = sections.find((s) => s.heading === 'Checks');
  const checklistItems = checksSection ? extractChecklistItems(checksSection.body) : [];
  return { sections, checklistItems };
}

function findBodyIssues(templateSections, prBody) {
  const { sections, checklistItems } = templateSections;
  const prSections = parseSections(prBody);
  const issues = [];

  for (const templateSection of sections) {
    const prSection = prSections.find((s) => s.heading === templateSection.heading);
    if (!prSection) {
      issues.push(`Missing section: "## ${templateSection.heading}"`);
      continue;
    }

    if (templateSection.heading === 'Checks') {
      for (const item of checklistItems) {
        if (!prSection.body.includes(item)) {
          issues.push(`"## Checks" is missing item: "${item}"`);
        }
      }
      continue;
    }

    if (stripPlaceholderComments(prSection.body) === '') {
      issues.push(`Section "## ${templateSection.heading}" was left empty`);
    }
  }

  return issues;
}

async function findExistingComment(github, context) {
  const comments = await github.rest.issues.listComments({
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: context.payload.pull_request.number,
  });
  return comments.data.find((c) => c.body.includes(MARKER));
}

async function postComment(github, context, existing, body) {
  const fullBody = `${MARKER}\n${body}`;
  if (existing) {
    await github.rest.issues.updateComment({
      owner: context.repo.owner,
      repo: context.repo.repo,
      comment_id: existing.id,
      body: fullBody,
    });
  } else {
    await github.rest.issues.createComment({
      owner: context.repo.owner,
      repo: context.repo.repo,
      issue_number: context.payload.pull_request.number,
      body: fullBody,
    });
  }
}

async function check({ github, context, core }) {
  const pr = context.payload.pull_request;
  if (!pr || pr.draft === true || !pr.body || !pr.body.trim()) {
    return;
  }

  const templateContent = fs.readFileSync(
    path.join(process.cwd(), '.github', 'PULL_REQUEST_TEMPLATE.md'),
    'utf8'
  );
  const templateSections = parseTemplateSections(templateContent);
  const issues = findBodyIssues(templateSections, pr.body);

  const existing = await findExistingComment(github, context);

  if (issues.length > 0) {
    core.setFailed(`PR template check failed:\n${issues.map((m) => `- ${m}`).join('\n')}`);
    await postComment(
      github,
      context,
      existing,
      `The PR template is missing required content:\n\n${issues.map((m) => `- ${m}`).join('\n')}`
    );
    return;
  }

  if (existing) {
    await postComment(github, context, existing, 'PR template check passed.');
  }
}

module.exports = { parseTemplateSections, findBodyIssues, check };
