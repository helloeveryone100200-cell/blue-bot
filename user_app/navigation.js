(() => {
  const shell = document.querySelector('.app-shell');
  if (!shell) return;
  const footer = shell.querySelector(':scope > footer');
  const directHeadings = Array.from(shell.querySelectorAll(':scope > .section-heading'));
  const findHeading = text => directHeadings.find(node => node.textContent.includes(text));
  const pageDefinitions = [
    { id: 'home', label: 'Home', icon: '⌂', aria: 'Dashboard overview', nodes: [
      shell.querySelector(':scope > .welcome'), document.getElementById('notice'),
      shell.querySelector(':scope > .profile-card'), findHeading('Your activity'),
      shell.querySelector(':scope > .metric-grid'), findHeading('What would you like to do?'),
      shell.querySelector(':scope > .action-list')
    ]},
    { id: 'referrals', label: 'Invite', icon: '↗', aria: 'Referral center', nodes: [
      document.getElementById('referral-heading'), shell.querySelector(':scope > .referral-panel')
    ]},
    { id: 'library', label: 'Library', icon: '▣', aria: 'Public and saved video library', nodes: [
      document.getElementById('video-library-heading'), shell.querySelector(':scope > .video-library'),
      document.getElementById('saved-videos-heading'), shell.querySelector(':scope > .saved-videos-library')
    ]},
    { id: 'activity', label: 'Activity', icon: '◷', aria: 'Recent dashboard activity', nodes: [
      document.getElementById('activity-heading'), shell.querySelector(':scope > .activity-panel')
    ]},
    { id: 'account', label: 'Account', icon: '⚙', aria: 'Help, notification preferences, and account privacy', nodes: [
      document.getElementById('help-center-heading'), shell.querySelector(':scope > .help-center'),
      document.getElementById('notification-preferences-heading'), shell.querySelector(':scope > .notification-panel'),
      document.getElementById('account-privacy-heading'), shell.querySelector(':scope > .privacy-panel')
    ]}
  ];
  const pages = [];
  pageDefinitions.forEach((definition, index) => {
    const page = document.createElement('section');
    page.id = 'dashboard-page-' + definition.id;
    page.className = 'dashboard-page';
    page.setAttribute('aria-label', definition.aria);
    page.hidden = index !== 0;
    definition.nodes.filter(Boolean).forEach(node => page.appendChild(node));
    pages.push(page);
    shell.insertBefore(page, footer || null);
  });
  const nav = document.createElement('nav');
  nav.className = 'dashboard-bottom-nav';
  nav.setAttribute('aria-label', 'Dashboard navigation');
  pageDefinitions.forEach((definition, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-controls', 'dashboard-page-' + definition.id);
    button.setAttribute('aria-current', index === 0 ? 'page' : 'false');
    const icon = document.createElement('span');
    icon.className = 'nav-icon'; icon.setAttribute('aria-hidden', 'true'); icon.textContent = definition.icon;
    const label = document.createElement('span');
    label.className = 'nav-label'; label.textContent = definition.label;
    button.append(icon, label);
    button.addEventListener('click', () => {
      pages.forEach((page, pageIndex) => { page.hidden = pageIndex !== index; });
      Array.from(nav.children).forEach((item, itemIndex) => item.setAttribute('aria-current', itemIndex === index ? 'page' : 'false'));
      const main = shell.querySelector('main');
      if (main) main.focus({preventScroll: true});
      window.scrollTo({top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    });
    nav.appendChild(button);
  });
  shell.insertBefore(nav, footer || null);
})();