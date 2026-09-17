# Contributing to LogistPulse

LogistPulse is a shared team portfolio project. Each contribution should improve a visible product behavior, an operational property or the confidence of the release process. GitHub issues define the work; pull requests contain the implementation, tests and observed evidence.

## Active workstreams

| Issue | Owner | Product outcome |
| --- | --- | --- |
| [#1](https://github.com/VillaforTech/logistpulse/issues/1) | `@nikotov` | Reliable fulfillment facts, event contracts and transactional outbox |
| [#2](https://github.com/VillaforTech/logistpulse/issues/2) | `@DanielSalazar0710` | Continuous analytics, deduplication, persistent state and timers |
| [#3](https://github.com/VillaforTech/logistpulse/issues/3) | `@oandretty010` | Grafana Live panels, business alerts and reconnect behavior |
| [#4](https://github.com/VillaforTech/logistpulse/issues/4) | `@VillaforTech` | Redpanda, Compose integration, CI and required release gate |
| [#5](https://github.com/VillaforTech/logistpulse/issues/5) | `@Dmt-155lbs` | End-to-end behavior, resilience, render latency and evidence |

Issue ownership coordinates the work; portfolio credit follows reviewed and merged commits. Agree on the event contract from #1 before integrating #2 and #3. The integration owner connects the components, and #5 verifies the complete story.

## Branch and pull-request workflow

Start from an updated `main` and create one focused branch per issue:

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/2-business-analytics

# Implement and validate the change.
git diff --check
git add path/to/file
git commit -m "feat(analytics): persist fulfillment projections"
git push -u origin feat/2-business-analytics
```

Use `feat/`, `fix/`, `docs/` or `chore/` plus the issue number. Do not modify another contributor's branch without coordinating first.

Open the PR against `main`, complete the template and link the issue. Keep it in **Draft** while incomplete. Use `Closes #2` only when the PR satisfies the whole issue; use `Related to #2` for a partial delivery.

## Definition of done

A contribution is ready for review when:

- the product behavior and reason for the change are clear;
- the branch is current with `main`;
- relevant unit, integration, business and recovery checks pass;
- event contracts and data ownership remain compatible;
- observed results and commands are recorded in the PR;
- no secrets, real customer data or generated private configuration are committed;
- documentation describes the final behavior rather than the implementation plan.

For event and KPI work, cover duplicates, replay, restart, no-traffic deadlines, recovery and freshness as applicable. A documentation-only PR should say that application tests do not apply and list its documentation checks.

## Merge protection

`main` requires:

- a pull request and one current approval from another collaborator with write access;
- resolved review conversations;
- an up-to-date branch;
- green `architecture-contract`, `integration`, and `Release gate` checks;
- squash merge and linear history.

New commits dismiss earlier approvals. Rules also apply to administrators; direct pushes, force pushes and deletion of `main` are blocked. Do not weaken a check to make a failing branch green. Authors cannot approve their own PRs, including PRs created through an authenticated automation tool.

## Local validation

```bash
docker compose config --quiet
docker compose -f observability/compose.yaml config --quiet
docker compose up --build -d --wait
bash scripts/smoke.sh
```

The integration contract in [TEAM-INTEGRATION](docs/TEAM-INTEGRATION.md) defines the topic, analytics interface and acceptance hook. Once `scripts/acceptance/` exists, skipped resilience checks and API-only latency evidence must fail the pipeline. The deliberate broken business revision belongs in a PR demonstration and must never be merged into `main`.

## Working from project contracts

Start with the [architecture and data ownership](docs/architecture/DATA-OWNERSHIP.md) and [integration contract](docs/TEAM-INTEGRATION.md). Keep implementation, tests and documentation aligned in the same pull request. Preserve attribution when adapting existing code, and support completion claims with tests and evidence produced in this repository.

## Security and project context

Never commit `.env`, access tokens, institutional credentials or real customer, fleet or order data. Review migrations, event contracts and ownership changes explicitly.

The team also uses this repository for a graded software-engineering case study. Those deadlines and evidence requirements remain valid, while product documentation, commit history and contribution records are maintained for long-term portfolio use.
