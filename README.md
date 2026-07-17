# To-Do App — Infrastructure (CloudFormation)

All AWS infrastructure for the To-Do app: multi-AZ VPC, ECS Fargate, RDS PostgreSQL + RDS
Proxy, ElastiCache Redis, ALB, CodePipeline/CodeDeploy blue/green pipeline, EventBridge, and
the GitHub OIDC trust used by the [app repo](../todo-app-code)'s GitHub Actions workflow.

No NAT Gateway is used — private subnets reach ECR, CloudWatch Logs, Secrets Manager, and S3
purely through VPC endpoints, which is both cheaper and keeps ECS tasks fully private.

Deployed via **CloudFormation Git sync**, not a CLI script — GitSync only tracks one root
template per stack, so this repo uses the standard nested-stack pattern: `root-stack.yaml` at
the repo root composes nine child stacks in `stacks/`, each nested stack's `TemplateURL`
pointing at an S3 bucket that mirrors this repo's `stacks/` folder.

## Layout

| Path | Purpose |
|---|---|
| `root-stack.yaml` | The template GitSync actually tracks — wires all child stacks together |
| `deployment-file.yaml` | GitSync's stack deployment file: parameters, capabilities, tags for `root-stack.yaml` |
| `stacks/network.yaml` | VPC, public subnets (ALB), three private subnet tiers (ECS / data / cache), VPC endpoints |
| `stacks/security.yaml` | Six security groups, chained ALB → ECS → RDS Proxy → RDS, and ECS → Redis |
| `stacks/database.yaml` | RDS PostgreSQL (`db.t3`, Multi-AZ), Secrets Manager credentials, RDS Proxy |
| `stacks/cache.yaml` | ElastiCache Redis replication group (primary + replica) |
| `stacks/ecr.yaml` | ECR repository for the app image |
| `stacks/iam.yaml` | GitHub Actions role (existing OIDC provider), ECS execution/task roles |
| `stacks/compute.yaml` | ECS cluster, ALB (prod + test listener), blue/green target groups, task definition, service |
| `stacks/autoscaling.yaml` | Application Auto Scaling: min 1 / desired 1 / max 4, CPU target tracking |
| `stacks/cicd.yaml` | Artifact bucket, CodeDeploy blue/green, CodePipeline (ECR + S3 sources), EventBridge trigger |
| `.githooks/pre-push` | Syncs `stacks/` to S3 before every push (see below) |

## Why child templates need a separate sync step

GitSync watches `root-stack.yaml` for changes and re-deploys the stack when it changes — but
`root-stack.yaml`'s nested stacks reference their children via S3 `TemplateURL`s, not local
paths, and GitSync has no idea the `stacks/` folder exists. A **git pre-push hook**
(`.githooks/pre-push`) syncs `stacks/` to an S3 bucket every time you push, so the
`TemplateURL`s always resolve to the version of each child template you just pushed.

Run once after cloning:

```bash
./setup.sh   # git config core.hooksPath .githooks
```

This requires your own AWS CLI credentials locally (not OIDC — it's a local git hook, not a
CI/CD workflow) with `s3:PutObject`/`s3:DeleteObject` on the templates bucket.

## One-time prerequisites (outside CloudFormation)

These exist before `root-stack.yaml` can be created, since the stack's own creation depends on
them:

1. **S3 templates bucket** — `todo-app-infra-templates-eu-central-1-124355645722`. Create it
   and run `./setup.sh`, then push once to populate `stacks/` via the pre-push hook.
2. **A real placeholder image in ECR** for the initial task definition (`AppImageUri` in
   `deployment-file.yaml`) — the ECS service must reach a healthy steady state during stack
   creation, before the app repo's pipeline has ever run. This reuses the shared bootstrap
   image already in this account (`ecs-lab-bootstrap:latest`); point it at any image that
   answers `200` on `/actuator/health` on port 8080 if that repo isn't available.
3. **GitHub OIDC provider** — this account already has one
   (`arn:aws:iam::124355645722:oidc-provider/token.actions.githubusercontent.com`), reused via
   the `GitHubOidcProviderArn` parameter rather than created fresh (an account can only have one
   OIDC provider per URL).

## Deploying via CloudFormation Git sync

In the CloudFormation console: **Git sync** → connect this repo via CodeConnections → create a
stack with **Sync from Git**, template path `root-stack.yaml`, and either point it at
`deployment-file.yaml` or let the console generate one from the same parameters. GitSync opens
a pull request for the initial stack creation and for every subsequent template change — merge
it to apply.

**Costs money as soon as it's applied**: RDS (Multi-AZ `db.t3.micro`), RDS Proxy, ElastiCache
(2 nodes), the ALB, 4 VPC interface endpoints, and CodePipeline all bill hourly.

## Wiring up the app repo

The `todo-app-code` GitHub Actions workflow assumes `todo-app-github-actions` directly (see
`stacks/iam.yaml`) — no GitHub repo variables to copy over. It re-derives the task definition
live via `aws ecs describe-task-definition` on every deploy (only patching the image field), so
the RDS Proxy endpoint, DB secret ARN, and Redis host/port baked in by `stacks/compute.yaml`
never need to be duplicated into the app repo.

## Tagging

`deployment-file.yaml` sets `tags: {Project: todo-app, ManagedBy: CloudFormation-GitSync}` at
the stack level — CloudFormation propagates these to every resource in the stack that supports
tagging, so this covers the whole stack without per-resource `Tags:` blocks (most resources
also carry an explicit `Project` tag for clarity).

## Architecture diagram

See [`diagrams/architecture.py`](diagrams/architecture.py) (diagram-as-code, using the
`diagrams` Python library) and its rendered [`diagrams/architecture.png`](diagrams/architecture.png).
