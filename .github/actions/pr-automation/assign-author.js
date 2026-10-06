function authorToAssign(pr) {
  if (pr.user.type === 'Bot') {
    return null;
  }
  if (pr.assignees.some((a) => a.login === pr.user.login)) {
    return null;
  }
  return pr.user.login;
}

async function assign({ github, context, core }) {
  const login = authorToAssign(context.payload.pull_request);
  if (!login) {
    return;
  }

  try {
    await github.rest.issues.addAssignees({
      owner: context.repo.owner,
      repo: context.repo.repo,
      issue_number: context.payload.pull_request.number,
      assignees: [login],
    });
  } catch (error) {
    core.warning(`Failed to assign "${login}": ${error.message}`);
  }
}

module.exports = { authorToAssign, assign };
