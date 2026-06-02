---
description: Read actual system state before proposing infrastructure changes
copilot_apply_to: '**'
---

# Verify Before Acting

Before proposing any change to a pipeline, CDK stack, deployment configuration, account structure, or task/ticket workflow, you MUST first read the current state of that system (pipeline definition, CDK code, account config, ticket status). Never propose changes based on inferred or assumed structure. When the user provides a URL to a pipeline or system, read it before summarizing or drawing conclusions.

This applies to all infrastructure-adjacent systems: pipelines, CloudFormation stacks, service accounts, deployment stages, version sets, and CI/CD configurations. The cost of reading first is low; the cost of acting on a wrong assumption is high.
