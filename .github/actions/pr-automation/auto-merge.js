const CONTRIBUTE_BRANCH = /^[^/]+\/contribute\//;

const ENABLE_AUTO_MERGE = `mutation($id: ID!) {
  enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: SQUASH}) {
    clientMutationId
  }
}`;

function isContributeBranch(ref) {
  return CONTRIBUTE_BRANCH.test(ref);
}

async function enable({ github, context, core }) {
  const pr = context.payload.pull_request;
  if (!isContributeBranch(pr.head.ref)) {
    return;
  }

  try {
    await github.graphql(ENABLE_AUTO_MERGE, { id: pr.node_id });
  } catch (error) {
    core.warning(`Failed to enable auto-merge: ${error.message}`);
  }
}

module.exports = { isContributeBranch, enable };
