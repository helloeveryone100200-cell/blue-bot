(() => {
  const shell = document.querySelector('.app-shell');
  if (!shell) return;
  const nav = document.createElement('nav');
  nav.className = 'admin-bottom-nav';
  nav.setAttribute('aria-label', 'Owner dashboard navigation');
  const items = [
    {id:'overview',label:'Overview',icon:'⌂'},
    {id:'users',label:'Users',icon:'♙'},
    {id:'media',label:'Media',icon:'▣'},
    {id:'settings',label:'Settings',icon:'⚙'},
    {id:'owner-controls',label:'Controls',icon:'🛡'}
  ];
  const setCurrent = id => Array.from(nav.children).forEach(button =>
    button.setAttribute('aria-current', button.dataset.view === id ? 'page' : 'false'));
  items.forEach((item,index) => {
    const button=document.createElement('button');
    button.type='button'; button.dataset.view=item.id;
    button.setAttribute('aria-current',index===0?'page':'false');
    const icon=document.createElement('span'); icon.className='nav-icon'; icon.setAttribute('aria-hidden','true'); icon.textContent=item.icon;
    const label=document.createElement('span'); label.className='nav-label'; label.textContent=item.label;
    button.append(icon,label);
    button.addEventListener('click',()=>{
      if(item.id==='overview'){
        const back=document.getElementById('back-to-overview');
        if(back) back.click();
        const refresh=document.getElementById('refresh-button');
        if(refresh) refresh.click();
      } else {
        const shortcut=document.querySelector('[data-feature="'+item.id+'"]');
        if(shortcut) shortcut.click();
      }
      setCurrent(item.id);
      window.scrollTo({top:0,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
    });
    nav.appendChild(button);
  });
  const footer=shell.querySelector(':scope > footer');
  shell.insertBefore(nav,footer||null);
  document.querySelectorAll('[data-feature]').forEach(button=>{
    button.addEventListener('click',()=>{
      const view=button.dataset.feature;
      setCurrent(view);
    });
  });
  ['back-to-overview','back-from-media','back-from-settings','back-from-owner-controls'].forEach(id=>{
    const button=document.getElementById(id);
    if(button) button.addEventListener('click',()=>setCurrent('overview'));
  });
})();