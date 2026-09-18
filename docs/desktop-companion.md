# Desktop companion boundary

`logged-in` mode is optional and deliberately separate from the plugin
container. A host-side companion connects only to a Chrome instance for which
the owner has already granted remote-debugging consent through Browser Harness.
The plugin never scans for browser profiles, enables remote debugging, copies
cookies or receives a raw CDP endpoint.

The companion creates one background target per requested session and records
only that target ID. It cannot enumerate or attach to pre-existing tabs. It
listens only on `127.0.0.1` with a private token file (mode `0600`). The plugin
connects through Docker Desktop's host gateway using the configured token; it
cannot reach the companion without that explicit binding.

To enable it, the installation owner must:

1. Start Browser Harness against the owner-selected Chrome instance.
2. Initialize and run `src/companion.py` on loopback with a private token file.
3. Configure `desktopCompanionToken` and a non-empty `loggedInOrigins` list
   together through `ez fast-browser configure`.

Each allowed entry must be a bare origin such as `https://github.com`; paths,
queries, subdomain wildcards and implicit redirects are rejected. The companion
checks the allowlist both before navigation and after every observed page change.
It closes its own tab when the session closes. Login, MFA, CAPTCHA, browser
permission, upload, download, popup, iframe and unexpected-origin flows fail
closed.
