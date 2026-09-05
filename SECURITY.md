# Security policy

## Reporting sensitive information

Do **not** open a public issue for exposed credentials, private conversation/session links, personal data, or other sensitive material.

If GitHub's private vulnerability-reporting flow is available for this repository, use **Security → Report a vulnerability**. Otherwise contact the repository owner privately through the owner's GitHub profile and include only the minimum information needed to identify the affected path or commit.

If a credential has been committed, treat it as compromised and rotate/revoke it even if the file is later deleted. Removing a secret from the current branch does not remove it from Git history, forks, caches, or clones.

## Scope

Security reports should cover vulnerabilities in the harness, CI configuration, dependency handling, credential handling, or accidental disclosure of sensitive data.

Model-behavior findings produced by the harness are research results rather than software security vulnerabilities; use a normal issue or pull request for reproducibility or methodology questions that do not contain sensitive information.

## Supported version

The default branch is the supported development line. The `v1/` directory is retained for research provenance and is not maintained as a supported release.
