(() => {
  const toast = document.getElementById('toast');
  const dialog = document.getElementById('info-dialog');
  let toastTimer;

  function notify(message) {
    toast.textContent = message;
    toast.classList.add('show');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove('show'), 3600);
  }

  const viewCopy = {
    overview: ['Overview', 'Good afternoon, Admin', 'A clear view of your Blue Bot workspace and content activity.'],
    users: ['Users', 'User management', 'A future view for user lookup, access status, and account activity.'],
    library: ['Media Library', 'Media library', 'A future view for video and photo inventory, indexing, and metadata.'],
    activity: ['Activity', 'Activity timeline', 'A future view for verified bot events and operational logs.'],
    settings: ['Bot Settings', 'Bot configuration', 'A future view for safe, audited configuration management.'],
    access: ['Access & Roles', 'Access and roles', 'A future view for authenticated administrators and permission scopes.']
  };

  document.querySelectorAll('[data-view]').forEach(link => {
    link.addEventListener('click', event => {
      event.preventDefault();
      const view = link.dataset.view;
      const copy = viewCopy[view];
      if (!copy) return;
      document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('active', item === link));
      document.getElementById('breadcrumb-title').textContent = copy[0];
      document.getElementById('page-title').textContent = copy[1];
      document.getElementById('page-subtitle').textContent = copy[2];
      document.querySelector('.eyebrow').innerHTML = 'PREVIEW WORKSPACE <span class="eyebrow-line"></span> ' + copy[0].toUpperCase();
      document.getElementById('sidebar').classList.remove('open');
      if (view !== 'overview') notify('This section is a design placeholder. Live data and actions are not connected.');
      else notify('Overview preview selected. All displayed values are illustrative.');
    });
  });

  document.getElementById('refresh-button').addEventListener('click', () => {
    notify('Preview refreshed. No production services were contacted.');
  });
  document.getElementById('notice-dismiss').addEventListener('click', () => {
    document.querySelector('.preview-notice').remove();
  });
  document.getElementById('help-button').addEventListener('click', () => dialog.showModal());
  document.getElementById('connection-details').addEventListener('click', () => dialog.showModal());
  document.getElementById('dialog-close').addEventListener('click', () => dialog.close());
  document.getElementById('dialog-ok').addEventListener('click', () => dialog.close());
  document.getElementById('view-activity').addEventListener('click', () => {
    document.querySelector('[data-view="activity"]').click();
    document.getElementById('recent-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
  });
  document.getElementById('period-select').addEventListener('change', event => {
    notify('Chart period changed to ' + event.target.options[event.target.selectedIndex].text + '. Sample values remain illustrative.');
  });
  document.getElementById('menu-toggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('open');
  });
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
})();
