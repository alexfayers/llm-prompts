const LIST_OPEN_PRS = `query($owner: String!, $repo: String!, $base: String!) {
  repository(owner: $owner, name: $repo) {
    pullRequests(states: OPEN, baseRefName: $base, first: 100) {
      nodes { id number headRefOid isDraft isCrossRepository mergeable autoMergeRequest { enabledAt } }
    }
  }
}`;

const REBASE_BRANCH = `mutation($id: ID!, $head: GitObjectID!) {
  updatePullRequestBranch(input: {pullRequestId: $id, expectedHeadOid: $head, updateMethod: REBASE}) {
    clientMutationId
  }
}`;

function isRebaseCandidate(pr) {
  return (
    pr.autoMergeRequest !== null &&
    !pr.isDraft &&
    !pr.isCrossRepository &&
    pr.mergeable !== 'CONFLICTING'
  );
}

async function rebase({ github, context, core }) {
  const base = context.ref.replace('refs/heads/', '');
  const { repository } = await github.graphql(LIST_OPEN_PRS, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    base,
  });

  for (const pr of repository.pullRequests.nodes.filter(isRebaseCandidate)) {
    try {
      await github.graphql(REBASE_BRANCH, { id: pr.id, head: pr.headRefOid });
    } catch (error) {
      core.warning(`Failed to rebase #${pr.number}: ${error.message}`);
    }
  }
}

module.exports = { isRebaseCandidate, rebase };
