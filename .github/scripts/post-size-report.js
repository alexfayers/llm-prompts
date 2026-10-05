const fs = require('fs');
const { findStickyComment, upsertStickyComment } = require('./sticky-comment.js');

const MARKER = '<!-- prompt-size-report -->';
const MAX_COMMENT_LENGTH = 60000;
const DETAILS_TAG = '<details>';
const HEADLINE_SECTION_COUNT = 2;
const SUMMARY_POINTER = '\n\nFull table in the job summary.\n';

function fits(markdown) {
  return `${MARKER}\n${markdown}`.length <= MAX_COMMENT_LENGTH;
}

function buildCommentBody(markdown) {
  if (fits(markdown)) {
    return markdown;
  }
  const detailsStart = markdown.lastIndexOf(DETAILS_TAG);
  const summaryOnly = detailsStart === -1 ? markdown : markdown.slice(0, detailsStart);
  const withoutDetails = `${summaryOnly.trimEnd()}${SUMMARY_POINTER}`;
  if (fits(withoutDetails)) {
    return withoutDetails;
  }
  const headline = markdown.split('\n\n').slice(0, HEADLINE_SECTION_COUNT).join('\n\n');
  return `${headline}${SUMMARY_POINTER}`;
}

async function report({ github, context, core, path }) {
  const markdown = fs.readFileSync(path, 'utf8');
  await core.summary.addRaw(markdown).write();

  try {
    const existing = await findStickyComment(github, context, MARKER);
    await upsertStickyComment(github, context, MARKER, buildCommentBody(markdown), existing);
  } catch (error) {
    if (error.status !== 403) {
      throw error;
    }
    core.warning(`Could not post the prompt size comment: ${error.message}`);
  }
}

async function reportForRun({ github, context, core, dir }) {
  const prNumber = fs.readFileSync(`${dir}/pr-number`, 'utf8').trim();
  if (!/^\d+$/.test(prNumber)) {
    core.warning(`Ignoring size report with invalid PR number: ${prNumber}`);
    return;
  }
  const { data: pr } = await github.rest.pulls.get({ ...context.repo, pull_number: Number(prNumber) });
  if (pr.head.sha !== context.payload.workflow_run.head_sha) {
    core.warning(`Ignoring size report for PR #${prNumber}: its head is not the reported commit`);
    return;
  }
  const prContext = { repo: context.repo, payload: { pull_request: { number: Number(prNumber) } } };
  await report({ github, context: prContext, core, path: `${dir}/size-report.md` });
}

module.exports = { report, reportForRun };
