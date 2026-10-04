async function findStickyComment(github, context, marker) {
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: context.payload.pull_request.number,
    per_page: 100,
  });
  return comments.find((c) => c.body.includes(marker));
}

async function upsertStickyComment(github, context, marker, body, existing) {
  if (existing) {
    await github.rest.issues.updateComment({
      owner: context.repo.owner,
      repo: context.repo.repo,
      comment_id: existing.id,
      body: `${marker}\n${body}`,
    });
  } else {
    await github.rest.issues.createComment({
      owner: context.repo.owner,
      repo: context.repo.repo,
      issue_number: context.payload.pull_request.number,
      body: `${marker}\n${body}`,
    });
  }
}

module.exports = { findStickyComment, upsertStickyComment };
