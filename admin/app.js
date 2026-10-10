(() => {
  const webApp = window.Telegram && window.Telegram.WebApp;
  const byId = id => document.getElementById(id);
  const notice = byId('notice');
  const overviewView = byId('overview-view');
  const usersView = byId('user-management-view');
  const userList = byId('user-list');
  let usersPage = 1;
  let usersPages = 1;
  let searchTimer = null;
  let usersRequest = 0;

  if (webApp && webApp.initData) document.body.classList.add('telegram-ready');

  function setNotice(message, state) {
    notice.textContent = message;
    notice.dataset.state = state || 'info';
  }

  function formatCount(value) {
    return Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString() : '—';
  }

  function ownerInitData() {
    return webApp && typeof webApp.initData === 'string' ? webApp.initData : '';
  }

  async function postOwnerApi(path, extra = {}) {
    const initData = ownerInitData();
    if (!initData) throw new Error('telegram_required');
    const response = await fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: JSON.stringify({initData, ...extra}),
      cache: 'no-store',
      credentials: 'omit'
    });
    let payload;
    try { payload = await response.json(); } catch (_error) { throw new Error('invalid_response'); }
    if (!response.ok) {
      const error = new Error(payload && payload.error ? payload.error : 'request_failed');
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  async function loadOverview() {
    if (!ownerInitData()) {
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
      const payload = await postOwnerApi('/admin/api/overview');
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
    } catch (error) {
      byId('connection-title').textContent = error.status === 403 ? 'Owner access denied' : 'Connection unavailable';
      byId('connection-description').textContent = 'Telegram identity could not be authorized.';
      setNotice(error.status === 403 ? 'This Telegram account is not authorized as a bot owner.' : 'Unable to load the overview. Check your connection and retry.', 'error');
    }
  }

  function makeElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function renderUsers(items) {
    userList.replaceChildren();
    if (!Array.isArray(items) || items.length === 0) {
      userList.append(makeElement('div', 'empty-users', 'No users matched this search.'));
      return;
    }
    items.forEach(user => {
      const card = makeElement('article', 'user-card');
      const avatar = makeElement('span', 'user-avatar', (user.first_name || user.username || '?').trim().slice(0, 1).toUpperCase());
      const details = makeElement('div', 'user-details');
      const name = makeElement('strong', 'user-name', user.first_name || (user.username ? '@' + user.username : 'Unnamed user'));
      const handle = makeElement('small', 'user-handle', user.username ? '@' + user.username : 'No username');
      const userId = makeElement('small', 'user-id', 'ID ' + user.id);
      const meta = makeElement('div', 'user-meta');
      const shares = makeElement('span', 'share-count', formatCount(user.shares) + ' shares');
      const state = makeElement('span', user.is_banned ? 'user-state banned' : 'user-state active', user.is_banned ? 'Banned' : 'Active');
      details.append(name, handle, userId);
      meta.append(shares, state);
      card.append(avatar, details, meta);
      userList.append(card);
    });
  }

  async function loadUsers() {
    if (!ownerInitData()) {
      byId('user-list-status').textContent = 'Open this screen inside the authorized Telegram Mini App.';
      return;
    }
    const requestId = ++usersRequest;
    byId('user-list-status').textContent = 'Loading users securely…';
    byId('users-prev').disabled = true;
    byId('users-next').disabled = true;
    try {
      const payload = await postOwnerApi('/admin/api/users', {
        query: byId('user-search').value.trim(),
        page: usersPage,
        pageSize: 20
      });
      if (requestId !== usersRequest) return;
      usersPages = Math.max(1, Number(payload.pages) || 1);
      usersPage = Math.min(Math.max(1, Number(payload.page) || 1), usersPages);
      byId('user-total').textContent = formatCount(payload.total) + ' users';
      byId('users-page-label').textContent = 'Page ' + usersPage + ' of ' + usersPages;
      byId('users-prev').disabled = usersPage <= 1;
      byId('users-next').disabled = usersPage >= usersPages;
      byId('user-list-status').textContent = formatCount(payload.total) + ' matching users · read-only';
      renderUsers(payload.items);
    } catch (error) {
      if (requestId !== usersRequest) return;
      userList.replaceChildren();
      byId('user-list-status').textContent = error.status === 403
        ? 'Owner access denied. Reopen the Mini App from your owner Telegram account.'
        : 'Unable to load users. Check the connection and try again.';
      setNotice('User directory could not be loaded.', 'error');
    }
  }

  function openUsers() {
    overviewView.hidden = true;
    usersView.hidden = false;
    usersPage = 1;
    loadUsers();
  }

  function showOverview() {
    usersView.hidden = true;
    overviewView.hidden = false;
  }

  byId('refresh-button').addEventListener('click', loadOverview);
  byId('back-to-overview').addEventListener('click', showOverview);
  byId('user-search').addEventListener('input', () => {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { usersPage = 1; loadUsers(); }, 250);
  });
  byId('users-prev').addEventListener('click', () => {
    if (usersPage > 1) { usersPage -= 1; loadUsers(); }
  });
  byId('users-next').addEventListener('click', () => {
    if (usersPage < usersPages) { usersPage += 1; loadUsers(); }
  });
  document.querySelectorAll('[data-feature]').forEach(button => {
    button.addEventListener('click', () => {
      if (button.dataset.feature === 'users') {
        openUsers();
        setNotice('User directory opened with read-only access.', 'success');
        return;
      }
      const labels = {media: 'Media library', settings: 'Bot settings'};
      setNotice(labels[button.dataset.feature] + ' is not connected yet. User directory and overview are available in this phase.', 'info');
    });
  });
  if (webApp) {
    try { webApp.ready(); webApp.expand(); } catch (_error) {}
    try {
      if (webApp.BackButton) webApp.BackButton.hide();
    } catch (_error) {
      // A host-specific BackButton failure must not prevent overview loading.
    }
  }
  loadOverview();
})();
