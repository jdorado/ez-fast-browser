# Fast Browser contributor notes

Read `README.md`, `SECURITY.md`, and `skills/fast-browser/SKILL.md` before
changing behavior. Keep Jev bounded to observed DOM elements and supported
operations; do not introduce generated selectors, JavaScript, browser-profile
copies, autonomous login handling, or mutation retries.

The native Ez engine owns goal selection, mode selection, authority and review.
The plugin owns browser transport, validation, private configuration and
redacted receipts. Tests must not contact TypeSafe, a text model or a real site.

Checks: `npm run verify`, `npm pack --dry-run --ignore-scripts`, and the
standard installed-plugin smoke path.
