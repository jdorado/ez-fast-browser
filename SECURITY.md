# Security model

`fast-browser` runs a bounded Jev policy only over visible DOM elements it has
observed. Model output is validated against that action table; it never becomes a
selector, coordinate, JavaScript fragment, shell command or arbitrary URL.

The TypeSafe request contains structured visible page state. It does not include
cookies, storage, screenshots, hidden/password/file fields or raw CDP access.
Because visible account content can still be sensitive, logged-in mode requires
explicit owner setup, Chrome remote-debugging consent and origin approval. Its
separate companion accepts only token-authenticated, bounded `start`, `observe`,
freshness, action and close operations for tabs it created; it cannot enumerate
or attach to existing tabs.

Configuration is written only to the plugin's private `/state` volume with mode
0600. Receipts contain action labels, page fingerprints and final readback
metadata; typed text and full page dumps are omitted. Browser profiles are
ephemeral and removed when the session closes.

The desktop companion exposes only an authenticated loopback operation protocol;
it does not mount a Chrome profile, Browser Harness home, browser history or raw
CDP to the plugin container. Login, MFA, CAPTCHA, browser-permission,
file-transfer and pop-up workflows fail closed.

Browser mutations are logged before post-action observation and are never retried
automatically. High-impact final actions pause for the native Ez agent's fresh
owner review. An uncertain result remains uncertain until page readback resolves
it.
