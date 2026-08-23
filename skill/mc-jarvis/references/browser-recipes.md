# Getting FFG's product page, per harness

`mc-jarvis init` normally needs no browser: it reads the rulebook list from
an archive.org capture of FFG's product page, and downloads the PDFs from
FFG's own CDN. It also checks the current Rules Reference version against a
mirror and takes the newer one, so a stale capture does not mean a stale
rulebook.

You only need this file when `init` says it could not reach archive.org, or
when the user wants the list FFG is publishing *right now* rather than the
one in the capture.

FFG's page returns 403 to plain HTTP clients and renders its links in
JavaScript, so it has to be fetched by something that runs a real browser —
or saved by hand. **Every route below ends in the same command**, so pick
whichever the user already has.

---

## No browser automation — works everywhere

The shortest path, and the one to suggest first. Nothing to install.

1. Open <https://www.fantasyflightgames.com/en/products/marvel-champions-the-card-game/>
2. Save the page: `Ctrl+S` / `Cmd+S`, choosing **Save Page As → Web Page,
   Complete** (or "Single File"). The links are in the HTML either way.
3. Run:

       mc-jarvis init --from-html ~/Downloads/marvel-champions.html

---

## Claude Code

Two options, whichever is connected.

**Claude in Chrome.** Navigate to the product page in the user's browser
and read it out:

    navigate → the product page
    read_page → save the HTML to a file

**Playwright MCP.** `browser_navigate` to the page, then
`browser_evaluate` returning `document.documentElement.outerHTML`, and
write the result to a file.

Either way, finish with:

    mc-jarvis init --from-html <file>

---

## Codex

Codex has no bundled browser. Use its shell to drive one the user already
has installed, or fall back to the manual save above. If Playwright is
available:

    npx playwright screenshot --full-page <url> /dev/null --save-har=page.har

is *not* enough — the HAR does not give you the DOM. Prefer:

    npx -y playwright open <url>

then save the page from the window that opens, and run:

    mc-jarvis init --from-html <file>

---

## opencode

opencode reads project skills from `.agents/skills`. It has no built-in
browser, so use whichever MCP browser server the user has configured, or
the manual save. Once you have the HTML:

    mc-jarvis init --from-html <file>

---

## pi

Same position as opencode: `.agents/skills`, no bundled browser. Use a
configured MCP browser server or the manual save, then:

    mc-jarvis init --from-html <file>

---

## Checking it worked

    mc-jarvis status

`rules_docs` names the rulebooks indexed and `rr_version` reports which
Rules Reference edition is in place. If a rulebook is missing, `update`
cannot fetch it — re-run `init`.
