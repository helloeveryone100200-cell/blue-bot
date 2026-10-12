(() => {
  const webApp = window.Telegram && window.Telegram.WebApp;
  const byId = id => document.getElementById(id);
  const notice = byId('notice');
  let botUrl = '';
  let requestId = 0;
  let videoRequestId = 0;
  let videoPage = 1;
  let videoPages = 1;
  let videoQuery = '';

  function setNotice(message, state) {
    notice.textContent = message;
    notice.dataset.state = state || 'info';
  }

  function safeCount(value) {
    return Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString() : '—';
  }

  function initData() {
    return webApp && typeof webApp.initData === 'string' ? webApp.initData : '';
  }

  async function loadProfile() {
    const currentRequest = ++requestId;
    const signedData = initData();
    if (!signedData) {
      setNotice('Please open this page from the Blue Bot Telegram Mini App button.', 'error');
      return;
    }
    byId('refresh-button').disabled = true;
    setNotice('Verifying your Telegram account…');
    try {
      const response = await fetch('/app/api/profile', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({initData: signedData}),
        cache: 'no-store',
        credentials: 'omit'
      });
      let payload;
      try { payload = await response.json(); } catch (_error) { throw new Error('invalid_response'); }
      if (currentRequest !== requestId) return;
      if (!response.ok) throw new Error(payload && payload.error ? payload.error : 'profile_unavailable');
      const profile = payload.profile || {};
      const name = profile.first_name || profile.username || 'Blue Bot User';
      byId('greeting').textContent = 'Welcome, ' + name;
      byId('profile-name').textContent = name;
      byId('profile-username').textContent = profile.username ? '@' + profile.username : 'Telegram account';
      byId('profile-id').textContent = profile.id || '—';
      byId('avatar').textContent = Array.from(name.trim())[0]?.toUpperCase() || 'B';
      byId('metric-shares').textContent = safeCount(profile.shares);
      byId('metric-videos').textContent = safeCount(payload.library && payload.library.public_videos);
      byId('metric-photos').textContent = safeCount(payload.library && payload.library.public_photos);
      byId('metric-private').textContent = profile.private_access ? 'Granted' : 'Standard';
      const status = byId('account-status');
      status.textContent = profile.is_banned ? 'Restricted' : 'Active';
      status.dataset.state = profile.is_banned ? 'banned' : 'active';
      botUrl = typeof payload.bot_url === 'string' ? payload.bot_url : '';
      byId('open-bot').disabled = !botUrl;
      byId('share-bot').disabled = !botUrl;
      setNotice(profile.is_banned
        ? 'Your account is currently restricted. Please contact the bot owner if you believe this is a mistake.'
        : 'Your account is connected securely. This dashboard only displays your own account information.', profile.is_banned ? 'error' : 'success');
      if (profile.is_banned) clearVideoLibrary('Your account is restricted. Public videos are unavailable.');
      else { videoPage = 1; loadVideos(); }
    } catch (error) {
      if (currentRequest !== requestId) return;
      const messages = {
        telegram_authentication_failed: 'Telegram could not verify this session. Close the app and reopen it from Blue Bot.',
        user_not_found: 'Please send /start to Blue Bot first, then reopen your dashboard.',
        profile_unavailable: 'Your profile is temporarily unavailable. Please try again.',
        invalid_response: 'The server returned an unexpected response. Please try again.'
      };
      setNotice(messages[error.message] || 'Could not load your profile. Please try again later.', 'error');
    } finally {
      if (currentRequest === requestId) byId('refresh-button').disabled = false;
    }
  }

  function clearVideoLibrary(message) {
    byId('video-grid').replaceChildren();
    byId('video-pagination').hidden = true;
    byId('video-total').textContent = '— videos';
    byId('video-notice').textContent = message;
    byId('video-notice').dataset.state = 'error';
  }

  function renderVideos(items) {
    const grid = byId('video-grid');
    grid.replaceChildren();
    items.forEach(video => {
      const card = document.createElement('article');
      card.className = 'video-card';
      const art = document.createElement('div');
      art.className = 'video-art';
      art.setAttribute('aria-hidden', 'true');
      const play = document.createElement('span');
      play.textContent = '▶';
      art.appendChild(play);
      const details = document.createElement('div');
      details.className = 'video-details';
      const id = document.createElement('span');
      id.className = 'video-id';
      id.textContent = video.id;
      const title = document.createElement('h3');
      title.textContent = video.title;
      const stats = document.createElement('p');
      stats.className = 'video-stats';
      stats.textContent = safeCount(video.views) + ' views · ' + safeCount(video.likes) + ' likes';
      const watch = document.createElement('button');
      watch.type = 'button';
      watch.className = 'watch-button';
      watch.textContent = '▶  Watch in Telegram';
      watch.disabled = !video.watch_url;
      watch.addEventListener('click', () => openTelegramLink(video.watch_url));
      details.append(id, title, stats, watch);
      card.append(art, details);
      grid.appendChild(card);
    });
  }

  async function loadVideos() {
    const currentRequest = ++videoRequestId;
    const signedData = initData();
    const notice = byId('video-notice');
    if (!signedData) {
      clearVideoLibrary('Open this dashboard from the Blue Bot Telegram Mini App button.');
      return;
    }
    notice.textContent = 'Loading public videos…';
    notice.dataset.state = 'info';
    byId('video-search-button').disabled = true;
    try {
      const response = await fetch('/app/api/videos', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({initData: signedData, page: videoPage, pageSize: 12, query: videoQuery}),
        cache: 'no-store',
        credentials: 'omit'
      });
      let payload;
      try { payload = await response.json(); } catch (_error) { throw new Error('invalid_response'); }
      if (currentRequest !== videoRequestId) return;
      if (!response.ok) throw new Error(payload && payload.error ? payload.error : 'videos_unavailable');
      const items = Array.isArray(payload.items) ? payload.items : [];
      videoPage = Number.isSafeInteger(payload.page) && payload.page > 0 ? payload.page : 1;
      videoPages = Number.isSafeInteger(payload.pages) && payload.pages > 0 ? payload.pages : 1;
      byId('video-total').textContent = safeCount(payload.total) + ' videos';
      renderVideos(items);
      notice.textContent = items.length ? 'Showing public videos only.' : (videoQuery ? 'No public videos match your search.' : 'No public videos are available yet.');
      notice.dataset.state = items.length ? 'success' : 'info';
      byId('video-pagination').hidden = videoPages <= 1;
      byId('video-page-label').textContent = 'Page ' + videoPage + ' of ' + videoPages;
      byId('video-previous').disabled = videoPage <= 1;
      byId('video-next').disabled = videoPage >= videoPages;
    } catch (error) {
      if (currentRequest !== videoRequestId) return;
      const messages = {
        telegram_authentication_failed: 'Telegram could not verify this session. Reopen the dashboard from Blue Bot.',
        user_not_found: 'Please send /start to Blue Bot first, then reopen your dashboard.',
        account_restricted: 'Your account is restricted. Public videos are unavailable.',
        invalid_query: 'Search text is too long. Use 80 characters or fewer.',
        videos_unavailable: 'The public video library is temporarily unavailable. Please try again.',
        invalid_response: 'The server returned an unexpected response. Please try again.'
      };
      notice.textContent = messages[error.message] || 'Could not load public videos. Please try again later.';
      notice.dataset.state = 'error';
      byId('video-grid').replaceChildren();
      byId('video-pagination').hidden = true;
    } finally {
      if (currentRequest === videoRequestId) byId('video-search-button').disabled = false;
    }
  }

  function openTelegramLink(url) {
    if (!url) return;
    if (webApp && typeof webApp.openTelegramLink === 'function') webApp.openTelegramLink(url);
    else if (webApp && typeof webApp.openLink === 'function') webApp.openLink(url);
  }

  byId('refresh-button').addEventListener('click', loadProfile);
  byId('video-search-form').addEventListener('submit', event => {
    event.preventDefault();
    videoQuery = byId('video-search').value.trim().slice(0, 80);
    videoPage = 1;
    loadVideos();
  });
  byId('video-previous').addEventListener('click', () => {
    if (videoPage > 1) { videoPage -= 1; loadVideos(); }
  });
  byId('video-next').addEventListener('click', () => {
    if (videoPage < videoPages) { videoPage += 1; loadVideos(); }
  });
  byId('open-bot').addEventListener('click', () => openTelegramLink(botUrl));
  byId('share-bot').addEventListener('click', () => {
    if (!botUrl) return;
    openTelegramLink('https://t.me/share/url?url=' + encodeURIComponent(botUrl));
  });

  if (webApp && typeof webApp.initData === 'string' && webApp.initData) {
    document.body.classList.add('telegram-ready');
    if (typeof webApp.ready === 'function') webApp.ready();
    if (typeof webApp.expand === 'function') webApp.expand();
    loadProfile();
  }
})();
