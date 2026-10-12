// Re-derive these IDs with: gh project field-list 4 --owner alexfayers --format json
const PROJECT_ID = 'PVT_kwHOAuJVkc4Bg4S7';
const STATUS_FIELD_ID = 'PVTSSF_lAHOAuJVkc4Bg4S7zhf2L34';
const DEPENDENCY_CHECK_NAME = 'check-dependencies';
const STATUS_OPTION = {
  IN_PROGRESS: '47fc9ee4',
  REVIEW: '432b1b61',
  APPROVED: 'c6f50cd1',
  DONE: '98236657',
  BLOCKED: 'a441f58e',
};

function latestCheck(checkRuns) {
  const completed = checkRuns.filter((run) => run.status === 'completed');
  return completed.reduce((latest, run) => (!latest || run.started_at > latest.started_at ? run : latest), null);
}

function isBlocked(pr) {
  return pr.dependencyCheck === 'failure' || pr.reviewDecision === 'CHANGES_REQUESTED';
}

function resolveStatus(pr) {
  if (pr.state !== 'OPEN') {
    return STATUS_OPTION.DONE;
  }
  if (pr.isDraft) {
    return STATUS_OPTION.IN_PROGRESS;
  }
  if (isBlocked(pr)) {
    return STATUS_OPTION.BLOCKED;
  }
  return pr.reviewDecision === 'APPROVED' ? STATUS_OPTION.APPROVED : STATUS_OPTION.REVIEW;
}

async function fetchPr(github, { owner, repo, number }) {
  const { repository } = await github.graphql(
    `query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $number) { id number state isDraft reviewDecision headRefOid labels(first: 50) { nodes { name } } }
      }
    }`,
    { owner, repo, number }
  );
  return repository.pullRequest;
}

async function setStatus(github, contentId, optionId) {
  const addResult = await github.graphql(
    `mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: { projectId: $projectId, contentId: $contentId }) {
        item { id }
      }
    }`,
    { projectId: PROJECT_ID, contentId }
  );
  const itemId = addResult.addProjectV2ItemById.item.id;

  await github.graphql(
    `mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
      updateProjectV2ItemFieldValue(
        input: {
          projectId: $projectId
          itemId: $itemId
          fieldId: $fieldId
          value: { singleSelectOptionId: $optionId }
        }
      ) {
        projectV2Item { id }
      }
    }`,
    { projectId: PROJECT_ID, itemId, fieldId: STATUS_FIELD_ID, optionId }
  );
}

async function findDependencyCheck(github, core, { owner, repo }, sha) {
  const { data } = await github.rest.checks.listForRef({ owner, repo, ref: sha, check_name: DEPENDENCY_CHECK_NAME });
  const check = latestCheck(data.check_runs);
  if (check?.conclusion === 'failure') {
    const { data: annotations } = await github.rest.checks.listAnnotations({ owner, repo, check_run_id: check.id });
    const blockers = annotations.filter((annotation) => annotation.annotation_level === 'failure');
    core.info(`Blocked by: ${blockers.map((annotation) => annotation.message).join(', ')} (${check.html_url})`);
  }
  return check?.conclusion ?? null;
}

async function findPullRequestNumber(github, { payload, repo }) {
  if (payload.pull_request) {
    return payload.pull_request.number;
  }
  const openPrs = await github.paginate(github.rest.pulls.list, { ...repo, state: 'open', per_page: 100 });
  return openPrs.find((pr) => pr.head.sha === payload.workflow_run.head_sha)?.number;
}

async function findPr(github, context, core) {
  const number = await findPullRequestNumber(github, context);
  if (!number) {
    core.info(`No open PR for ${context.payload.workflow_run.head_sha}; skipping.`);
    return null;
  }
  return fetchPr(github, { ...context.repo, number });
}

async function sync({ github, context, core }) {
  const pr = await findPr(github, context, core);
  if (!pr) {
    return;
  }
  const dependencyCheck = await findDependencyCheck(github, core, context.repo, pr.headRefOid);
  await setStatus(github, pr.id, resolveStatus({ ...pr, dependencyCheck }));
}

module.exports = { findDependencyCheck, findPr, isBlocked, latestCheck, resolveStatus, sync };
