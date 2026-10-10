(() => {
  const webApp = window.Telegram && window.Telegram.WebApp;
  const byId = id => document.getElementById(id);
  const notice = byId('notice');
  if (webApp && webApp.initData) document.body.classList.add('telegram-ready');

  function setNotice(message, state) {
    notice.textContent = message;
    notice.dataset.state = state || 'info';
  }

  function formatCount(value) {
    return Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString() : '—';
  }

  async function loadOverview() {
    if (!webApp || !webApp.initData) {
      byId('connection-title').textContent = 'Open from Telegram';
      byId('connection-description').textContent = 'Owner identity is not available in this browser.';
      setNotice('For security, Blue Bot data is available only inside the Telegram Mini App.', 'error');
      return;
    }
    try {
      webApp.ready();
      webApp.expand();
      if (webApp.setHeaderColor) webApp.setHeaderColor('#080d1a');
      if (webApp.setBackgroundColor) webApp.setBackgroundColor('#080d1a');
      const response = await fetch('/admin/api/overview', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({initData: webApp.initData}),
        cache: 'no-store',
        credentials: 'omit'
      });
      const payload = await response.json();
      if (!response.ok) {
        byId('connection-title').textContent = response.status === 403 ? 'Owner access denied' : 'Connection unavailable';
        byId('connection-description').textContent = 'Telegram identity could not be authorized.';
        setNotice(response.status === 403 ? 'This Telegram account is not authorized as a bot owner.' : 'Unable to load live overview. Try again shortly.', 'error');
        return;
      }
      const ownerName = typeof payload.owner?.name === 'string' ? payload.owner.name : 'Owner';
      byId('greeting').textContent = 'Welcome, ' + ownerName;
      byId('metric-users').textContent = formatCount(payload.users);
      byId('metric-media').textContent = formatCount(payload.media);
      byId('metric-videos').textContent = formatCount(payload.videos);
      byId('metric-photos').textContent = formatCount(payload.photos);
      byId('media-breakdown').textContent = formatCount(payload.videos) + ' videos · ' + formatCount(payload.photos) + ' photos';
      byId('connection-title').textContent = 'Bot overview connected';
      byId('connection-description').textContent = 'Authenticated as Telegram owner ID ' + payload.owner.id;
      setNotice('Live aggregate statistics loaded securely from Blue Bot.', 'success');
    } catch (_error) {
      byId('connection-title').textContent = 'Connection unavailable';
      byId('connection-description').textContent = 'Could not reach the Mini App API.';
      setNotice('Unable to load the overview. Check your connection and retry.', 'error');
    }
  }

  byId('refresh-button').addEventListener('click', loadOverview);
  document.querySelectorAll('[data-feature]').forEach(button => {
    button.addEventListener('click', () => {
      const labels = {users: 'User management', media: 'Media library', settings: 'Bot settings'};
      setNotice(labels[button.dataset.feature] + ' is not connected yet. Only verified read-only overview statistics are available.', 'info');
    });
  });
  if (webApp) {
    try { webApp.ready(); webApp.expand(); } catch (_error) {}
    if (webApp.BackButton) webApp.BackButton.hide();
  }
  loadOverview();
})();
