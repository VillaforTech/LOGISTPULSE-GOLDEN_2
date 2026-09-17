# GitHub distribution model

## Reusable project foundation

`LOGISTPULSE-GOLDEN` began as a validated template and now acts as the reusable foundation for the product family. Teams create repositories from Git history rather than exchanging ZIP archives, preserving ownership and review evidence.

Recommended product repositories created with **Use this template**:

- `LOGISTPULSE-INVENTORY`
- `LOGISTPULSE-DISTRIBUTION`
- `LOGISTPULSE-OPERATIONS`
- `LOGISTPULSE-FULFILLMENT`

Each product cell pairs product/domain engineering with platform/reliability engineering.

## Branch model

- `main` — stable integration branch.
- `architecture/*` — C4, ADR, domain and contract decisions.
- `feature/*` — frontend/backend product changes.
- `devops/*` — CI/CD, Docker, observability and platform changes.
- `fix/*` — corrective work.

All changes should enter `main` through Pull Requests and CI.
