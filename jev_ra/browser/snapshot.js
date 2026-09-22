// Adapted from jev-ultrafast (https://github.com/browser-use/jev-ultrafast).
// MIT License, Copyright (c) 2026 Browser Use. See THIRD_PARTY_NOTICES.md.
//
// One evaluation returns visible text, the observed elements, the operations they
// support, and the identity/freshness material the act-time guards compare against.
// Open shadow roots and same-origin iframes are flattened into the same list; a
// cross-origin iframe is reported as one opaque element instead.
(options => {
  if (!document.body) return null;
  const limit = options?.max_elements ?? 250;
  const cache = window.__jevRa ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const contentOf = frame => { try { return frame.contentDocument; } catch { return null; } };
  // Every root whose elements this page owns: the document, open shadow roots, same-origin frames.
  cache.roots = () => {
    const found=[document];
    const visit = root => {
      for (const e of root.querySelectorAll('*')) {
        if (e.shadowRoot) { found.push(e.shadowRoot); visit(e.shadowRoot); }
        else if (e.tagName==='IFRAME') { const doc=contentOf(e); if (doc?.body) { found.push(doc); visit(doc); } }
      }
    };
    visit(document);
    return found;
  };
  // A rect inside a frame is meaningless to CDP input, which speaks top-level coordinates.
  cache.offset = e => {
    let dx=0, dy=0, view=e.ownerDocument.defaultView;
    while (view && view!==window && view.frameElement) {
      const r=view.frameElement.getBoundingClientRect();
      dx+=r.x; dy+=r.y; view=view.frameElement.ownerDocument.defaultView;
    }
    return [dx,dy];
  };
  cache.deepest = (doc,x,y) => {
    let node=doc.elementFromPoint(x,y);
    while (node?.shadowRoot) {
      const inner=node.shadowRoot.elementFromPoint(x,y);
      if (!inner || inner===node) break;
      node=inner;
    }
    return node;
  };
  const safe = e => !['password','file','hidden'].includes(e.type);
  // Whether a pointer landing on `top` reaches `e`: itself, its own subtree, or the label that
  // forwards a click to it - which is how a shop paints its filter checkboxes.
  // Whether a pointer landing on `top` reaches `e`: itself, its own subtree, an ancestor that
  // took the pointer for it, or the label that forwards a click to it. A cover is none of those:
  // a consent wall is a sibling of what it hides, never its parent.
  cache.reaches = (e,top) => !!top &&
    (top===e || e.contains(top) || top.contains(e) || top.closest('label')?.control===e);
  // Where to put the pointer. The centre is where a person aims, but a bar floating over the
  // middle of a filter list leaves the names beside it perfectly clickable, so a few points along
  // the element are tried before giving up on it. The first one that reaches is the one used, by
  // observation and by execution alike, so what is offered is what can be pressed.
  cache.point = e => {
    const r=e.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    const [dx,dy]=cache.offset(e), midX=r.x+r.width/2, midY=r.y+r.height/2;
    const inset=(size,most)=>Math.min(size/4,most)+1;
    const tries=[[midX,midY],
      [r.x+inset(r.width,40),midY], [r.right-inset(r.width,40),midY],
      [midX,r.y+inset(r.height,12)], [midX,r.bottom-inset(r.height,12)]];
    for (let i=0; i<tries.length; i++) {
      const [x,y]=tries[i];
      if (x<0 || y<0 || x+dx<0 || y+dy<0 || x+dx>=innerWidth || y+dy>=innerHeight) continue;
      const top=cache.deepest(e.ownerDocument,x,y);
      // The centre is where a person aims, and an ancestor taking the pointer there is the
      // ordinary way a card carries the click for the link it wraps. Away from the centre that
      // reasoning does not hold: a point the element does not paint belongs to whatever is behind
      // it, and pressing there runs the row's handler rather than the link's. Off-centre, the
      // pointer has to land on the element itself or on something inside it.
      const reached = i===0 ? cache.reaches(e,top) : !!top && (top===e || e.contains(top));
      if (reached) return {x,y,top};
    }
    return null;
  };
  // Rendered: the browser lays it out and the accessibility tree keeps it. Visible: rendered and
  // not painted transparent. The two differ on purpose - a control drawn at opacity 0 over its own
  // artwork is the ordinary way to style a checkbox, and it still catches every click.
  const rendered = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkVisibilityCSS:true});
  const visible = e => rendered(e) && e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const root=e.getRootNode();
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(root.getElementById?.(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      // A select's children are its options, and joining their text names the whole list: a
      // country picker would call itself every country at once. Its selection names it instead.
      (e.tagName==='SELECT' ? [...e.selectedOptions].map(o=>o.label).join(', ')
        : e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a,button,input,textarea,select,summary,iframe,label,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  // A label only counts as a control of its own when the thing it labels has no pixels: a
  // dropdown checkbox sized to nothing, a toggle drawn entirely in CSS. Where the control is
  // there to be clicked, the label is just its name, and offering both says the same thing twice.
  const standIn = e => {
    if (e.tagName!=='LABEL') return null;
    const control=e.control;
    if (!control || !safe(control)) return null;
    const r=control.getBoundingClientRect();
    return (!rendered(control) || !r.width || !r.height) ? control : null;
  };
  const role = e => {
    const stand=standIn(e);
    if (stand) return role(stand);
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='IFRAME') return 'frame';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  cache.fields = () => cache.roots().flatMap(root=>[...root.querySelectorAll('input,textarea,select')])
    .filter(safe).map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly]);
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,cache.fields()];
  cache.guard=e=>{
    if (!e?.isConnected || !rendered(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  // Which item in a group you are on. aria-current is the standard answer; most of the web
  // instead puts a state class on the item or on the list item wrapping it, so a wrapper is
  // read only while it holds nothing but this element's own text.
  const STATE=/(?:^|[\s_-])(?:on|active|selected|current)(?:$|[\s_-])/i;
  const marked=e=>STATE.test(typeof e.className==='string'?e.className:(e.className?.baseVal||''));
  const current=e=>{
    const aria=e.getAttribute('aria-current');
    if (aria!==null) return aria!=='false';
    const own=(e.innerText||'').trim();
    for (let node=e, hops=0; node && hops<3; node=node.parentElement, hops++) {
      if (node!==e && (node.innerText||'').trim()!==own) break;
      if (marked(node)) return true;
    }
    return false;
  };
  // A page in front of the page: a modal dialog, or something pinned over a large part of the
  // viewport. A consent wall is the common one - the goal is behind it and the way through is one
  // of its own buttons - and what is inside it is all a run can reach while it is up. The pinned
  // kind is found by hit test rather than by walking the document, because a wall is by
  // definition the thing a pointer lands on, and five aims cost five ancestor walks.
  const area=innerWidth*innerHeight, covers=[];
  for (const root of cache.roots())
    for (const e of root.querySelectorAll('dialog[open],[role="dialog"],[aria-modal="true"]'))
      if (rendered(e)) covers.push(e);
  for (const [fx,fy] of [[.5,.5],[.25,.25],[.75,.25],[.25,.75],[.75,.75]]) {
    for (let node=cache.deepest(document,innerWidth*fx,innerHeight*fy); node; node=node.parentElement) {
      const position=getComputedStyle(node).position;
      if (position!=='fixed' && position!=='sticky') continue;
      const r=node.getBoundingClientRect();
      if (r.width*r.height>area*0.4 && !covers.includes(node)) covers.push(node);
    }
  }
  const covered=e=>covers.some(cover=>cover===e || cover.contains(e));
  const observed=[];
  for (const root of cache.roots()) {
    for (const e of root.querySelectorAll(selector)) {
      // A frame we can read is traversed, not offered; only an opaque one is an element.
      if (e.tagName==='IFRAME' && contentOf(e)?.body) continue;
      if (e.tagName==='A' && !e.hasAttribute('href') && !e.getAttribute('role') &&
          !e.hasAttribute('tabindex') && typeof e.onclick!=='function' &&
          getComputedStyle(e).cursor!=='pointer') continue;
      if (e.tagName==='LABEL' && !standIn(e)) continue;
      if (!safe(e) || !rendered(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
      const r=e.getBoundingClientRect(), [dx,dy]=cache.offset(e), rname=role(e);
      if (!rname) continue;
      // Whatever is offered here has to be reachable by the resolver: a consent wall leaves the
      // page under it visible to CSS and unclickable in fact, and what nobody can click is not
      // an action. Transparency counts against an element only when the pointer lands elsewhere:
      // a control wearing someone else's pixels still catches every press.
      const spot=cache.point(e);
      if (!spot || (spot.top!==e && !visible(e))) continue;
      if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
      const element={node:identity(e),role:rname,label:name(e)||rname,
        rect:{x:r.x+dx,y:r.y+dy,w:r.width,h:r.height}};
      if (root!==document) element.nested=true;
      for (const key of ['checked','selected','expanded']) {
        const value=e.getAttribute('aria-'+key);
        if (value!==null) element[key]=value;
      }
      if (current(e)) element.current='true';
      if (covered(e)) element.overlay='true';
      // Where a link goes, when that is somewhere else. An anchor resolves its own href, so a
      // relative one answers with this page's host and says nothing; mailto: and javascript:
      // have no host at all. Only a link that leaves the site says so.
      if (e.tagName==='A' && e.host && e.host!==location.host) element.host=e.host;
      if (['checkbox','radio'].includes(e.type)) element.checked=String(e.checked);
      const stand=standIn(e);
      if (stand && ['checkbox','radio'].includes(stand.type)) element.checked=String(stand.checked);
      observed.push({element:e, view:element});
    }
  }
  const omitted=Math.max(0,observed.length-limit);
  observed.splice(limit);
  const elements=[], actions=[];
  // An address with nothing after its `#` is the address without it: `href="#"` is a handler
  // wearing a link's clothes, and it goes nowhere.
  const address=u=>u.endsWith('#') ? u.slice(0,-1) : u;
  observed.forEach(({element:e, view}, index) => {
    const ref='e'+(index+1);
    view.ref=ref;
    elements.push(view);
    const shared={id:ref,node:view.node,role:view.role};
    // Where a web link would take the page, when that is somewhere else. A click on a link is
    // answered by an address, and a client router may push it well after the click, so the wait
    // after the click has to know which address it is waiting for.
    if (e.tagName==='A' && /^https?:/i.test(e.href) && address(e.href)!==address(location.href))
      shared.href=e.href;
    if (e.tagName==='SELECT') {
      view.value=[...e.selectedOptions].map(o=>o.label).join(', ');
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...shared,kind:'select',value:o.value,current_value:view.value,
          label:view.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(view.role) ||
          (view.role==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      view.value='value' in e ? String(e.value) :
        e.isContentEditable || view.role==='combobox' ? e.innerText.trim() : '';
      actions.push({...shared,kind:editable?'fill':'click',label:view.label,value:view.value});
      // A combobox often needs its list opened before its suggestions can be clicked.
      if (editable) actions.push({...shared,kind:'click',label:'Open '+view.label,value:view.value});
    }
  });
  // Two readings of one walk. `text` is what a reader can see right now, which is what one
  // decision gets. `doc_text` is what the page says: an article whose every word sits under a
  // full-screen hero is not a 200-character page, and a run that ends on one has to report it.
  const words=[], whole=[]; let length=0, total=0;
  const range=document.createRange();
  for (const root of cache.roots()) {
    const host=root.body ?? root;
    if (!host || (length>=6000 && total>=6000)) continue;
    const walker=(root.ownerDocument ?? root).createTreeWalker(host,NodeFilter.SHOW_TEXT);
    let node;
    while ((node=walker.nextNode()) && (length<6000 || total<6000)) {
      const value=node.textContent.trim(), parent=node.parentElement;
      if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
      if (total<6000) { whole.push(value); total+=value.length; }
      if (length>=6000) continue;
      range.selectNodeContents(node);
      const r=range.getBoundingClientRect(), [dx,dy]=cache.offset(parent);
      const top=r.top+dy, left=r.left+dx;
      if (r.width>0 && r.height>0 && top+r.height>0 && top<innerHeight && left+r.width>0 && left<innerWidth) {
        words.push(value); length+=value.length;
      }
    }
  }
  const text=words.join('\n').slice(0,6000), doc_text=whole.join('\n').slice(0,6000);
  const height=document.documentElement.scrollHeight;
  // A search palette that only answers to the Enter key has no control to click once its input
  // holds the query, so the key is offered as an operation. It lands wherever focus is at the
  // moment it is pressed, which is not necessarily where it was when this was observed: name the
  // field, so the decision says which one it meant and the act-time guard can check it.
  const active=document.activeElement;
  const typed=active?.tagName==='INPUT' && active.value?.trim() &&
    !['password','file','hidden','checkbox','radio','submit','button','reset','image'].includes(active.type);
  const submits=typed ? identity(active) : null;
  const page_key=cache.pageKey(), guards={};
  for (const element of elements) if (!(element.node in guards))
    guards[element.node]=cache.guard(cache.nodes.get(element.node));
  if (submits!==null && !(submits in guards)) guards[submits]=cache.guard(active);
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=elements.map(({rect,...rest})=>rest);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,actions,page_key[6]];
  if (submits!==null) actions.push({id:'press_enter',node:submits,kind:'press',key:'Enter',
    label:'Press Enter to submit '+(name(active)||'the focused field')});
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,doc_text,
    scroll:{y:scrollY,height},elements,actions,marker,page_key,guards,omitted};
})
