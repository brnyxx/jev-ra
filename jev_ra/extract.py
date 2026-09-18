"""Structured page data straight from the DOM. No model runs here; the host LLM shapes the schema."""

import json

from .browser import actions

MAX_CHARS = 20000
MODES = ("text", "elements", "links", "tables", "main")

EXTRACT_JS = """(options => {
  const visible = e => e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) &&
    !e.closest('[aria-hidden="true"],[inert]');
  const clean = s => s.replace(/[ \\t]+/g,' ').replace(/ ?\\n ?/g,'\\n').replace(/\\n{3,}/g,'\\n\\n').trim();
  const BREAKS=['P','DIV','LI','TR','SECTION','ARTICLE','BR','UL','OL','TABLE','HEADER','FOOTER','NAV'];
  const render = root => {
    const parts=[];
    const walk = node => {
      for (const child of node.childNodes) {
        if (child.nodeType===3) { const t=child.textContent.trim(); if (t) parts.push(t); continue; }
        if (child.nodeType!==1 || ['SCRIPT','STYLE','NOSCRIPT','TEMPLATE'].includes(child.tagName)) continue;
        if (!visible(child)) continue;
        if (/^H[1-6]$/.test(child.tagName)) {
          parts.push('\\n' + '#'.repeat(+child.tagName[1]) + ' ' + child.innerText.trim() + '\\n');
          continue;
        }
        walk(child);
        if (BREAKS.includes(child.tagName)) parts.push('\\n');
      }
    };
    walk(root);
    return clean(parts.join(' '));
  };
  if (options.mode==='links')
    return {links:[...document.querySelectorAll('a[href]')].filter(visible)
      .map(a=>({text:(a.innerText.trim()||a.getAttribute('aria-label')||''), href:a.href}))};
  if (options.mode==='tables')
    return {tables:[...document.querySelectorAll('table')].filter(visible)
      .map(t=>({rows:[...t.rows].map(r=>[...r.cells].map(c=>c.innerText.trim()))}))};
  if (options.mode==='main') {
    // The tightest container that still holds most of the page's own prose.
    const score = e => {
      const own=(e.innerText||'').trim().length;
      const links=[...e.querySelectorAll('a')].reduce((n,a)=>n+a.innerText.length,0);
      return own-links;
    };
    const depth = e => { let n=0; while ((e=e.parentElement)) n++; return n; };
    const floor=score(document.body)*0.5;
    const ranked=[...document.querySelectorAll('main,article,section,div')].filter(visible)
      .map(e=>({e,depth:depth(e),value:score(e)})).sort((a,b)=>b.depth-a.depth);
    const best=ranked.find(item=>item.value>=floor && item.value>0);
    return {text:render(best ? best.e : document.body)};
  }
  return {text:render(document.body)};
})"""


def fit(payload, max_chars):
    """Trim the largest field until the JSON fits, and say so."""
    truncated = False
    while len(json.dumps(payload, ensure_ascii=False)) > max_chars:
        truncated = True
        if isinstance(payload.get("text"), str) and payload["text"]:
            payload["text"] = payload["text"][: max(0, int(len(payload["text"]) * 0.9)) - 1]
            continue
        lists = [key for key, value in payload.items() if isinstance(value, list) and value]
        if not lists:
            break
        longest = max(lists, key=lambda key: len(json.dumps(payload[key], ensure_ascii=False)))
        payload[longest] = payload[longest][:-1]
    return payload, truncated


def extract(session, mode="text", max_chars=MAX_CHARS):
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    page = session.observe()
    if mode == "elements":
        space = actions.build(page, session.max_elements)
        payload = {"elements": [actions.element_view(element) for element in space.elements], "omitted": space.omitted}
    else:
        payload = session.evaluate(f"({EXTRACT_JS})({json.dumps({'mode': mode})})") or {}
    payload, truncated = fit(payload, max_chars)
    return {
        "mode": mode,
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "truncated": truncated,
        **payload,
    }
