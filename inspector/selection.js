(() => {
  if (window !== window.top || window.__smartRpa) return;
  let selecting = false;
  let chosen = null;
  let box;
  let host;
  const setMode = (active, message) => {
    selecting = active;
    if (box) box.style.display = 'none';
    if (host) host.shadowRoot.querySelector('[data-status]').textContent = message || (active ? 'Selecting — click a target · Esc cancels' : 'Browsing');
  };
  const draw = (element) => {
    const rect = element.getBoundingClientRect();
    // Draw outside the target bounds so screenshot masking cannot hide its outline.
    Object.assign(box.style, {display:'block', left:(rect.x-3)+'px', top:(rect.y-3)+'px', width:(rect.width+6)+'px', height:(rect.height+6)+'px'});
  };
  const emit = (action) => window.__smartRpaAction(action).catch(() => setMode(false, 'Inspector disconnected'));
  const init = () => {
    host = document.createElement('div');
    host.id = '__smart-rpa-toolbar';
    host.style.cssText = 'all:initial;position:fixed;right:16px;top:16px;z-index:2147483647';
    const shadow = host.attachShadow({mode:'open'});
    shadow.innerHTML = `<style>:host{font:14px system-ui}section{background:#142b38;color:white;padding:12px;border-radius:10px;box-shadow:0 3px 16px #0004;max-width:340px}strong,span{display:block;margin-bottom:8px}button{font:inherit;margin:3px;padding:7px;border:0;border-radius:5px;cursor:pointer}button[data-action=stop]{background:#ffd9d9}</style><section><strong>Smart RPA Inspector</strong><span data-status>Browsing</span><button data-action="select">Select element</button><button data-action="cancel">Cancel selection</button><button data-action="stop">Stop inspector</button><button data-action="move">Move toolbar</button></section>`;
    shadow.addEventListener('click', (event) => {
      const action = event.target.dataset.action;
      if (action === 'move') {
        const bottom = host.style.bottom === '16px';
        host.style.top = bottom ? '16px' : 'auto';
        host.style.bottom = bottom ? 'auto' : '16px';
        return;
      }
      if (action) { if (action === 'cancel') setMode(false); emit({action}); }
    });
    box = document.createElement('div');
    box.id = '__smart-rpa-highlight';
    box.style.cssText = 'display:none;position:fixed;pointer-events:none;z-index:2147483646;border:3px solid #00b5d1;box-sizing:border-box;background:#00b5d115';
    document.documentElement.append(host, box);
  };
  window.__smartRpa = {
    documentId: Math.random().toString(36).slice(2) + Date.now().toString(36),
    select: () => setMode(true),
    cancel: () => setMode(false),
    message: (value) => setMode(false, value),
    highlight: (element) => draw(element),
    hideToolbar: () => { host.style.visibility = 'hidden'; },
    showToolbar: () => { host.style.visibility = 'visible'; },
    metadata: (target) => {
      const el = target || chosen;
      if (!el || !el.isConnected) throw new Error('Selected element disappeared');
      const tag = el.tagName.toLowerCase();
      if (['iframe','frame','canvas','object','embed','video'].includes(tag)) return {unsupported:true};
      const label = Array.from(el.labels || []).map(item => item.innerText.trim()).join(' ').slice(0,160);
      const labelled = (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ').trim();
      const text = !el.closest('[contenteditable]:not([contenteditable="false"])') && ['button','a','option','summary','label','h1','h2','h3','h4','h5','h6','p','span'].includes(tag) ? (el.innerText || '').trim().slice(0,160) : '';
      const attributes = {};
      for (const key of ['id','name','type','placeholder','data-testid','aria-label','title','alt']) {
        const value = el.getAttribute(key);
        if (value) attributes[key] = value.slice(0,200);
      }
      let role = el.getAttribute('role') || ({button:'button',a:el.hasAttribute('href')?'link':'',textarea:'textbox',select:'combobox',img:'img',summary:'button'}[tag] || '');
      if (/^h[1-6]$/.test(tag) && !role) role = 'heading';
      if (tag === 'input') role = ({checkbox:'checkbox',radio:'radio',button:'button',submit:'button',range:'slider',number:'spinbutton',password:''}[el.type] ?? 'textbox');
      return {tag, role, name:(el.getAttribute('aria-label') || labelled || label || attributes.alt || text || attributes.title || '').slice(0,160), label, attributes};
    },
    selected: () => chosen,
  };
  document.addEventListener('pointermove', (event) => {
    if (selecting && !event.composedPath().includes(host)) draw(event.target);
  }, true);
  for (const type of ['pointerdown','pointerup','mousedown','mouseup','click','dblclick','contextmenu']) {
    document.addEventListener(type, (event) => {
      if (!selecting || event.composedPath().includes(host)) return;
      event.preventDefault(); event.stopImmediatePropagation();
      if (type === 'click') {
        chosen = event.target.closest('button,a,input,textarea,select,[role]') || event.target;
        setMode(false, 'Capturing…'); draw(chosen);
        emit({action:'capture'});
      }
    }, true);
  }
  document.addEventListener('keydown', event => { if (selecting && event.key === 'Escape') {event.preventDefault(); setMode(false); emit({action:'cancel'});} }, true);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true}); else init();
})();
