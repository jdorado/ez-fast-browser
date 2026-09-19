# Ez Fast Browser

`@jc_stack/ez-fast-browser` gives an Ez agent a small, bounded Jev Ultrafast
browser capability. It opens an ephemeral Chromium session, builds a current
indexed action table from visible controls, asks TypeSafe to choose an operation
and compatible target, and validates the target again before acting.

It is an [Ez](https://github.com/jdorado/ez) plugin, not an npm package or a
standalone browser agent. The native Ez engine chooses the task and authority;
this package owns only the constrained browser transport, configuration and
redacted receipt.

It is not a general browser shell. It cannot execute model-generated selectors
or JavaScript, copy cookies, enter passwords, solve CAPTCHAs, upload/download
files, follow pop-up/iframe/canvas workflows or retry browser mutations.

## Current beta scope

- `isolated` is implemented: each session has fresh Chromium profile state.
- `logged-in` uses a separately started, token-authenticated loopback companion
  after Chrome remote-debugging consent and an explicit origin allowlist. It
  creates and closes only its own background tab; it never enumerates existing
  tabs or copies browser data.
- `run` returns an active session ID; `continue`, `snapshot`, `execute` and
  `close` support bounded follow-up work.
- Targets whose labels imply a high-impact final action pause for owner review.

## Install and configure

Inspect the reviewed source, add this Git repository to an agent's Ez catalog,
then install and start it through the standard `ez plugins` commands. Confirm
that the resulting `ez fast-browser` command is available before configuring
TypeSafe and an optional OpenAI-compatible text helper privately:

```sh
printf '%s' '{"typesafeApiKey":"...","textApiKey":"...","textBaseUrl":"https://openrouter.ai/api/v1","textModel":"inception/mercury-2.5"}' |
  ez fast-browser configure
ez fast-browser doctor
```

Use a private shell or agent-managed secret handoff; do not save that JSON in a
workspace file. `doctor` reports only readiness, never values.

For `logged-in` mode, configure a separate desktop companion and an explicit
list of bare allowed origins at the same time. See
[the desktop companion boundary](docs/desktop-companion.md). A browser profile,
cookie jar or Chrome debugging port is never mounted into the plugin container.

## Run

```sh
printf '%s' 'Find and open the Wikipedia article about Gödel’s incompleteness theorems.' |
  ez fast-browser run --mode isolated --url https://en.wikipedia.org/wiki/Main_Page --goal-file -
```

Read the returned snapshot before claiming success. Continue an active session
with a new goal, or close it after the task. See the installed skill for authority
and review requirements.

## Verification

The supported dependency range is declared in `requirements.txt`; the reviewed
runtime set is frozen in `requirements.lock.txt`. CI and the runtime image
install the lock so source, package and image verification use the same Python
dependency version.

Run the package checks:

```sh
npm run verify
npm pack --dry-run --ignore-scripts
```

A real acceptance run requires a configured TypeSafe key and must be performed
from the installed agent's actual bound executor. Verify the returned page title,
final URL and receipt, then close the session. The current local browser POC is
a reference implementation for the companion, not a substitute for this
installed-plugin acceptance check.
