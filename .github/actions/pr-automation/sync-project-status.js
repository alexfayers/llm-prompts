// Re-derive these IDs with: gh project field-list 4 --owner alexfayers --format json
const PROJECT_ID = 'PVT_kwHOAuJVkc4Bg4S7';
const STATUS_FIELD_ID = 'PVTSSF_lAHOAuJVkc4Bg4S7zhf2L34';
const STATUS_OPTION = {
  IN_PROGRESS: '47fc9ee4',
  REVIEW: '432b1b61',
  APPROVED: 'c6f50cd1',
  DONE: '98236657',
};

function isBlocked(pr) {
  return pr.reviewDecision === 'CHANGES_REQUESTED';
}

function isApproved(pr) {
  const states = (pr.latestOpinionatedReviews?.nodes ?? []).map(({ state }) => state);
  return states.includes('APPROVED') && !states.includes('CHANGES_REQUESTED');
}

function resolveStatus(pr) {
  if (pr.state !== 'OPEN') {
    return STATUS_OPTION.DONE;
  }
  if (pr.isDraft) {
    return STATUS_OPTION.IN_PROGRESS;
  }
  return isApproved(pr) ? STATUS_OPTION.APPROVED : STATUS_OPTION.REVIEW;
}

async function fetchPr(github, { owner, repo, number }) {
  const { repository } = await github.graphql(
    `query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $number) { id number state isDraft reviewDecision latestOpinionatedReviews(first: 50) { nodes { state } } headRefOid labels(first: 50) { nodes { name } } }
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

async function findPullRequest(github, { payload, repo }) {
  if (payload.pull_request) {
    return payload.pull_request;
  }
  const openPrs = await github.paginate(github.rest.pulls.list, { ...repo, state: 'open', per_page: 100 });
  const { head_sha: sha, head_branch: ref, head_repository: repository } = payload.workflow_run;
  const matches = openPrs.filter((pr) => pr.head.sha === sha && pr.head.ref === ref && pr.head.repo?.full_name === repository?.full_name);
  return matches.length === 1 ? matches[0] : undefined;
}

async function findPr(github, context, core) {
  const number = (await findPullRequest(github, context))?.number;
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
  await setStatus(github, pr.id, resolveStatus(pr));
}

module.exports = { findPullRequest, findPr, fetchPr, isBlocked, resolveStatus, sync };
