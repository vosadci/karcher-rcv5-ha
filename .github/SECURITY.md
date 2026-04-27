# Security policy

## Supported versions

Only the latest tagged release receives security fixes. Use `main` at
your own risk.

| Version | Supported |
|---|---|
| Latest tag | ✓ |
| `main` | Best-effort |
| Everything else | ✗ |

## Reporting a vulnerability

**Do not open a public issue or pull request for a security problem.**

Report vulnerabilities privately via one of the following:

- GitHub's [private vulnerability reporting](https://github.com/vosadci/karcher-rcv5-ha/security/advisories/new)
  on this repository.
- Email the maintainers listed in `.github/CODEOWNERS` with subject
  `[karcher_home_robots] security report`.

Include, at minimum:

- Affected version or commit SHA.
- A reproduction — exact steps, config, and expected vs. actual behaviour.
- Impact assessment: what an attacker can achieve (RCE, credential theft,
  device takeover, data disclosure, denial of service).
- Whether the issue requires physical access, network position on the
  user's LAN, or only an internet-exposed Home Assistant.

## What qualifies

In scope:

- Any credential, token, or serial-number leak in logs, diagnostics, or
  on-disk state.
- TLS-related weaknesses (missing hostname check, CA fallback,
  certificate confusion).
- Wire-message handling that enables spoofed commands, replay, or
  unvalidated deserialisation.
- Any bypass of the secrets policy in `05-security-threat-model.md` §3.
- Dependency vulnerabilities with an exploitable path via this
  integration.

Out of scope (unless a novel exploitation path is demonstrated):

- The 3iRobotix cloud itself or the device firmware.
- Physical attacks on the robot (UART, eMMC, enclosure).
- General Home Assistant core issues — report those to
  [Home Assistant](https://github.com/home-assistant/core/security/policy).
- Theoretical weaknesses in the APK-extracted mutual-TLS asset, which
  is treated as public knowledge in the threat model.

## Disclosure

Initial response target: 5 working days. A fix is targeted within 30
days for critical issues, 90 days for lower severities, or with an
explicit coordinated disclosure timeline agreed with the reporter.

Credit is given in `CHANGELOG.md` under the corresponding release's
**Security** subsection unless the reporter prefers to remain anonymous.
