# Security policy

LogistPulse is a portfolio and development environment built with synthetic orders, stores and telemetry. Its local credentials are not suitable for a public deployment.

- Never commit real API keys, passwords, certificates, personal data or production connection strings.
- Report a suspected vulnerability privately to the repository owner instead of opening an issue with exploit details.
- Keep PostgreSQL, MongoDB, MQTT and Redpanda ports private behind the product edge.
- Store registry and deployment credentials in GitHub Actions Secrets.
- Do not place real fleet, customer, employee or order data in fixtures or CI artifacts.
- Before a public deployment, add managed secrets, authentication and authorization, rate limits, encrypted transport, SAST/SCA, secret and container scanning, SBOM generation and policy-as-code.

Security improvements are welcome through focused pull requests with a threat, mitigation and verification method.
