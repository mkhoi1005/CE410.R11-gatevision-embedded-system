/* Server giả chạy trong trình duyệt, mô phỏng đúng API_CONTRACT_WEB.md.
   Chỉ dùng khi GV_CONFIG.USE_MOCK = true. Dữ liệu biển số là biển giả. */
(function () {
  const cfg = window.GV_CONFIG;
  if (!cfg.USE_MOCK) return;
  const CONF = { '0': 'O', 'O': '0', '1': 'I', 'I': '1', '8': 'B', 'B': '8', '5': 'S', 'S': '5' };
  const norm = p => String(p || '').toUpperCase().replace(/[\s.\-]/g, '');
  const iso = t => new Date(t).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const vnDate = t => new Intl.DateTimeFormat('sv-SE', { timeZone: cfg.TZ }).format(new Date(t));
  const rnd = (a, b) => a + Math.random() * (b - a);
  const pick = a => a[Math.floor(Math.random() * a.length)];
  const delay = ms => new Promise(r => setTimeout(r, ms));
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const uri = s => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(s);
  const fail = (status, code, message) => { throw { status, code, message }; };

  /* ---------- ảnh giả (hình học, không phải ảnh thật) ---------- */
  function parts(plate) {
    const m = String(plate).split('-');
    let b = m.slice(1).join('');
    if (/^\d{5}$/.test(b)) b = b.slice(0, 3) + '.' + b.slice(3);
    return [m[0], b];
  }
  function plateSVG(plate) {
    const [a, b] = parts(plate);
    const f = 'font-family="Consolas,Menlo,monospace" font-weight="700" text-anchor="middle" fill="#1d2a30"';
    return uri(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 190 140"><rect x="3" y="3" width="184" height="134" rx="10" fill="#fff" stroke="#1d2a30" stroke-width="5"/><text x="95" y="62" font-size="46" ${f}>${esc(a)}</text><text x="95" y="118" font-size="50" ${f}>${esc(b)}</text></svg>`);
  }
  function frameSVG(plate, seed) {
    const h = 190 + (seed * 37) % 50;
    let body;
    if (plate === 'IDLE') {
      body = `<text x="320" y="250" text-anchor="middle" font-size="22" fill="#9fb0b8" font-family="Segoe UI,Arial,sans-serif">Chưa có xe</text>`;
    } else if (plate) {
      const [a, b] = parts(plate);
      const f = 'font-family="Consolas,Menlo,monospace" font-weight="700" text-anchor="middle" fill="#1d2a30"';
      body = `<g transform="translate(225,215)"><rect x="3" y="3" width="184" height="134" rx="10" fill="#fff" stroke="#1d2a30" stroke-width="5"/><text x="95" y="62" font-size="46" ${f}>${esc(a)}</text><text x="95" y="118" font-size="50" ${f}>${esc(b)}</text></g>`;
    } else {
      body = `<g transform="translate(225,215)"><rect x="3" y="3" width="184" height="134" rx="10" fill="#c9d1d5" opacity=".55" stroke="#8fa0a8" stroke-width="5"/><text x="95" y="92" text-anchor="middle" font-size="44" fill="#6b7780" font-family="Segoe UI,Arial,sans-serif">?</text></g>`;
    }
    return uri(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="hsl(${h},14%,30%)"/><stop offset="1" stop-color="hsl(${h},14%,17%)"/></linearGradient></defs><rect width="640" height="480" fill="url(#g)"/><rect y="360" width="640" height="120" fill="#0f1a1e" opacity=".5"/>${body}</svg>`);
  }
  const IDLE = frameSVG('IDLE', 0);

  /* ---------- trạng thái ---------- */
  const PLATES = ['59X1-12345', '59C2-67890', '51F1-24680', '59B1-10805', '50Z1-11223', '59H1-45678', '61B1-33445', '72D1-90817', '59P3-13579', '52K1-77010'];
  const S = {
    nextEvent: 1, nextSession: 1, nextAlert: 1, nextUser: 3, bootAt: Date.now(), wsUp: true, fails: 0,
    cur: null, users: [
      { id: 1, username: 'admin', display_name: 'Quản trị', role: 'admin', must_change_password: true, password: 'admin123' },
      { id: 2, username: 'truc1', display_name: 'Nhân viên trực 1', role: 'staff', must_change_password: false, password: 'truc1234' }
    ],
    events: [], sessions: [], alerts: [], timers: {}, listeners: new Set(),
    devices: [
      { device_id: 'cam-a', gate: 'IN', ip: '192.168.4.11', rssi: -58, state: 'IDLE', online: true, last: Date.now(), stream_url: null },
      { device_id: 'cam-b', gate: 'OUT', ip: '192.168.4.12', rssi: -66, state: 'IDLE', online: true, last: Date.now(), stream_url: null }
    ]
  };
  try { const id = sessionStorage.getItem('gv_mock_uid'); if (id) S.cur = S.users.find(u => u.id === +id) || null; } catch (_) {}

  const devOut = d => ({ device_id: d.device_id, gate: d.gate, ip: d.ip, rssi: d.rssi, uptime: Math.floor((Date.now() - S.bootAt) / 1000) + 86400, state: d.state, last_seen: iso(d.last), online: d.online, stream_url: d.stream_url });
  const userOut = u => ({ id: u.id, username: u.username, display_name: u.display_name, role: u.role, must_change_password: u.must_change_password });
  function emit(msg) { if (S.wsUp) S.listeners.forEach(h => h.onmessage(JSON.parse(JSON.stringify(msg)))); }
  function setState(dev, st, after) {
    dev.state = st; emit({ type: 'device_status', data: devOut(dev) });
    if (after) setTimeout(() => { if (dev.state === st && dev.online) setState(dev, 'IDLE'); }, after);
  }

  function newAlert(type, ev, dev, message) {
    const a = { id: S.nextAlert++, type, event_id: ev ? ev.event_id : null, device_id: dev ? dev.device_id : null, time: iso(Date.now()), status: 'OPEN', message };
    S.alerts.unshift(a); emit({ type: 'alert', data: a }); return a;
  }
  function resolveAlerts(match) {
    S.alerts.filter(a => a.status === 'OPEN' && match(a)).forEach(a => { a.status = 'RESOLVED'; emit({ type: 'alert', data: a }); });
  }
  function fuzzyMatch(read) {
    const r = norm(read);
    return S.sessions.filter(s => {
      if (s.status !== 'IN') return false;
      const p = norm(s.plate); if (p.length !== r.length || p === r) return false;
      let diff = 0, ok = true;
      for (let i = 0; i < p.length; i++) if (p[i] !== r[i]) { diff++; if (CONF[p[i]] !== r[i]) ok = false; }
      return diff === 1 && ok;
    });
  }
  const inLot = plate => S.sessions.find(s => s.status === 'IN' && norm(s.plate) === norm(plate));

  function openSession(plate, ev, flagged) {
    const s = { id: S.nextSession++, plate, time_in: ev.time, image_in_url: ev.image_url, confidence_in: ev.confidence, time_out: null, image_out_url: null, confidence_out: null, status: 'IN', flagged: !!flagged };
    S.sessions.unshift(s); return s;
  }
  function closeSession(s, ev) { s.status = 'OUT'; s.time_out = ev.time; s.image_out_url = ev.image_url; s.confidence_out = ev.confidence; }

  function capture(gate, read, conf, silent, holdS) {
    const dev = S.devices.find(d => d.gate === gate);
    const id = S.nextEvent++;
    const readable = read && conf >= 0.6;
    const ev = { event_id: id, time: iso(Date.now()), gate, device_id: dev.device_id, plate: readable ? read : null, confidence: readable ? +conf.toFixed(2) : null, decision: 'OPEN', status: 'OK', image_url: frameSVG(readable ? read : null, id), plate_image_url: readable ? plateSVG(read) : null, session_id: null, fuzzy_candidates: [], resolution: null, hold_expires_at: null };
    let msg = '';
    if (!readable) { ev.status = 'UNREADABLE'; ev.decision = 'HOLD'; msg = 'Không đọc được biển số'; }
    else if (gate === 'IN') {
      if (inLot(read)) { ev.status = 'DUPLICATE_IN'; ev.decision = 'HOLD'; msg = 'Biển này đã có trong bãi'; }
      else ev.session_id = openSession(read, ev).id;
    } else {
      const m = inLot(read);
      if (m) { closeSession(m, ev); ev.session_id = m.id; }
      else {
        const f = fuzzyMatch(read);
        if (f.length) { ev.status = 'FUZZY'; ev.decision = 'HOLD'; ev.fuzzy_candidates = f.map(s => ({ session_id: s.id, plate: s.plate })); msg = 'Biển gần giống xe trong bãi, cần xác nhận'; }
        else { ev.status = 'MISMATCH'; ev.decision = 'HOLD'; msg = 'Biển ra không khớp phiên nào đang mở'; }
      }
    }
    S.events.unshift(ev);
    if (ev.decision === 'HOLD') {
      const hs = holdS || cfg.HOLD_MAX_S;
      ev.hold_expires_at = iso(Date.now() + hs * 1000);
      S.timers[id] = setTimeout(() => expire(ev), hs * 1000);
    }
    if (!silent) {
      emit({ type: 'event_created', data: ev });
      if (ev.decision === 'HOLD') { newAlert(ev.status, ev, dev, msg); setState(dev, 'HOLD'); }
      else setState(dev, 'GATE_OPEN', 4000);
    }
    return ev;
  }
  function expire(ev) {
    if (ev.resolution) return;
    ev.resolution = { action: 'EXPIRED', operator_id: null, operator_name: null, time: iso(Date.now()), manual_plate: null };
    ev.hold_expires_at = null;
    resolveAlerts(a => a.event_id === ev.event_id);
    emit({ type: 'event_updated', data: ev });
    setState(S.devices.find(d => d.device_id === ev.device_id), 'IDLE');
  }

  /* ---------- dữ liệu ban đầu ---------- */
  function seed() {
    const t0 = Date.now();
    PLATES.slice(0, 6).forEach((p, i) => {
      const ev = capture('IN', p, rnd(0.8, 0.96), true);
      const t = t0 - (180 - i * 25) * 60000; ev.time = iso(t);
      const s = S.sessions.find(x => x.id === ev.session_id); s.time_in = ev.time;
    });
    const m = capture('OUT', '59Q9-00000', 0.88, true);
    m.time = iso(t0 - 40 * 60000); clearTimeout(S.timers[m.event_id]);
    m.hold_expires_at = null; m.resolution = { action: 'DENY', operator_id: 2, operator_name: 'Nhân viên trực 1', time: iso(t0 - 39 * 60000), manual_plate: null };
    S.alerts.unshift({ id: S.nextAlert++, type: 'MISMATCH', event_id: m.event_id, device_id: null, time: m.time, status: 'RESOLVED', message: 'Biển ra không khớp phiên nào đang mở' });
    const out = capture('OUT', PLATES[5], 0.91, true); out.time = iso(t0 - 12 * 60000);
    const o = S.sessions.find(s => s.id === out.session_id); o.time_out = out.time;
    S.events.sort((a, b) => b.event_id - a.event_id);
  }
  seed();
  setInterval(() => {
    S.devices.forEach(d => { if (!d.online) return; d.rssi = Math.max(-80, Math.min(-45, d.rssi + Math.round(rnd(-2, 2)))); d.last = Date.now(); emit({ type: 'device_status', data: devOut(d) }); });
  }, 10000);

  /* ---------- REST giả ---------- */
  const needUser = () => { if (!S.cur) fail(401, 'UNAUTHORIZED', 'Bạn cần đăng nhập.'); return S.cur; };
  const validPlate = p => /^[0-9A-Z]{6,10}$/.test(norm(p));

  async function request(method, path, opt = {}) {
    await delay(100 + Math.random() * 120);
    const q = opt.query || {}, b = opt.body || {};
    let m;
    if (path === '/healthz') return { status: 'ok' };
    if (path === '/auth/login' && method === 'POST') {
      if (S.fails >= 5) fail(429, 'TOO_MANY_ATTEMPTS', 'Thử quá nhiều lần. Hãy đợi một lát rồi thử lại.');
      const u = S.users.find(x => x.username === b.username && x.password === b.password);
      if (!u) { S.fails++; fail(401, 'BAD_CREDENTIALS', 'Sai tên đăng nhập hoặc mật khẩu.'); }
      S.fails = 0; S.cur = u; try { sessionStorage.setItem('gv_mock_uid', u.id); } catch (_) {}
      return userOut(u);
    }
    if (path === '/auth/logout' && method === 'POST') { S.cur = null; try { sessionStorage.removeItem('gv_mock_uid'); } catch (_) {} return {}; }
    const me = needUser();
    if (path === '/users/me' && method === 'GET') return userOut(me);
    if (path === '/users/me' && method === 'PATCH') {
      const n = String(b.display_name || '').trim(); if (!n) fail(422, 'INVALID', 'Tên hiển thị không được để trống.');
      me.display_name = n; return userOut(me);
    }
    if (path === '/users/me/password' && method === 'POST') {
      if (b.old_password !== me.password) fail(422, 'BAD_OLD_PASSWORD', 'Mật khẩu hiện tại không đúng.');
      if (String(b.new_password || '').length < 8) fail(422, 'WEAK_PASSWORD', 'Mật khẩu mới cần ít nhất 8 ký tự.');
      me.password = b.new_password; me.must_change_password = false; return userOut(me);
    }
    if (path === '/users' || (m = path.match(/^\/users\/(\d+)$/))) {
      if (me.role !== 'admin') fail(403, 'FORBIDDEN', 'Chỉ quản trị mới dùng được chức năng này.');
      if (!m && method === 'GET') return { items: S.users.map(userOut), next_cursor: null };
      if (!m && method === 'POST') {
        const un = String(b.username || '').trim();
        if (!/^[a-z0-9_]{3,20}$/.test(un)) fail(422, 'INVALID', 'Tên đăng nhập gồm 3–20 ký tự thường, số hoặc dấu gạch dưới.');
        if (S.users.some(u => u.username === un)) fail(409, 'EXISTS', 'Tên đăng nhập đã tồn tại.');
        if (String(b.password || '').length < 8) fail(422, 'WEAK_PASSWORD', 'Mật khẩu cần ít nhất 8 ký tự.');
        const u = { id: S.nextUser++, username: un, display_name: String(b.display_name || un).trim() || un, role: b.role === 'admin' ? 'admin' : 'staff', must_change_password: true, password: b.password };
        S.users.push(u); return userOut(u);
      }
      if (m && method === 'PATCH') {
        const u = S.users.find(x => x.id === +m[1]); if (!u) fail(404, 'NOT_FOUND', 'Không có người dùng này.');
        if (b.role && u.id === me.id) fail(409, 'SELF_ROLE', 'Không đổi được vai trò của chính mình.');
        if (b.role) u.role = b.role === 'admin' ? 'admin' : 'staff';
        return userOut(u);
      }
    }
    if (path === '/events' && method === 'GET') {
      let l = S.events.slice();
      if (q.gate) l = l.filter(e => e.gate === q.gate);
      if (q.status) l = l.filter(e => e.status === q.status);
      if (q.plate) l = l.filter(e => e.plate && norm(e.plate).includes(norm(q.plate)));
      if (q.from) l = l.filter(e => vnDate(e.time) >= q.from);
      if (q.to) l = l.filter(e => vnDate(e.time) <= q.to);
      if (q.cursor) l = l.filter(e => e.event_id < +q.cursor);
      const lim = +q.limit || 50, items = l.slice(0, lim);
      return { items, next_cursor: l.length > lim ? String(items[items.length - 1].event_id) : null };
    }
    if ((m = path.match(/^\/events\/(\d+)$/)) && method === 'GET') {
      const e = S.events.find(x => x.event_id === +m[1]); if (!e) fail(404, 'EVENT_NOT_FOUND', 'Không có sự kiện này.'); return e;
    }
    if (path === '/sessions' && method === 'GET') {
      let l = S.sessions.slice();
      if (q.status) l = l.filter(s => s.status === q.status);
      if (q.plate) l = l.filter(s => norm(s.plate).includes(norm(q.plate)));
      return { items: l, next_cursor: null };
    }
    if (path === '/alerts' && method === 'GET') {
      let l = S.alerts.slice(); if (q.status) l = l.filter(a => a.status === q.status);
      return { items: l, next_cursor: null };
    }
    if (path === '/devices' && method === 'GET') return { items: S.devices.map(devOut), next_cursor: null };
    if (path === '/stats' && method === 'GET') {
      const today = vnDate(Date.now());
      return {
        inside_now: S.sessions.filter(s => s.status === 'IN').length,
        in_today: S.sessions.filter(s => vnDate(s.time_in) === today).length,
        out_today: S.sessions.filter(s => s.time_out && vnDate(s.time_out) === today).length,
        hold_today: S.events.filter(e => e.decision === 'HOLD' && vnDate(e.time) === today).length,
        unreadable_today: S.events.filter(e => e.status === 'UNREADABLE' && vnDate(e.time) === today).length
      };
    }
    if ((m = path.match(/^\/gate\/(IN|OUT)\/override$/)) && method === 'POST') {
      const ev = S.events.find(e => e.event_id === +b.event_id && e.gate === m[1]);
      if (!ev) fail(404, 'EVENT_NOT_FOUND', 'Không tìm thấy lượt xe này ở cổng này.');
      if (ev.decision !== 'HOLD') fail(409, 'ALREADY_RESOLVED', 'Lượt này không ở trạng thái giữ.');
      if (ev.resolution) fail(409, ev.resolution.action === 'EXPIRED' ? 'EXPIRED' : 'ALREADY_RESOLVED', ev.resolution.action === 'EXPIRED' ? 'Lượt giữ đã hết hạn.' : 'Lượt này đã được xử lý.');
      if (!['PASS', 'DENY'].includes(b.action)) fail(422, 'INVALID', 'Hành động không hợp lệ.');
      const dev = S.devices.find(d => d.device_id === ev.device_id);
      if (b.action === 'PASS') {
        if (ev.gate === 'IN' && ev.status === 'UNREADABLE') {
          if (b.manual_plate && !validPlate(b.manual_plate)) fail(422, 'INVALID_PLATE', 'Biển số nhập tay chưa đúng định dạng.');
          const plate = b.manual_plate ? String(b.manual_plate).trim().toUpperCase() : 'UNKNOWN-' + ev.event_id;
          if (b.manual_plate && inLot(plate)) fail(409, 'DUPLICATE_IN', 'Biển này đã có trong bãi.');
          ev.session_id = openSession(plate, ev, !b.manual_plate).id;
          if (b.manual_plate) ev.plate = plate;
        }
        if (ev.gate === 'OUT') {
          if (ev.status === 'FUZZY' && !b.session_id) fail(422, 'CHOOSE_SESSION', 'Hãy chọn xe trong bãi tương ứng.');
          if (b.session_id) {
            const s = S.sessions.find(x => x.id === +b.session_id && x.status === 'IN');
            if (!s) fail(422, 'INVALID_SESSION', 'Phiên không còn trong bãi.');
            if (ev.status === 'FUZZY' && !ev.fuzzy_candidates.some(c => c.session_id === s.id)) fail(422, 'INVALID_SESSION', 'Phiên không nằm trong các xe gần giống.');
            closeSession(s, ev); ev.session_id = s.id;
          }
        }
      }
      clearTimeout(S.timers[ev.event_id]);
      ev.hold_expires_at = null;
      ev.resolution = { action: b.action, operator_id: me.id, operator_name: me.display_name, time: iso(Date.now()), manual_plate: b.manual_plate || null };
      resolveAlerts(a => a.event_id === ev.event_id);
      emit({ type: 'event_updated', data: ev });
      if (b.action === 'PASS') setState(dev, 'GATE_OPEN', 4000); else setState(dev, 'IDLE');
      return { event: ev };
    }
    fail(404, 'NOT_FOUND', 'Không có đường dẫn này.');
  }

  /* ---------- WebSocket giả ---------- */
  function connectWS(h) {
    let closed = false;
    const handler = { onmessage: h.onmessage, onclose: () => { if (!closed) { closed = true; h.onclose(); } } };
    setTimeout(() => {
      if (closed) return;
      if (!S.wsUp) { handler.onclose(); return; }
      S.listeners.add(handler); h.onopen();
    }, 250);
    return { close() { closed = true; S.listeners.delete(handler); } };
  }

  /* ---------- công cụ thử cho trang Giám sát ---------- */
  function sim(kind) {
    const inside = S.sessions.filter(s => s.status === 'IN');
    const fresh = () => { let p; do { p = pick(['59A', '59D', '51G', '50M', '62E', '75C']) + pick('123456789') + '-' + String(Math.floor(rnd(10000, 99999))); } while (inLot(p)); return p; };
    const conf = () => rnd(0.78, 0.96);
    switch (kind) {
      case 'in_ok': capture('IN', fresh(), conf()); break;
      case 'out_ok': if (inside.length) capture('OUT', pick(inside).plate, conf()); break;
      case 'dup_in': if (inside.length) capture('IN', pick(inside).plate, conf()); break;
      case 'unreadable_in': capture('IN', null, 0); break;
      case 'unreadable_out': capture('OUT', null, 0); break;
      case 'mismatch_out': capture('OUT', fresh(), conf()); break;
      case 'fuzzy_out': {
        let s = inside.find(x => [...norm(x.plate)].some(c => CONF[c]));
        if (!s) { const ev = capture('IN', '59B1-10805', 0.9, false); s = S.sessions.find(x => x.id === ev.session_id); }
        const r = [...norm(s.plate)]; const i = r.findIndex(c => CONF[c]); r[i] = CONF[r[i]];
        const t = r.join(''); capture('OUT', t.slice(0, 4) + '-' + t.slice(4), 0.82); break;
      }
      case 'cam_toggle': case 'cam_a_toggle': {
        const d = S.devices[kind === 'cam_a_toggle' ? 0 : 1], nm = kind === 'cam_a_toggle' ? 'A' : 'B'; d.online = !d.online; d.last = Date.now();
        if (!d.online) { d.state = 'OFFLINE'; newAlert('DEVICE_OFFLINE', null, d, 'Camera ' + nm + ' mất kết nối'); }
        else { d.state = 'IDLE'; resolveAlerts(a => a.type === 'DEVICE_OFFLINE' && a.device_id === d.device_id); }
        emit({ type: 'device_status', data: devOut(d) }); break;
      }
      case 'hold_short': capture('OUT', fresh(), conf(), false, 15); break;
      case 'multi_hold':
        capture('IN', null, 0); capture('OUT', fresh(), conf());
        if (inside.length) capture('IN', pick(inside).plate, conf()); else capture('OUT', null, 0);
        break;
      case 'burst': for (let i = 0; i < 30; i++) { const p = fresh(); capture('IN', p, conf()); capture('OUT', p, conf()); } break;
      case 'reset': location.reload(); break;
      case 'ws_toggle':
        S.wsUp = !S.wsUp;
        if (!S.wsUp) { const hs = [...S.listeners]; S.listeners.clear(); hs.forEach(h => h.onclose()); }
        break;
    }
  }

  window.GV_MOCK = { request, connectWS, sim, idleFrame: IDLE, isWsUp: () => S.wsUp };
})();
