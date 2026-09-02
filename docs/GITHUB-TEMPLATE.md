# GitHub distribution model

## Golden repository

The instructor publishes `LOGISTPULSE-GOLDEN` as the validated Template Repository. Students do not upload ZIP files.

Recommended product repositories created with **Use this template**:

- `LOGISTPULSE-INVENTORY`
- `LOGISTPULSE-DISTRIBUTION`
- `LOGISTPULSE-OPERATIONS`
- `LOGISTPULSE-FULFILLMENT`

Each product cell pairs a Design of Systems team (frontend/backend) with a Software Development team acting as DevOps/Platform Engineering.

## Branch model

- `main` — stable integration branch.
- `architecture/*` — C4, ADR, domain and contract decisions.
- `feature/*` — frontend/backend product changes.
- `devops/*` — CI/CD, Docker, observability and platform changes.
- `fix/*` — corrective work.

All changes should enter `main` through Pull Requests and CI.
