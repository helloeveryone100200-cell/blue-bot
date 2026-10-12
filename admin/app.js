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
  const ownerControlsView = byId('owner-controls-view');
  const settingsList = byId('settings-list');
  let usersPage = 1;
  let usersPages = 1;
  let mediaPage = 1;
  let mediaPages = 1;
  let userSearchTimer = null;
  let mediaSearchTimer = null;
  let overviewRequest = 0;
  let activeView = 'overview';
  let usersRequest = 0;
  let mediaRequest = 0;
  let settingsRequest = 0;
  let ownerStatsRequest = 0;
  let userDetailRequest = 0;


  function setupOwnerControlSections() {
    if (!ownerControlsView || ownerControlsView.dataset.sectionsReady === 'true') return;
    ownerControlsView.dataset.sectionsReady = 'true';

    const backButton = byId('back-from-owner-controls');
    const heading = ownerControlsView.querySelector(':scope > .section-heading');
    const intro = ownerControlsView.querySelector(':scope > .controls-intro');
    const cards = Array.from(ownerControlsView.querySelectorAll(':scope > .control-card'));
    if (!heading || !intro || cards.length === 0) return;

    const definitions = [
      {id: 'overview', label: 'Overview', description: 'Statistics and system snapshot', titles: ['Owner overview']},
      {id: 'appearance', label: 'Appearance', description: 'User dashboard visual settings', titles: ['Background image']},
      {id: 'bot-setup', label: 'Bot setup', description: 'Channels, groups and automation', titles: ['Auto broadcast new videos', 'Channel join requirement', 'Admin group configuration']},
      {id: 'users-messaging', label: 'Users & messaging', description: 'Account actions and broadcasts', titles: ['Account actions', 'Send a message']},
      {id: 'media-tools', label: 'Media tools', description: 'Media records, thumbnails and links', titles: ['Delete media or manage thumbnails']}
    ];

    const navigation = document.createElement('div');
    navigation.className = 'control-section-nav';
    navigation.setAttribute('role', 'tablist');
    navigation.setAttribute('aria-label', 'Owner control categories');

    const panelHost = document.createElement('div');
    panelHost.className = 'control-section-panels';

    const panels = new Map();
    definitions.forEach((definition, index) => {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'control-section-tab';
      tab.id = 'control-tab-' + definition.id;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', 'control-panel-' + definition.id);
      tab.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
      tab.tabIndex = index === 0 ? 0 : -1;
      tab.innerHTML = '<span class="control-tab-title"></span><span class="control-tab-description"></span>';
      tab.querySelector('.control-tab-title').textContent = definition.label;
      tab.querySelector('.control-tab-description').textContent = definition.description;
      navigation.append(tab);

      const panel = document.createElement('div');
      panel.className = 'control-section-panel';
      panel.id = 'control-panel-' + definition.id;
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', tab.id);
      panel.hidden = index !== 0;
      panelHost.append(panel);
      panels.set(definition.id, panel);

      const activate = () => {
        definitions.forEach(item => {
          const selected = item.id === definition.id;
          const itemTab = byId('control-tab-' + item.id);
          const itemPanel = byId('control-panel-' + item.id);
          if (itemTab) {
            itemTab.setAttribute('aria-selected', selected ? 'true' : 'false');
            itemTab.tabIndex = selected ? 0 : -1;
          }
          if (itemPanel) itemPanel.hidden = !selected;
        });
      };
      tab.addEventListener('click', activate);
      tab.addEventListener('keydown', event => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight' && event.key !== 'Home' && event.key !== 'End') return;
        event.preventDefault();
        const current = definitions.findIndex(item => item.id === definition.id);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? definitions.length - 1
          : (current + (event.key === 'ArrowRight' ? 1 : definitions.length - 1)) % definitions.length;
        const nextTab = byId('control-tab-' + definitions[next].id);
        if (nextTab) { nextTab.click(); nextTab.focus(); }
      });
    });

    cards.forEach(card => {
      const title = card.querySelector('h3')?.textContent.trim();
      const definition = definitions.find(item => item.titles.includes(title));
      if (definition) panels.get(definition.id).append(card);
    });

    // Keep the existing controls intact; only reorganize their presentation.
    ownerControlsView.insertBefore(heading, intro);
    if (backButton) {
      ownerControlsView.insertBefore(navigation, intro.nextSibling);
    } else {
      ownerControlsView.insertBefore(navigation, intro.nextSibling);
    }
    ownerControlsView.insertBefore(panelHost, navigation.nextSibling);
  }

  setupOwnerControlSections();

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
    const requestId = ++overviewRequest;
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
      if (requestId !== overviewRequest || activeView !== 'overview') return;
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
      if (requestId !== overviewRequest || activeView !== 'overview') return;
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
      if (requestId !== usersRequest || activeView !== 'users') return;
      usersPages = Math.max(1, Number(payload.pages) || 1);
      usersPage = Math.min(Math.max(1, Number(payload.page) || 1), usersPages);
      byId('user-total').textContent = formatCount(payload.total) + ' users';
      byId('users-page-label').textContent = 'Page ' + usersPage + ' of ' + usersPages;
      byId('users-prev').disabled = usersPage <= 1;
      byId('users-next').disabled = usersPage >= usersPages;
      byId('user-list-status').textContent = formatCount(payload.total) + ' matching users · read-only';
      renderUsers(payload.items);
    } catch (error) {
      if (requestId !== usersRequest || activeView !== 'users') return;
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
      if (requestId !== mediaRequest || activeView !== 'media') return;
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
      if (requestId !== settingsRequest || activeView !== 'settings') return;
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
      byId('auto-broadcast-toggle').checked = Boolean(payload.auto_broadcast_new_video);
      byId('auto-broadcast-state').textContent = payload.auto_broadcast_new_video
        ? 'Currently enabled · new public videos trigger notifications.'
        : 'Currently disabled · new public videos will not trigger notifications.';
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

  const actionErrors = {
    invalid_action: 'That action is not supported.',
    invalid_user_id: 'Enter a valid numeric Telegram user ID.',
    user_not_found: 'The user was not found in the database.',
    cannot_ban_owner: 'An owner account cannot be banned.',
    invalid_channel_link: 'Enter a valid public Telegram channel link or @username.',
    channel_validation_failed: 'Could not verify the channel. Check the link and bot access.',
    bot_must_be_channel_admin: 'The bot must be an administrator in that channel.',
    not_a_channel: 'The supplied link does not point to a channel.',
    group_not_found: 'Could not find that group. Ensure the bot has access to it.',
    bot_not_in_group: 'Add the bot to that group before setting it as a media group.',
    too_many_broadcast_jobs: 'Too many broadcasts are running. Wait for an existing broadcast to finish.',
    invalid_enabled_value: 'Choose a valid auto-broadcast setting.',
    target_is_not_group: 'That chat is not a group or supergroup.',
    invalid_group_id: 'Enter a group ID or public @username.',
    invalid_media_id: 'Enter a valid media ID for the selected action.',
    invalid_media_target: 'Select a valid media type and ID.',
    media_not_found: 'That media record was not found.',
    invalid_thumbnail_file_id: 'Enter a valid Telegram photo file_id.',
    invalid_broadcast_message: 'Enter a message of 1–4000 characters.',
    broadcast_job_not_found: 'Broadcast status is no longer available. It may have expired after a restart.',
    owner_access_denied: 'Owner authorization failed. Reopen the Mini App from your owner Telegram account.'
  };

  function actionErrorMessage(error) {
    if (error && error.status === 403) return 'Owner access denied. Reopen this Mini App from the authorized Telegram account.';
    return actionErrors[error && error.message] || 'The action could not be completed. Please check the values and try again.';
  }

  async function runOwnerAction(payload, successMessage) {
    try {
      const result = await postOwnerApi('/admin/api/action', payload);
      if (successMessage) setNotice(successMessage, 'success');
      return result;
    } catch (error) {
      setNotice(actionErrorMessage(error), 'error');
      throw error;
    }
  }

  function renderOwnerStats(payload) {
    const container = byId('owner-stats');
    container.replaceChildren();
    const metrics = [
      ['Total users', payload.users], ['Banned users', payload.bannedUsers],
      ['Total shares', payload.shares], ['Public videos', payload.publicVideos],
      ['Public photos', payload.publicPhotos], ['Private videos', payload.privateVideos],
      ['Private photos', payload.privatePhotos], ['Auto broadcast', payload.autoBroadcast ? 'ON' : 'OFF']
    ];
    metrics.forEach(([label, value]) => {
      const item = makeElement('div', 'owner-stat');
      item.append(makeElement('small', '', label), makeElement('strong', '', typeof value === 'number' ? formatCount(value) : String(value)));
      container.append(item);
    });
    byId('auto-broadcast-toggle').checked = Boolean(payload.autoBroadcast);
    byId('auto-broadcast-state').textContent = payload.autoBroadcast
      ? 'Currently enabled · new public videos trigger notifications.'
      : 'Currently disabled · new public videos will not trigger notifications.';
  }

  async function loadOwnerStats() {
    const requestId = ++ownerStatsRequest;
    byId('owner-stats').replaceChildren(makeElement('p', 'list-status', 'Loading owner statistics…'));
    try {
      const payload = await runOwnerAction({action: 'panel_stats'});
      if (requestId !== ownerStatsRequest || activeView !== 'owner-controls') return;
      renderOwnerStats(payload);
      const settingsPayload = await postOwnerApi('/admin/api/settings');
      if (requestId !== ownerStatsRequest || activeView !== 'owner-controls') return;
      const channel = settingsPayload.channel_gate;
      byId('channel-link').placeholder = channel && channel.enabled
        ? 'Current channel: ' + (channel.title || 'configured') + ' · enter new link to replace'
        : 'https://t.me/your_channel';
    } catch (_error) {
      if (requestId !== ownerStatsRequest || activeView !== 'owner-controls') return;
      byId('owner-stats').replaceChildren(makeElement('p', 'list-status', 'Unable to load owner statistics.'));
    }
  }

  async function pollBroadcast(jobId, attempts = 0) {
    if (attempts >= 120) {
      byId('broadcast-status').textContent = 'Broadcast is still running. Reopen this panel to check status.';
      return;
    }
    try {
      const job = await postOwnerApi('/admin/api/action', {action: 'broadcast_status', jobId});
      byId('broadcast-status').textContent = 'Status: ' + job.status + ' · sent ' + formatCount(job.sent) +
        ' / ' + formatCount(job.total) + ' · failed ' + formatCount(job.failed);
      if (job.status === 'completed') {
        setNotice('Broadcast finished. Sent: ' + formatCount(job.sent) + ', failed: ' + formatCount(job.failed) + '.', job.failed ? 'info' : 'success');
        return;
      }
      setTimeout(() => pollBroadcast(jobId, attempts + 1), 1500);
    } catch (_error) {
      byId('broadcast-status').textContent = 'Could not retrieve progress. The bot may have restarted.';
    }
  }

  function activateView(view) {
    activeView = view;
    // Invalidate overview requests so a late response cannot overwrite another section's notice.
    overviewRequest += 1;
  }

  function invalidateUserDetailView() {
    // Invalidate outstanding detail requests whenever navigation leaves the detail view.
    userDetailRequest += 1;
    const detailPanel = byId('user-detail-panel');
    if (detailPanel) detailPanel.remove();
    userList.hidden = false;
    byId('user-list-status').hidden = false;
    byId('user-total').hidden = false;
    byId('user-search-label').hidden = false;
    byId('user-search').hidden = false;
    byId('user-pagination').hidden = false;
  }

  function openUsers() {
    activateView('users');
    invalidateUserDetailView();
    userList.hidden = false;
    byId('user-list-status').hidden = false;
    byId('user-total').hidden = false;
    byId('user-search-label').hidden = false;
    byId('user-search').hidden = false;
    byId('user-pagination').hidden = false;
    overviewView.hidden = true;
    mediaView.hidden = true;
    settingsView.hidden = true;
    ownerControlsView.hidden = true;
    usersView.hidden = false;
    usersPage = 1;
    loadUsers();
  }

  function openMedia() {
    activateView('media');
    invalidateUserDetailView();
    overviewView.hidden = true;
    usersView.hidden = true;
    settingsView.hidden = true;
    ownerControlsView.hidden = true;
    mediaView.hidden = false;
    mediaPage = 1;
    loadMedia();
  }

  function openSettings() {
    activateView('settings');
    invalidateUserDetailView();
    overviewView.hidden = true;
    usersView.hidden = true;
    mediaView.hidden = true;
    ownerControlsView.hidden = true;
    settingsView.hidden = false;
    loadSettings();
  }

  function openOwnerControls() {
    activateView('owner-controls');
    invalidateUserDetailView();
    overviewView.hidden = true;
    usersView.hidden = true;
    mediaView.hidden = true;
    settingsView.hidden = true;
    ownerControlsView.hidden = false;
    loadOwnerStats();
  }

  function showOverview() {
    activateView('overview');
    invalidateUserDetailView();
    usersView.hidden = true;
    mediaView.hidden = true;
    settingsView.hidden = true;
    ownerControlsView.hidden = true;
    overviewView.hidden = false;
  }

  byId('refresh-button').addEventListener('click', loadOverview);
  byId('back-to-overview').addEventListener('click', showOverview);
  byId('back-from-media').addEventListener('click', showOverview);
  byId('back-from-settings').addEventListener('click', showOverview);
  byId('back-from-owner-controls').addEventListener('click', showOverview);
  byId('load-owner-stats').addEventListener('click', loadOwnerStats);
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
  byId('save-auto-broadcast').addEventListener('click', async () => {
    try {
      const result = await runOwnerAction({action: 'set_auto_broadcast', enabled: byId('auto-broadcast-toggle').checked}, 'Auto broadcast setting updated.');
      byId('auto-broadcast-toggle').checked = Boolean(result.enabled);
      byId('auto-broadcast-state').textContent = result.enabled ? 'Currently enabled.' : 'Currently disabled.';
      loadOwnerStats();
    } catch (_error) {}
  });

  byId('save-channel').addEventListener('click', async () => {
    const channelLink = byId('channel-link').value.trim();
    try {
      const result = await runOwnerAction({action: 'set_required_channel', channelLink}, 'Required channel configured successfully.');
      byId('channel-link').value = '';
      byId('channel-link').placeholder = 'Current channel: ' + (result.channel || result.link);
    } catch (_error) {}
  });

  byId('remove-channel').addEventListener('click', async () => {
    if (!window.confirm('Remove the required-channel join gate?')) return;
    try {
      await runOwnerAction({action: 'remove_required_channel'}, 'Required channel setting removed.');
      byId('channel-link').placeholder = 'No required channel is configured';
    } catch (_error) {}
  });

  byId('save-admin-group').addEventListener('click', async () => {
    const groupId = byId('admin-group-id').value.trim();
    const action = byId('admin-group-type').value === 'private' ? 'set_private_admin_group' : 'set_public_admin_group';
    try {
      const result = await runOwnerAction({action, groupId}, (action === 'set_private_admin_group' ? 'Private' : 'Public') + ' media group set to ' + resultSafeName(groupId) + '.');
      byId('admin-group-id').value = '';
      setNotice('Admin group configured: ' + (result.groupName || result.groupId), 'success');
      loadOwnerStats();
    } catch (_error) {}
  });

  function resultSafeName(value) {
    return String(value || '').slice(0, 80);
  }

  byId('run-user-action').addEventListener('click', async () => {
    const userId = byId('owner-user-id').value.trim();
    const action = byId('owner-user-action').value;
    if (!/^[0-9]{1,20}$/.test(userId)) {
      setNotice('Enter a valid numeric Telegram user ID.', 'error');
      return;
    }
    const destructive = action === 'ban_user' || action === 'revoke_private_access';
    if (destructive && !window.confirm('Confirm ' + byId('owner-user-action').selectedOptions[0].textContent + ' for user ' + userId + '?')) return;
    try {
      const result = await runOwnerAction({action, userId}, 'User action completed for ID ' + resultSafeName(userId) + '.');
      setNotice('User ' + result.userId + ': ' + (result.banned === true ? 'banned' : result.banned === false ? 'unbanned' : result.access ? 'private access granted' : 'private access revoked') + '.', 'success');
    } catch (_error) {}
  });

  byId('start-broadcast').addEventListener('click', async () => {
    const targetText = byId('broadcast-target').value.trim().toLowerCase();
    const message = byId('broadcast-message').value;
    if (!byId('broadcast-confirm').checked) {
      setNotice('Confirm the broadcast before sending.', 'error');
      return;
    }
    if (!targetText || (targetText !== 'all' && !/^[0-9]{1,20}$/.test(targetText))) {
      setNotice('Recipient must be "all" or an exact numeric user ID.', 'error');
      return;
    }
    if (!message.trim()) {
      setNotice('Enter a message before starting the broadcast.', 'error');
      return;
    }
    if (!window.confirm('Start sending this message to ' + (targetText === 'all' ? 'all registered users' : 'user ' + targetText) + '?')) return;
    byId('start-broadcast').disabled = true;
    byId('broadcast-status').textContent = 'Starting broadcast…';
    try {
      const result = await runOwnerAction({action: 'broadcast_start', target: targetText, message}, 'Broadcast job started.');
      byId('broadcast-confirm').checked = false;
      byId('broadcast-status').textContent = 'Queued for ' + formatCount(result.total) + ' recipient(s).';
      pollBroadcast(result.jobId);
    } catch (_error) {
      byId('broadcast-status').textContent = 'Broadcast could not be started.';
    } finally {
      byId('start-broadcast').disabled = false;
    }
  });

  byId('delete-media').addEventListener('click', async () => {
    const mediaId = byId('owner-media-id').value.trim();
    const kind = byId('owner-media-kind').value;
    if (!mediaId) { setNotice('Enter a media ID.', 'error'); return; }
    if (!window.confirm('Permanently delete media record ' + mediaId + '? This cannot be undone.')) return;
    try {
      await runOwnerAction({action: 'delete_media', kind, mediaId}, 'Media ' + mediaId + ' deleted.');
      byId('owner-media-id').value = '';
      loadOwnerStats();
    } catch (_error) {}
  });

  byId('set-thumbnail').addEventListener('click', async () => {
    const mediaId = byId('owner-media-id').value.trim();
    const fileId = byId('owner-thumbnail-file-id').value.trim();
    try {
      await runOwnerAction({action: 'set_thumbnail', mediaId, fileId}, 'Thumbnail set for ' + mediaId + '.');
      byId('owner-thumbnail-file-id').value = '';
    } catch (_error) {}
  });

  byId('remove-thumbnail').addEventListener('click', async () => {
    const mediaId = byId('owner-media-id').value.trim();
    if (!mediaId) { setNotice('Enter a video ID (vN or zN).', 'error'); return; }
    if (!window.confirm('Remove the thumbnail from ' + mediaId + '?')) return;
    try {
      await runOwnerAction({action: 'remove_thumbnail', mediaId}, 'Thumbnail removed from ' + mediaId + '.');
    } catch (_error) {}
  });

  byId('create-referral-link').addEventListener('click', async () => {
    const mediaId = byId('owner-media-id').value.trim();
    try {
      const result = await runOwnerAction({action: 'create_referral_link', mediaId}, 'Referral link created.');
      byId('referral-result').replaceChildren();
      const link = makeElement('a', 'referral-link', result.link);
      link.href = result.link;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      const copy = makeElement('button', 'secondary-button', 'Copy link');
      copy.type = 'button';
      copy.addEventListener('click', async () => {
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(result.link);
            setNotice('Referral link copied.', 'success');
          } else {
            setNotice('Open the referral link to copy it manually.', 'info');
          }
        } catch (_error) {
          setNotice('Unable to copy link automatically.', 'error');
        }
      });
      byId('referral-result').append(link, copy);
    } catch (_error) {}
  });

  let backgroundPreviewUrl = '';
  const backgroundFileInput = byId('background-image-file');
  const backgroundPreview = byId('background-preview');
  const backgroundPreviewWrap = byId('background-preview-wrap');
  const backgroundUploadButton = byId('upload-background');
  const backgroundStatus = byId('background-upload-status');

  backgroundFileInput.addEventListener('change', () => {
    const file = backgroundFileInput.files && backgroundFileInput.files[0];
    backgroundUploadButton.disabled = !file;
    if (backgroundPreviewUrl) URL.revokeObjectURL(backgroundPreviewUrl);
    backgroundPreviewUrl = '';
    if (!file) {
      backgroundPreviewWrap.hidden = true;
      backgroundPreview.removeAttribute('src');
      return;
    }
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 2500000) {
      backgroundFileInput.value = '';
      backgroundUploadButton.disabled = true;
      backgroundPreviewWrap.hidden = true;
      backgroundStatus.textContent = 'Choose a PNG, JPEG, or WebP image no larger than 2.5 MB.';
      setNotice('Invalid background image. Use PNG, JPEG, or WebP up to 2.5 MB.', 'error');
      return;
    }
    backgroundPreviewUrl = URL.createObjectURL(file);
    backgroundPreview.src = backgroundPreviewUrl;
    backgroundPreviewWrap.hidden = false;
    backgroundStatus.textContent = 'Preview ready. Upload to apply this image to all users.';
  });

  backgroundUploadButton.addEventListener('click', async () => {
    const file = backgroundFileInput.files && backgroundFileInput.files[0];
    if (!file) return;
    if (!window.confirm('Apply this image as the background for every User Dashboard?')) return;
    backgroundUploadButton.disabled = true;
    backgroundStatus.textContent = 'Uploading background image…';
    try {
      const imageData = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('image_read_failed'));
        reader.onerror = () => reject(new Error('image_read_failed'));
        reader.readAsDataURL(file);
      });
      await postOwnerApi('/admin/api/background', {action: 'upload', imageData});
      backgroundStatus.textContent = 'Background uploaded and applied to the User Dashboard.';
      setNotice('User Dashboard background updated successfully.', 'success');
      backgroundFileInput.value = '';
    } catch (error) {
      const messages = {
        image_size_limit: 'The image exceeds the 2.5 MB limit.',
        invalid_image: 'The uploaded file is not a supported image.',
        image_type_mismatch: 'The image content does not match its file type.',
        telegram_owner_authentication_failed: 'Owner authentication failed. Reopen the Mini App from Telegram.'
      };
      backgroundStatus.textContent = messages[error.message] || 'Upload failed. Please try again.';
      setNotice(backgroundStatus.textContent, 'error');
    } finally {
      backgroundUploadButton.disabled = !backgroundFileInput.files || !backgroundFileInput.files[0];
    }
  });

  byId('remove-background').addEventListener('click', async () => {
    if (!window.confirm('Remove the uploaded background and restore the default User Dashboard design?')) return;
    const button = byId('remove-background');
    button.disabled = true;
    backgroundStatus.textContent = 'Restoring default background…';
    try {
      await postOwnerApi('/admin/api/background', {action: 'remove'});
      backgroundStatus.textContent = 'Custom background removed. The default design is restored.';
      setNotice('Default User Dashboard background restored.', 'success');
    } catch (_error) {
      backgroundStatus.textContent = 'Could not remove the background. Please try again.';
      setNotice(backgroundStatus.textContent, 'error');
    } finally {
      button.disabled = false;
    }
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
      if (button.dataset.feature === 'owner-controls') {
        openOwnerControls();
        setNotice('Owner controls opened. Write actions require Telegram owner authentication.', 'success');
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
