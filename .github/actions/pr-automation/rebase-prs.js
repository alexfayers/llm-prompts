const { AUTO_REBASE_LABEL, isRenovate } = require('./label-pr.js');
const { findPullRequest } = require('./sync-project-status.js');

const LIST_OPEN_PRS = `query($owner: String!, $repo: String!, $base: String!) {
  repository(owner: $owner, name: $repo) {
    pullRequests(states: OPEN, baseRefName: $base, first: 100) {
      nodes { id number headRefOid mergeable author { login } labels(first: 50) { nodes { name } } }
    }
  }
}`;

const updateBranch = (method) => `mutation($id: ID!, $head: GitObjectID!) {
  updatePullRequestBranch(input: {pullRequestId: $id, expectedHeadOid: $head, updateMethod: ${method}}) {
    clientMutationId
  }
}`;

const REBASE_BRANCH = updateBranch('REBASE');
const MERGE_BRANCH = updateBranch('MERGE');

const GET_PR = `query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) { id number baseRefName headRefOid mergeable author { login } labels(first: 50) { nodes { name } } }
  }
}`;

function isRebaseCandidate(pr) {
  return !isRenovate(pr.author?.login) && pr.mergeable !== 'CONFLICTING' && pr.labels.nodes.some(({ name }) => name === AUTO_REBASE_LABEL.name);
}

async function rebase({ github, context, core }) {
  const base = context.ref.replace('refs/heads/', '');
  const { repository } = await github.graphql(LIST_OPEN_PRS, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    base,
  });

  for (const pr of repository.pullRequests.nodes.filter(isRebaseCandidate)) {
    await rebaseBranch(github, core, pr);
  }
}

async function rebaseBranch(github, core, pr) {
  const variables = { id: pr.id, head: pr.headRefOid };
  try {
    await github.graphql(REBASE_BRANCH, variables);
    return;
  } catch (error) {
    core.info(`Rebase of #${pr.number} failed, updating by merge: ${error.message}`);
  }
  try {
    await github.graphql(MERGE_BRANCH, variables);
  } catch (error) {
    core.warning(`Failed to update #${pr.number}: ${error.message}`);
  }
}

async function rebaseLabelled({ github, context, core }) {
  const found = await findPullRequest(github, context);
  if (!found) {
    return;
  }
  const { repository } = await github.graphql(GET_PR, { ...context.repo, number: found.number });
  const pr = repository.pullRequest;
  if (!isRebaseCandidate(pr)) {
    return;
  }
  const { data: { behind_by: behindBy } } = await github.rest.repos.compareCommitsWithBasehead({
    ...context.repo,
    basehead: `${pr.baseRefName}...${pr.headRefOid}`,
  });
  if (behindBy > 0) {
    await rebaseBranch(github, core, pr);
  }
}

module.exports = { isRebaseCandidate, rebase, rebaseLabelled };
