(() => {
  const webApp = window.Telegram && window.Telegram.WebApp;
  const byId = id => document.getElementById(id);
  const notice = byId('notice');
  const overviewView = byId('overview-view');
  const usersView = byId('user-management-view');
  const userList = byId('user-list');
  const mediaView = byId('media-library-view');
  const mediaList = byId('media-list');
  const settingsView = byId('bot-settings-view');
  const settingsList = byId('settings-list');
  let usersPage = 1;
  let usersPages = 1;
  let mediaPage = 1;
  let mediaPages = 1;
  let userSearchTimer = null;
  let mediaSearchTimer = null;
  let usersRequest = 0;
  let mediaRequest = 0;
  let settingsRequest = 0;
  let userDetailRequest = 0;

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
      const actions = makeElement('div', 'user-card-actions');
      const detailButton = makeElement('button', 'user-detail-button', 'View details');
      detailButton.type = 'button';
      detailButton.addEventListener('click', () => loadUserDetail(user.id));
      actions.append(detailButton);
      card.append(avatar, details, meta, actions);
      userList.append(card);
    });
  }

  async function loadUserDetail(userId) {
    const requestId = ++userDetailRequest;
    setNotice('Loading user details securely…', 'info');
    try {
      const user = await postOwnerApi('/admin/api/user-detail', {userId: String(userId)});
      if (requestId !== userDetailRequest) return;
      const card = makeElement('section', 'user-detail-panel');
      const heading = makeElement('div', 'user-detail-heading');
      heading.append(
        makeElement('p', 'eyebrow', 'USER RECORD'),
        makeElement('h3', '', user.first_name || (user.username ? '@' + user.username : 'User ' + user.id))
      );
      const close = makeElement('button', 'back-button', '‹ Back to user list');
      close.type = 'button';
      close.addEventListener('click', () => {
        // Invalidate any in-flight detail request so a late response cannot reopen this view.
        userDetailRequest += 1;
        card.remove();
        userList.hidden = false;
        byId('user-list-status').hidden = false;
        byId('user-total').hidden = false;
        byId('user-search-label').hidden = false;
        byId('user-search').hidden = false;
        byId('user-pagination').hidden = false;
      });
      const fields = makeElement('div', 'user-detail-fields');
      const addField = (label, value) => {
        const item = makeElement('div', 'user-detail-field');
        item.append(makeElement('small', '', label), makeElement('strong', '', String(value)));
        fields.append(item);
      };
      addField('Telegram ID', user.id);
      addField('Username', user.username ? '@' + user.username : 'Not set');
      addField('Shares', formatCount(user.shares));
      addField('Referrals', formatCount(user.referrals));
      addField('Account status', user.is_banned ? 'Banned' : 'Active');
      addField('Current state', user.state || 'normal');
      addField('Joined', user.joined_at || '—');
      card.append(heading, close, fields, makeElement('p', 'read-only-note', 'Read-only user details. No account changes are available here.'));
      userList.hidden = true;
      byId('user-list-status').hidden = true;
      byId('user-total').hidden = true;
      byId('user-search-label').hidden = true;
      byId('user-search').hidden = true;
      byId('user-pagination').hidden = true;
      const previous = byId('user-detail-panel');
      if (previous) previous.remove();
      card.id = 'user-detail-panel';
      userList.parentNode.insertBefore(card, userList);
      setNotice('User details loaded in read-only mode.', 'success');
    } catch (error) {
      if (requestId !== userDetailRequest) return;
      setNotice(error.status === 404 ? 'User record was not found.' : 'Unable to load user details securely.', 'error');
    }
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

  function renderMedia(items) {
    mediaList.replaceChildren();
    if (!Array.isArray(items) || items.length === 0) {
      mediaList.append(makeElement('div', 'empty-users', 'No media matched this search.'));
      return;
    }
    items.forEach(item => {
      const card = makeElement('article', 'media-card');
      const icon = makeElement('span', 'media-avatar', item.kind === 'photo' ? '▧' : '▷');
      const details = makeElement('div', 'media-details');
      const title = makeElement('strong', 'media-name', item.id);
      const caption = makeElement('small', 'media-caption', item.caption || 'No caption');
      const stats = makeElement('small', 'media-stats',
        (item.kind === 'photo' ? item.photo_parts + ' photo(s)' : item.video_parts + ' video(s)') +
        (item.photo_parts && item.kind === 'video' ? ' · ' + item.photo_parts + ' attached photo(s)' : '') +
        (item.kind === 'video' ? ' · ' + formatCount(item.views) + ' views' : ''));
      const meta = makeElement('div', 'media-meta');
      const visibility = makeElement('span', item.visibility === 'private' ? 'media-state private' : 'media-state public', item.visibility);
      const type = makeElement('span', 'media-type', item.kind);
      details.append(title, caption, stats);
      meta.append(visibility, type);
      if (item.kind === 'video') {
        meta.append(makeElement('small', 'media-rating', '👍 ' + formatCount(item.likes) + '  ·  👎 ' + formatCount(item.dislikes)));
      }
      card.append(icon, details, meta);
      mediaList.append(card);
    });
  }

  async function loadMedia() {
    if (!ownerInitData()) {
      byId('media-list-status').textContent = 'Open this screen inside the authorized Telegram Mini App.';
      return;
    }
    const requestId = ++mediaRequest;
    byId('media-list-status').textContent = 'Loading media metadata securely…';
    byId('media-prev').disabled = true;
    byId('media-next').disabled = true;
    try {
      const payload = await postOwnerApi('/admin/api/media', {
        query: byId('media-search').value.trim(),
        kind: byId('media-kind').value,
        page: mediaPage,
        pageSize: 20
      });
      if (requestId !== mediaRequest) return;
      mediaPages = Math.max(1, Number(payload.pages) || 1);
      mediaPage = Math.min(Math.max(1, Number(payload.page) || 1), mediaPages);
      byId('media-total').textContent = formatCount(payload.total) + ' items';
      byId('media-page-label').textContent = 'Page ' + mediaPage + ' of ' + mediaPages;
      byId('media-prev').disabled = mediaPage <= 1;
      byId('media-next').disabled = mediaPage >= mediaPages;
      byId('media-list-status').textContent = formatCount(payload.total) + ' matching items · metadata only';
      renderMedia(payload.items);
    } catch (error) {
      if (requestId !== mediaRequest) return;
      mediaList.replaceChildren();
      byId('media-list-status').textContent = error.status === 403
        ? 'Owner access denied. Reopen the Mini App from your owner Telegram account.'
        : 'Unable to load media. Check the connection and try again.';
      setNotice('Media inventory could not be loaded.', 'error');
    }
  }

  function renderSetting(title, value, detail, enabled) {
    const row = makeElement('article', 'setting-card');
    const details = makeElement('div', 'setting-details');
    details.append(makeElement('strong', 'setting-title', title), makeElement('small', 'setting-description', detail));
    const status = makeElement('span', enabled ? 'setting-value enabled' : 'setting-value disabled', value);
    row.append(details, status);
    settingsList.append(row);
  }

  async function loadSettings() {
    if (!ownerInitData()) {
      byId('settings-list-status').textContent = 'Open this screen inside the authorized Telegram Mini App.';
      return;
    }
    const requestId = ++settingsRequest;
    byId('settings-list-status').textContent = 'Loading current configuration securely…';
    settingsList.replaceChildren();
    try {
      const payload = await postOwnerApi('/admin/api/settings');
      if (requestId !== settingsRequest) return;
      const channelEnabled = Boolean(payload.channel_gate && payload.channel_gate.enabled);
      renderSetting('Required channel gate', channelEnabled ? 'Enabled' : 'Disabled',
        channelEnabled ? (payload.channel_gate.title || 'A required channel is configured') : 'No required channel is active',
        channelEnabled);
      renderSetting('Public media group', payload.public_media_group_configured ? 'Connected' : 'Not configured',
        'Source for public video and photo uploads', Boolean(payload.public_media_group_configured));
      renderSetting('Private media group', payload.private_media_group_configured ? 'Connected' : 'Not configured',
        'Source for private media uploads', Boolean(payload.private_media_group_configured));
      renderSetting('New-video auto broadcast', payload.auto_broadcast_new_video ? 'Enabled' : 'Disabled',
        'Automatically notify users when a new public video is added', Boolean(payload.auto_broadcast_new_video));
      renderSetting('Private-access users', formatCount(payload.private_access_users),
        'Users granted private-group access; user IDs are not exposed here', Number(payload.private_access_users) > 0);
      byId('settings-list-status').textContent = 'Current configuration loaded · inspection only';
    } catch (error) {
      if (requestId !== settingsRequest) return;
      byId('settings-list-status').textContent = error.status === 403
        ? 'Owner access denied. Reopen the Mini App from your owner Telegram account.'
        : 'Unable to load settings. Check the connection and try again.';
      setNotice('Bot settings could not be loaded.', 'error');
    }
  }

  function openUsers() {
    const detailPanel = byId('user-detail-panel');
    if (detailPanel) detailPanel.remove();
    userList.hidden = false;
    byId('user-list-status').hidden = false;
    byId('user-total').hidden = false;
    byId('user-search-label').hidden = false;
    byId('user-search').hidden = false;
    byId('user-pagination').hidden = false;
    overviewView.hidden = true;
    mediaView.hidden = true;
    settingsView.hidden = true;
    usersView.hidden = false;
    usersPage = 1;
    loadUsers();
  }

  function openMedia() {
    overviewView.hidden = true;
    usersView.hidden = true;
    settingsView.hidden = true;
    mediaView.hidden = false;
    mediaPage = 1;
    loadMedia();
  }

  function openSettings() {
    overviewView.hidden = true;
    usersView.hidden = true;
    mediaView.hidden = true;
    settingsView.hidden = false;
    loadSettings();
  }

  function showOverview() {
    usersView.hidden = true;
    mediaView.hidden = true;
    settingsView.hidden = true;
    overviewView.hidden = false;
  }

  byId('refresh-button').addEventListener('click', loadOverview);
  byId('back-to-overview').addEventListener('click', showOverview);
  byId('back-from-media').addEventListener('click', showOverview);
  byId('back-from-settings').addEventListener('click', showOverview);
  byId('user-search').addEventListener('input', () => {
    if (userSearchTimer) clearTimeout(userSearchTimer);
    userSearchTimer = setTimeout(() => { usersPage = 1; loadUsers(); }, 250);
  });
  byId('media-search').addEventListener('input', () => {
    if (mediaSearchTimer) clearTimeout(mediaSearchTimer);
    mediaSearchTimer = setTimeout(() => { mediaPage = 1; loadMedia(); }, 250);
  });
  byId('media-kind').addEventListener('change', () => { mediaPage = 1; loadMedia(); });
  byId('users-prev').addEventListener('click', () => {
    if (usersPage > 1) { usersPage -= 1; loadUsers(); }
  });
  byId('users-next').addEventListener('click', () => {
    if (usersPage < usersPages) { usersPage += 1; loadUsers(); }
  });
  byId('media-prev').addEventListener('click', () => {
    if (mediaPage > 1) { mediaPage -= 1; loadMedia(); }
  });
  byId('media-next').addEventListener('click', () => {
    if (mediaPage < mediaPages) { mediaPage += 1; loadMedia(); }
  });
  document.querySelectorAll('[data-feature]').forEach(button => {
    button.addEventListener('click', () => {
      if (button.dataset.feature === 'users') {
        openUsers();
        setNotice('User directory opened with read-only access.', 'success');
        return;
      }
      if (button.dataset.feature === 'media') {
        openMedia();
        setNotice('Media inventory opened with read-only metadata access.', 'success');
        return;
      }
      openSettings();
      setNotice('Current bot configuration opened in read-only mode.', 'success');
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
