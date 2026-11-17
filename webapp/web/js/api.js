/* Lớp gọi API: chọn server giả hoặc server thật theo GV_CONFIG.USE_MOCK.
   Mọi lỗi đều ném ra đối tượng { status, code, message } (message bằng tiếng Việt). */
(function () {
  const cfg = window.GV_CONFIG;

  async function realRequest(method, path, opt = {}) {
    const entries = Object.entries(opt.query || {}).filter(([, v]) => v !== '' && v != null);
    const qs = entries.length ? '?' + new URLSearchParams(entries) : '';
    let res;
    try {
      res = await fetch(cfg.API_BASE + path + qs, {
        method, credentials: 'same-origin',
        headers: opt.body ? { 'Content-Type': 'application/json' } : {},
        body: opt.body ? JSON.stringify(opt.body) : undefined
      });
    } catch (_) {
      throw { status: 0, code: 'NETWORK', message: 'Không kết nối được máy chủ.' };
    }
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const e = (data && data.error) || {};
      throw { status: res.status, code: e.code || 'ERROR', message: e.message || 'Có lỗi xảy ra.' };
    }
    return data;
  }

  function realWS(h) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    let ws;
    try { ws = new WebSocket(proto + '://' + location.host + cfg.WS_PATH); }
    catch (_) { setTimeout(h.onclose, 0); return { close() {} }; }
    ws.onopen = h.onopen;
    ws.onclose = h.onclose;
    ws.onmessage = e => { try { h.onmessage(JSON.parse(e.data)); } catch (_) {} };
    return { close() { try { ws.close(); } catch (_) {} } };
  }

  window.GV_API = cfg.USE_MOCK
    ? { request: window.GV_MOCK.request, connectWS: window.GV_MOCK.connectWS, sim: window.GV_MOCK.sim, idleFrame: window.GV_MOCK.idleFrame }
    : { request: realRequest, connectWS: realWS, idleFrame: cfg.DEV_TOOLS ? '/media/idle.svg' : '',
        sim: kind => cfg.DEV_TOOLS ? fetch('/dev/sim/' + kind, { method: 'POST', credentials: 'same-origin' }).catch(() => {}) : Promise.resolve() };
})();
