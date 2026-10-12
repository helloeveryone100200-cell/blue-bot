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

  function openTelegramLink(url) {
    if (!url) return;
    if (webApp && typeof webApp.openTelegramLink === 'function') webApp.openTelegramLink(url);
    else if (webApp && typeof webApp.openLink === 'function') webApp.openLink(url);
  }

  byId('refresh-button').addEventListener('click', loadProfile);
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
