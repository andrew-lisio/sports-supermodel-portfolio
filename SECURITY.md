# Security policy

## Supported version

Security and privacy fixes are accepted for the current V2.3.2 line and active development branches.

## Reporting

Do not open a public issue for vulnerabilities, exposed credentials, private sportsbook information, personal data, or a snapshot containing sensitive account details. Contact the repository owner privately through GitHub's security-reporting feature once enabled.

## Sensitive data

The project should never contain:

- usernames or passwords
- API secrets
- session or authentication cookies
- payment information
- sportsbook account identifiers
- account balances
- precise personal location
- private URLs containing access tokens
- unredacted private correspondence

The model needs only structured game identity and two-way odds. It does not need sportsbook authentication or personal information.

## Local browser interface

The Streamlit interface is a local development application. Do not expose it directly to the public internet without a production security design covering authentication, authorization, secrets, network controls, rate limiting, logging, dependency updates, privacy, and incident response.

## Accidental exposure

If sensitive information is committed:

1. Revoke or rotate the affected credential immediately.
2. Remove the material from Git history, not only the latest commit.
3. Review forks, release assets, CI logs, and caches.
4. Notify affected parties when legally or contractually required.
