// Re-derive these IDs with: gh project field-list 4 --owner alexfayers --format json
const PROJECT_ID = 'PVT_kwHOAuJVkc4Bg4S7';
const STATUS_FIELD_ID = 'PVTSSF_lAHOAuJVkc4Bg4S7zhf2L34';
const STATUS_OPTION = {
  IN_PROGRESS: '47fc9ee4',
  REVIEW: '432b1b61',
  APPROVED: 'c6f50cd1',
  DONE: '98236657',
};

function resolveStatus(eventName, payload) {
  if (eventName === 'pull_request_target') {
    const pr = payload.pull_request;
    switch (payload.action) {
      case 'opened':
      case 'reopened':
        return pr.draft ? STATUS_OPTION.IN_PROGRESS : STATUS_OPTION.REVIEW;
      case 'converted_to_draft':
        return STATUS_OPTION.IN_PROGRESS;
      case 'ready_for_review':
        return STATUS_OPTION.REVIEW;
      case 'closed':
        return STATUS_OPTION.DONE;
      default:
        return null;
    }
  }

  if (eventName === 'pull_request_review' && payload.action === 'submitted') {
    switch (payload.review.state) {
      case 'approved':
        return STATUS_OPTION.APPROVED;
      case 'changes_requested':
        return STATUS_OPTION.REVIEW;
      default:
        return null;
    }
  }

  return null;
}

async function sync({ github, context, core }) {
  const optionId = resolveStatus(context.eventName, context.payload);
  if (!optionId) {
    core.info(`No status mapping for ${context.eventName}/${context.payload.action}; skipping.`);
    return;
  }

  const pr = context.payload.pull_request;
  const addResult = await github.graphql(
    `mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: { projectId: $projectId, contentId: $contentId }) {
        item { id }
      }
    }`,
    { projectId: PROJECT_ID, contentId: pr.node_id }
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

module.exports = { resolveStatus, sync };
