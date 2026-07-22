# Security policy

## Supported version

Security and privacy fixes are accepted for the current V2.3.1 line and active development branches.

## Reporting

Do not open a public issue for vulnerabilities, exposed credentials, private sportsbook information, personal data, or a snapshot containing sensitive account details. Contact the repository owner privately through GitHub's security-reporting feature once enabled.

## Sensitive data

The project should never contain:

- usernames or passwords
- API secrets
- session cookies
- payment information
- sportsbook account identifiers
- precise personal location
- unredacted private correspondence

If sensitive information is committed, rotate affected credentials immediately and remove the material from Git history before publishing.
