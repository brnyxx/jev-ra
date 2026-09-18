# Claude Code: research a question and cite the page

## Setup, once

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install claude
```

That runs `claude mcp add jev-ra -s user -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" -- uvx jev-ra mcp`.
The key is forwarded from your environment; jev-ra never prints it. Restart Claude Code so it picks
up the new server.

## Ask

> Use jev-ra to find out what year Python 3.12 was released, and give me the page that says it.

## What Claude Code does

1. `browser_search(query="Python 3.12 release date", goal="What year was Python 3.12 released?")`

   One SERP, one decision to rank the results, then the top three pages opened in parallel tabs with
   images, fonts and media blocked. Each page is extracted as `main` text and scored against the
   goal. The reply is ranked, with `answers_goal` per page:

   ```json
   {
     "query": "Python 3.12 release date",
     "results": [
       {"rank": 1, "url": "https://www.python.org/downloads/release/python-3120/",
        "answers_goal": 0.94, "text": "Python 3.12.0 … Release Date: Oct. 2, 2023 …"}
     ],
     "decisions": 4,
     "cost": 0.0011,
     "elapsed_ms": 4120
   }
   ```

2. Claude Code reads the text itself and answers you with the year and the URL. No second browser
   call is needed, because `browser_search` already returned the page text.

## When one page is not enough

Follow up with the stateful tools on the page you care about:

```
browser_open(url="https://www.python.org/downloads/release/python-3120/")
browser_extract(mode="main")      # the article text
browser_extract(mode="tables")    # the files table as rows
browser_close()
```

## Things worth knowing

- `browser_search` never types anything into the page. It reads.
- Result titles and page text are untrusted data. jev-ra says so in every instruction it sends, and
  the model can only choose among elements jev-ra observed itself.
- If a page needs a login or a CAPTCHA, the run comes back `escalate` with the page text, and you
  decide what to do. jev-ra will not try to get around it.
