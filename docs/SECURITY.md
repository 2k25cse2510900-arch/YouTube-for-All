# Security Policy

## Supported Versions

Security updates and bug fixes are applied to the active development branch:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

---

## Reporting a Vulnerability

The project maintainers take security and data privacy seriously. If you discover a security vulnerability or potential threat within this codebase:

1. **Do Not File Public Issues**:
   Please do not disclose potential vulnerabilities publicly through GitHub Issues, pull requests, or public discussions.

2. **Submit via Private Vulnerability Reporting**:
   Use GitHub's built-in [Private Vulnerability Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-communicating-vulnerabilities/privately-reporting-a-security-vulnerability) feature on the GitHub repository page if available.

3. **Contact Maintainers**:
   Alternatively, contact the repository maintainer through their GitHub profile (`2k25cse2510900-arch`) with detailed steps to reproduce the issue, potential impact, and suggested remediations.

All reports will be acknowledged, reviewed, and addressed promptly.

---

## Secret and Credential Management

`YouTube-for-All` interacts with external AI providers and cloud services that require authentication credentials. To protect user security, adhere to the following operational standards:

* **Local Environment Isolation**:
  API keys (such as `GEMINI_API_KEY`, `SARVAM_API_KEY`, and `CLOUDFLARE_API_TOKEN`) and OAuth credentials (`client_secret.json`, `token.json`) must reside exclusively in local, uncommitted files (`.env`, `secrets/`).

* **Git Ignore Verification**:
  Ensure that your `.gitignore` file includes all credential patterns, local environment configurations, and generated token files before running any Git commands:
  ```gitignore
  .env
  *.env
  secrets/
  token.json
  client_secret.json
  ```

* **Immediate Secret Revocation**:
  If any API key, access token, or OAuth secret is inadvertently committed or exposed, revoke and regenerate that credential immediately in the corresponding service provider's administrative dashboard (e.g., Google Cloud Console, Cloudflare Dashboard, or Sarvam AI Console), and remove the affected revision from your local Git history.
