# Issue rules

Used by `{{SKILL_DIR}}/report-issue.md` and `{{SKILL_DIR}}/request.md`, and by anything else that files or works an issue.

## Content

- An issue MUST hold everything anyone needs to pick it up and finish it, without asking. A design-needed issue MUST state the core idea so someone can design it.
- MUST keep it short and leave out the obvious.
- MUST end with `## Success criteria`: checkable bullets that say when it is done.
- MUST link related issues as `#<n>` in the body.
- A pure idea with no research MUST get the `idea` label. Where the repo lacks it: `gh label create idea --color FBCA04 -d "A pure idea, not researched yet" -R <owner/name>`.

## Links

Numeric id: `gh api repos/<owner>/<repo>/issues/<n> --jq .id`. After filing:

- Blocked by another issue: MUST set it with `gh api -X POST repos/<owner>/<repo>/issues/<n>/dependencies/blocked_by -F issue_id=<blocking id>`.
- Larger work: MUST file a parent issue and each part as a sub-issue with `gh api -X POST repos/<owner>/<repo>/issues/<parent>/sub_issues -F sub_issue_id=<child id>`.

## Status

- Status ids: `gh api graphql -f query='{repository(owner:"<owner>",name:"<repo>"){planningStatuses(first:20){nodes{id name}}}}'`.
- Issue node id: `gh api repos/<owner>/<repo>/issues/<n> --jq .node_id`.
- Set it: `gh api graphql -f query='mutation($i:ID!,$s:ID!){setIssueStatus(input:{issueId:$i,statusId:$s}){issue{status{name}}}}' -f i=<node id> -f s=<status id>`.
- The mutation cannot clear a status, so MUST set a real one.
- MUST set `Backlog` on a new idea or parked work, and `Todo` on an issue picked for now.
- MUST set `In progress` when work on it starts, `Done` when it closes as completed, and `Not planned` when it closes as dropped.
