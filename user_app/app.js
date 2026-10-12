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
  let savedVideoIds = new Set();
  let currentVideoItems = [];
  let savedVideoRequestId = 0;
  let profileIsRestricted = false;

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
      byId('referral-link').value = botUrl;
      byId('referral-success-count').textContent = safeCount(profile.shares);
      byId('copy-referral-link').disabled = !botUrl;
      byId('share-referral-link').disabled = !botUrl;
      byId('referral-notice').textContent = botUrl
        ? 'Share this link with friends. Successful new-user referrals are counted by Blue Bot.'
        : 'Your referral link is temporarily unavailable.';
      setNotice(profile.is_banned
        ? 'Your account is currently restricted. Please contact the bot owner if you believe this is a mistake.'
        : 'Your account is connected securely. This dashboard only displays your own account information.', profile.is_banned ? 'error' : 'success');
      profileIsRestricted = profile.is_banned === true;
      if (profileIsRestricted) {
        clearVideoLibrary('Your account is restricted. Public videos are unavailable.');
        savedVideoIds = new Set();
        currentVideoItems = [];
        renderVideos([], 'saved-video-grid');
        byId('saved-video-count').textContent = '0 saved';
        byId('saved-video-notice').textContent = 'Saved videos are unavailable for restricted accounts.';
        byId('saved-video-notice').dataset.state = 'error';
      } else {
        videoPage = 1;
        await loadSavedVideos();
        loadVideos();
      }
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

  function renderVideos(items, gridId = 'video-grid') {
    const grid = byId(gridId);
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
      const isSaved = savedVideoIds.has(video.id);
      const save = document.createElement('button');
      save.type = 'button';
      save.className = 'bookmark-button';
      save.textContent = gridId === 'saved-video-grid' ? 'Remove saved' : (isSaved ? '✓ Saved' : '＋ Save video');
      save.disabled = profileIsRestricted;
      save.setAttribute('aria-pressed', String(isSaved));
      save.addEventListener('click', () => toggleSavedVideo(video.id, !isSaved));
      details.append(id, title, stats, watch, save);
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
      currentVideoItems = items;
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
      currentVideoItems = [];
      byId('video-grid').replaceChildren();
      byId('video-pagination').hidden = true;
    } finally {
      if (currentRequest === videoRequestId) byId('video-search-button').disabled = false;
    }
  }

  async function loadSavedVideos() {
    const currentRequest = ++savedVideoRequestId;
    const signedData = initData();
    const notice = byId('saved-video-notice');
    if (!signedData || profileIsRestricted) return;
    notice.textContent = 'Loading your saved videos…';
    notice.dataset.state = 'info';
    try {
      const response = await fetch('/app/api/saved-videos', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({initData: signedData, action: 'list'}),
        cache: 'no-store',
        credentials: 'omit'
      });
      let payload;
      try { payload = await response.json(); } catch (_error) { throw new Error('invalid_response'); }
      if (currentRequest !== savedVideoRequestId) return;
      if (!response.ok) throw new Error(payload && payload.error ? payload.error : 'saved_videos_unavailable');
      const ids = Array.isArray(payload.savedIds) ? payload.savedIds : [];
      savedVideoIds = new Set(ids.filter(id => typeof id === 'string' && /^v[0-9]+$/.test(id)));
      const items = Array.isArray(payload.items) ? payload.items : [];
      byId('saved-video-count').textContent = safeCount(items.length) + ' saved';
      renderVideos(items, 'saved-video-grid');
      notice.textContent = items.length
        ? 'Your saved videos are private to your account.'
        : 'No saved videos yet. Use “Save video” in the public library to add one.';
      notice.dataset.state = items.length ? 'success' : 'info';
      renderVideos(currentVideoItems);
    } catch (error) {
      if (currentRequest !== savedVideoRequestId) return;
      notice.textContent = error.message === 'account_restricted'
        ? 'Saved videos are unavailable for restricted accounts.'
        : 'Could not load saved videos. Please try again.';
      notice.dataset.state = 'error';
    }
  }

  async function toggleSavedVideo(videoId, shouldSave) {
    if (profileIsRestricted || typeof videoId !== 'string' || !/^v[0-9]+$/.test(videoId)) return;
    const signedData = initData();
    if (!signedData) return;
    const notice = byId('saved-video-notice');
    notice.textContent = shouldSave ? 'Saving video…' : 'Removing saved video…';
    notice.dataset.state = 'info';
    try {
      const response = await fetch('/app/api/saved-videos', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({initData: signedData, action: shouldSave ? 'save' : 'remove', videoId}),
        cache: 'no-store',
        credentials: 'omit'
      });
      let payload;
      try { payload = await response.json(); } catch (_error) { throw new Error('invalid_response'); }
      if (!response.ok) throw new Error(payload && payload.error ? payload.error : 'saved_video_update_failed');
      await loadSavedVideos();
      renderVideos(currentVideoItems);
      notice.textContent = shouldSave ? 'Video saved to your collection.' : 'Video removed from your saved collection.';
      notice.dataset.state = 'success';
    } catch (error) {
      const messages = {
        saved_videos_limit: 'Your collection is full. Remove a saved video before adding another (maximum 100).',
        media_not_found: 'This video is no longer available in the public library.',
        account_restricted: 'Your account is restricted. Saved videos are unavailable.'
      };
      notice.textContent = messages[error.message] || 'Could not update your saved videos. Please try again.';
      notice.dataset.state = 'error';
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
  byId('share-referral-link').addEventListener('click', () => {
    if (!botUrl) return;
    openTelegramLink('https://t.me/share/url?url=' + encodeURIComponent(botUrl));
  });
  byId('copy-referral-link').addEventListener('click', async () => {
    if (!botUrl) return;
    const button = byId('copy-referral-link');
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(botUrl);
      } else {
        const field = byId('referral-link');
        field.focus();
        field.select();
        if (!document.execCommand('copy')) throw new Error('copy_unavailable');
      }
      byId('referral-notice').textContent = 'Referral link copied. Share it with a friend to invite them to Blue Bot.';
      byId('referral-notice').dataset.state = 'success';
      button.textContent = 'Copied';
    } catch (_error) {
      const field = byId('referral-link');
      field.focus();
      field.select();
      byId('referral-notice').textContent = 'Copy is unavailable here. Select the link above and copy it manually.';
      byId('referral-notice').dataset.state = 'error';
    }
  });

  async function loadDashboardBackground() {
    try {
      const response = await fetch('/app/api/background', {
        method: 'GET',
        headers: {'Accept': 'application/json'},
        cache: 'no-store',
        credentials: 'omit'
      });
      if (!response.ok) return;
      const payload = await response.json();
      if (typeof payload.imageData === 'string' &&
          /^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(payload.imageData)) {
        document.documentElement.style.setProperty('--user-dashboard-background-image', 'url("' + payload.imageData + '")');
        document.body.classList.add('has-custom-dashboard-background');
      }
    } catch (_error) {
      // Keep the built-in background if the optional custom image is unavailable.
    }
  }

  if (webApp && typeof webApp.initData === 'string' && webApp.initData) {
    document.body.classList.add('telegram-ready');
    if (typeof webApp.ready === 'function') webApp.ready();
    if (typeof webApp.expand === 'function') webApp.expand();
    loadDashboardBackground();
    loadProfile();
  }
})();
