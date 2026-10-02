# Security

## Reporting a vulnerability

Please report it privately, not in a public issue:
**[open a private security advisory](https://github.com/DoxaLogosGit/mc-jarvis-skill/security/advisories/new)**.

Include what you found, how to reproduce it, and which release you used.
This is a one-person hobby project, so replies are best-effort - but a
reported vulnerability is fixed and released before its details are made
public.

## What counts

mc-jarvis is a skill an AI agent follows on your machine, plus the tool it
runs. Security problems include, among others:

- a way for card data, a rulebook or a decklist to make the tool run
  something, or to make the agent follow instructions hidden in it;
- an instruction in `SKILL.md` or its references that leads an agent to do
  something harmful;
- the tool reading or writing outside its own data directory and the
  project folder it was run in (`install-skill --global`, which you ask
  for by name, writes to your harnesses' skill folders - that is
  expected);
- anything in the release workflow, or in a published release, that
  differs from what this repository builds.

A wrong card answer or a wrong rules citation is a bug, not a security
problem - please open an ordinary issue for those.

## Supported versions

Only the latest release receives fixes.
