/* Logic giao diện (Alpine.js). Mỗi hàm có tên theo việc nó làm. */
function app() {
  const cfg = window.GV_CONFIG, api = window.GV_API;
  const GATES = [{ id: 'IN', name: 'Cổng A', dir: 'VÀO' }, { id: 'OUT', name: 'Cổng B', dir: 'RA' }];
  const TITLES = { dashboard: 'Giám sát cổng', history: 'Lịch sử', lot: 'Xe đang trong bãi', devices: 'Thiết bị', stats: 'Thống kê', profile: 'Tài khoản', users: 'Người dùng' };
  const STATUS = {
    OK: { label: 'Hợp lệ', cls: 'ok', icon: 'check' },
    DUPLICATE_IN: { label: 'Biển đã có trong bãi', cls: 'hold', icon: 'alert' },
    MISMATCH: { label: 'Không khớp xe nào trong bãi', cls: 'hold', icon: 'alert' },
    FUZZY: { label: 'Gần giống, cần xác nhận', cls: 'hold', icon: 'alert' },
    UNREADABLE: { label: 'Không đọc được biển', cls: 'err', icon: 'x' }
  };
  const norm = p => String(p || '').toUpperCase().replace(/[\s.\-]/g, '');
  const fmt = new Intl.DateTimeFormat('vi-VN', { timeZone: cfg.TZ, hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });

  return {
    cfg, mock: cfg.USE_MOCK, devtools: !!(cfg.USE_MOCK || cfg.DEV_TOOLS), gates: GATES, titles: TITLES,
    booted: false, user: null, route: 'dashboard',
    loginForm: { username: '', password: '', error: '', busy: false },
    events: [], alerts: [], devices: [], sessions: [], stats: null, users: [],
    exporting: false, wsState: 'connecting', ws: null, wsTry: 0, wsGen: 0, wsTimer: null, refreshT: null,
    nowMs: Date.now(), sound: false, audio: null, toast: null, toastT: null, camErr: {}, menu: false, deskSel: null,
    dlg: { open: false, ev: null, action: '', manual: '', sessionId: '', busy: false, error: '' },
    detail: null,
    hist: { items: [], cursor: null, loading: false, f: { plate: '', gate: '', status: '', from: '', to: '' } },
    lotQ: '', histErr: '',
    pw: { old: '', n1: '', n2: '', error: '', busy: false },
    prof: { name: '', msg: '' },
    newUser: { username: '', display_name: '', role: 'staff', password: '', error: '', busy: false },

    /* ---------- khởi động ---------- */
    async init() {
      setInterval(() => { this.nowMs = Date.now(); }, 1000);
      window.addEventListener('hashchange', () => this.syncRoute());
      window.addEventListener('keydown', e => {
        if (e.key !== 'Escape') return;
        if (this.dlg.open) { if (!this.dlg.busy) this.dlg.open = false; }
        else if (this.detail) this.detail = null;
      });
      let opener = null;
      const track = (open) => { if (open) { opener = document.activeElement; } else if (opener && opener.focus) { const o = opener; opener = null; setTimeout(() => o.focus(), 0); } };
      this.$watch('dlg.open', v => { track(v); if (v) this.$nextTick(() => { const b = document.getElementById('dlg-confirm'); if (b) b.focus(); }); });
      this.$watch('detail', v => { track(!!v); if (v) this.$nextTick(() => { const b = document.querySelector('#dlg-detail-close'); if (b) b.focus(); }); });
      window.addEventListener('keydown', e => { if (e.key === 'Escape') { this.dlg.open = false; this.detail = null; } });
      try { this.sound = localStorage.getItem('gv_sound') === '1'; } catch (_) {}
      try { this.user = await api.request('GET', '/users/me'); await this.afterLogin(); } catch (_) {}
      this.booted = true;
    },
    async afterLogin() {
      this.prof.name = this.user.display_name;
      if (this.user.must_change_password) return;
      await this.resync();
      this.startWS();
      this.syncRoute();
    },
    async resync() {
      await Promise.all([this.loadEvents(), this.loadAlerts(), this.loadDevices(), this.loadSessions(), this.loadStats()]);
    },
    syncRoute() {
      let h = location.hash.slice(1);
      if (!TITLES[h] || (h === 'users' && !(this.user && this.user.role === 'admin'))) h = 'dashboard';
      this.route = h; this.menu = false;
      if (h === 'history') this.loadHistory(true);
      if (h === 'lot') this.loadSessions();
      if (h === 'stats') this.loadStats();
      if (h === 'devices') this.loadDevices();
      if (h === 'users') this.loadUsers();
    },
    go(r) { location.hash = r; },

    /* ---------- đăng nhập ---------- */
    async doLogin() {
      const f = this.loginForm; f.error = ''; f.busy = true;
      try {
        this.user = await api.request('POST', '/auth/login', { body: { username: f.username.trim(), password: f.password } });
        f.password = '';
        await this.afterLogin();
      } catch (e) { f.error = e.message; }
      f.busy = false;
    },
    async doLogout() {
      try { await api.request('POST', '/auth/logout'); } catch (_) {}
      this.stopWS(); this.user = null; this.events = []; this.alerts = []; this.sessions = []; this.hist.items = [];
      this.hist.cursor = null; location.hash = '';
    },
    async changePassword(forced) {
      const p = this.pw; p.error = '';
      if (p.n1.length < 8) { p.error = 'Mật khẩu mới cần ít nhất 8 ký tự.'; return; }
      if (p.n1 !== p.n2) { p.error = 'Hai lần nhập mật khẩu mới chưa giống nhau.'; return; }
      p.busy = true;
      try {
        this.user = await api.request('POST', '/users/me/password', { body: { old_password: p.old, new_password: p.n1 } });
        p.old = p.n1 = p.n2 = '';
        if (forced) await this.afterLogin(); else this.say('Đã đổi mật khẩu.');
      } catch (e) { p.error = e.message; }
      p.busy = false;
    },
    async saveName() {
      this.prof.msg = '';
      try { this.user = await api.request('PATCH', '/users/me', { body: { display_name: this.prof.name } }); this.say('Đã lưu tên hiển thị.'); }
      catch (e) { this.prof.msg = e.message; }
    },

    /* ---------- tải dữ liệu ---------- */
    async loadEvents() { try { this.events = (await api.request('GET', '/events', { query: { limit: 40 } })).items; } catch (e) { this.say(e.message, 'err'); } },
    async loadAlerts() { try { this.alerts = (await api.request('GET', '/alerts', { query: { status: 'OPEN' } })).items; } catch (_) {} },
    async loadDevices() { try { this.devices = (await api.request('GET', '/devices')).items; } catch (_) {} },
    async loadSessions() { try { this.sessions = (await api.request('GET', '/sessions', { query: { status: 'IN' } })).items; } catch (_) {} },
    async loadStats() { try { this.stats = await api.request('GET', '/stats'); } catch (_) {} },
    async loadUsers() { try { this.users = (await api.request('GET', '/users')).items; } catch (e) { this.say(e.message, 'err'); } },
    async loadHistory(reset) {
      const h = this.hist; if (h.loading) return;
      if (reset) { h.items = []; h.cursor = null; }
      h.loading = true; this.histErr = '';
      try {
        const r = await api.request('GET', '/events', { query: { ...h.f, limit: 20, cursor: h.cursor || '' } });
        h.items = h.items.concat(r.items); h.cursor = r.next_cursor;
      } catch (e) { this.histErr = e.message; }
      h.loading = false;
    },
    async exportCsv() {
      if (this.exporting) return;
      this.exporting = true; this.histErr = '';
      try {
        const rows = []; let cursor = '';
        for (let i = 0; i < 25; i++) {   // tối đa 5000 dòng
          const r = await api.request('GET', '/events', { query: { ...this.hist.f, limit: 200, cursor } });
          rows.push(...r.items); cursor = r.next_cursor;
          if (!cursor) break;
        }
        const q = v => { v = v == null ? '' : String(v); if (/^[=+\-@]/.test(v)) v = "'" + v; return '"' + v.replace(/"/g, '""') + '"'; };
        const head = ['Mã lượt', 'Thời gian', 'Cổng', 'Biển số', 'Trạng thái', 'Độ tin cậy (%)', 'Quyết định', 'Kết quả xử lý', 'Người xử lý', 'Biển nhập tay'];
        const lines = [head.map(q).join(',')];
        for (const e of rows) {
          const res = e.resolution;
          lines.push([e.event_id, this.time(e.time), e.gate === 'IN' ? 'A vào' : 'B ra', e.plate || '', this.statusInfo(e).label,
            e.confidence != null ? this.pct(e.confidence) : '', e.decision, this.resultText(e), res && res.operator_name || '', res && res.manual_plate || ''].map(q).join(','));
        }
        const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
        a.download = 'lich-su-gatevision-' + new Date().toISOString().slice(0, 10) + '.csv';
        document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        this.say('Đã tải ' + rows.length + ' dòng' + (cursor ? ' (đủ 5000 dòng đầu, hãy lọc hẹp hơn để lấy phần còn lại)' : '') + '.');
      } catch (e) { this.histErr = e.message; }
      this.exporting = false;
    },
    clearFilters() { this.hist.f = { plate: '', gate: '', status: '', from: '', to: '' }; this.loadHistory(true); },

    /* ---------- thời gian thực ---------- */
    startWS() {
      this.stopWS();
      const gen = ++this.wsGen;
      this.wsState = this.wsTry ? 'down' : 'connecting';
      this.ws = api.connectWS({
        onopen: () => { if (gen !== this.wsGen) return; const again = this.wsTry > 0; this.wsTry = 0; this.wsState = 'up'; if (again) this.resync(); },
        onclose: () => {
          if (gen !== this.wsGen) return;
          this.wsState = 'down';
          const wait = Math.min(1000 * 2 ** this.wsTry, 5000); this.wsTry++;
          this.wsTimer = setTimeout(() => { if (gen === this.wsGen) this.startWS(); }, wait);
        },
        onmessage: m => { if (gen === this.wsGen) this.onWS(m); }
      });
    },
    stopWS() { this.wsGen++; clearTimeout(this.wsTimer); if (this.ws) this.ws.close(); this.ws = null; },
    upsert(list, item, key) {
      const i = list.findIndex(x => x[key] === item[key]);
      if (i >= 0) list.splice(i, 1, item); else list.unshift(item);
    },
    onWS(m) {
      const d = m.data;
      if (m.type === 'event_created') {
        this.upsert(this.events, d, 'event_id'); this.events.sort((a, b) => b.event_id - a.event_id); this.events.splice(60);
        if (d.decision === 'HOLD') { this.beep(); this.say(this.gateName(d.gate) + ': cần xử lý, ' + STATUS[d.status].label.toLowerCase() + '.', 'hold'); }
      } else if (m.type === 'event_updated') {
        this.upsert(this.events, d, 'event_id');
        const h = this.hist.items.findIndex(x => x.event_id === d.event_id); if (h >= 0) this.hist.items.splice(h, 1, d);
      } else if (m.type === 'alert') { this.upsert(this.alerts, d, 'id'); this.alerts = this.alerts.filter(a => a.status === 'OPEN'); }
      else if (m.type === 'device_status') { this.upsert(this.devices, d, 'device_id'); if (d.online) this.camErr[d.gate] = false; }
      clearTimeout(this.refreshT);
      this.refreshT = setTimeout(() => { this.loadSessions(); this.loadStats(); }, 400);
    },

    /* ---------- dữ liệu hiển thị ---------- */
    gateName(id) { const g = GATES.find(x => x.id === id); return g.name + ' (' + g.dir + ')'; },
    device(gate) { return this.devices.find(d => d.gate === gate) || null; },
    lastEvent(gate) { return this.events.find(e => e.gate === gate) || null; },
    recent(gate) { return this.events.filter(e => e.gate === gate).slice(0, 5); },
    get holds() { return this.events.filter(e => e.decision === 'HOLD' && !e.resolution).sort((a, b) => b.event_id - a.event_id); },
    get desk() { const h = this.holds; if (!h.length) return null; return h.find(e => e.event_id === this.deskSel) || h[h.length - 1]; },
    get queue() { const d = this.desk; return this.holds.filter(e => !d || e.event_id !== d.event_id).reverse(); },
    get logEvents() { return this.events.slice(0, 30); },
    explain(ev) {
      if (ev.status === 'DUPLICATE_IN') return 'Biển này đang có trong bãi. Có thể xe đã vào trước đó, hoặc camera đọc nhầm.';
      if (ev.status === 'MISMATCH') return 'Không có xe nào trong bãi mang biển này.';
      if (ev.status === 'FUZZY') return 'Giống biển: ' + (ev.fuzzy_candidates || []).map(c => c.plate).join(', ') + '. Hãy đối chiếu với xe thật.';
      if (ev.status === 'UNREADABLE') return ev.gate === 'IN' ? 'Camera không đọc được biển. Bạn có thể nhập tay biển khi cho qua.' : 'Camera không đọc được biển. Hãy đối chiếu với xe thật rồi quyết định.';
      return '';
    },
    get offlineAlerts() { return this.alerts.filter(a => a.type === 'DEVICE_OFFLINE'); },
    get filteredLot() {
      const q = norm(this.lotQ);
      return this.sessions.filter(s => s.status === 'IN' && (!q || norm(s.plate).includes(q)));
    },
    camSrc(gate) {
      if (!this.user) return '';
      if (cfg.USE_MOCK || cfg.DEV_TOOLS) { const e = this.lastEvent(gate); return e ? e.image_url : api.idleFrame; }
      const d = this.device(gate); return d && d.stream_url ? d.stream_url : '';
    },
    camOk(gate) { const d = this.device(gate); return !!(d && d.online) && !this.camErr[gate]; },
    statusInfo(ev) { return STATUS[ev.status] || STATUS.OK; },
    // con dấu trên vé gửi xe: kết quả cuối cùng của lượt
    stamp(ev) {
      const r = ev.resolution;
      if (r) return r.action === 'PASS' ? { t: 'Đã cho qua', c: 'ok' } : r.action === 'DENY' ? { t: 'Từ chối', c: 'err' } : { t: 'Hết hạn', c: 'off' };
      if (ev.decision === 'HOLD') return { t: 'Chờ duyệt', c: 'hold' };
      return { t: ev.gate === 'IN' ? 'Đã vào' : 'Đã ra', c: 'ok' };
    },
    sessNo(s) { return 'Phiên #' + String(s.id).padStart(4, '0'); },
  ticketNo(ev) { return 'Vé #' + String(ev.event_id).padStart(4, '0'); },
    today() { return new Intl.DateTimeFormat('vi-VN', { timeZone: cfg.TZ, weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date()); },
    resultText(ev) {
      const r = ev.resolution;
      if (!r) return ev.decision === 'OPEN' ? 'Đã mở cổng' : 'Đang giữ, chờ người trực';
      if (r.action === 'EXPIRED') return 'Hết hạn, cổng không mở';
      const who = r.operator_name || 'người trực';
      return r.action === 'PASS' ? 'Cho qua bởi ' + who : 'Từ chối bởi ' + who;
    },
    plateLines(plate) {
      if (!plate) return ['—', ''];
      const m = String(plate).split('-'); let b = m.slice(1).join('');
      if (/^\d{5}$/.test(b)) b = b.slice(0, 3) + '.' + b.slice(3);
      return [m[0], b];
    },
    pct(c) { return c == null ? 0 : Math.round(c * 100); },
    holdLeft(ev) { return ev.hold_expires_at ? Math.max(0, Math.floor((Date.parse(ev.hold_expires_at) - this.nowMs) / 1000)) : 0; },
    holdText(ev) { const s = this.holdLeft(ev); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); },
    canAct(ev) { return this.wsState === 'up' && this.holdLeft(ev) > 0; },
    time(iso) { return iso ? fmt.format(new Date(iso)).replace(',', '') : '—'; },
    timeShort(iso) { return iso ? this.time(iso).split(' ')[0] : '—'; },
    ago(iso) {
      const s = Math.max(0, Math.floor((this.nowMs - Date.parse(iso)) / 1000));
      if (s < 60) return s + ' giây trước';
      if (s < 3600) return Math.floor(s / 60) + ' phút trước';
      return Math.floor(s / 3600) + ' giờ ' + Math.floor(s % 3600 / 60) + ' phút trước';
    },
    duration(iso) {
      const m = Math.max(0, Math.floor((this.nowMs - Date.parse(iso)) / 60000));
      return Math.floor(m / 60) + ' giờ ' + String(m % 60).padStart(2, '0') + ' phút';
    },
    uptime(s) { const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return (d ? d + ' ngày ' : '') + h + ' giờ ' + m + ' phút'; },
    rssiLevel(r) { return r >= -60 ? 'Tốt' : r >= -70 ? 'Khá' : 'Yếu'; },
    stateText(s) {
      return { IDLE: 'Sẵn sàng', DETECTED: 'Phát hiện xe', CAPTURING: 'Đang chụp', WAITING_SERVER: 'Chờ máy chủ', GATE_OPENING: 'Đang mở cổng', GATE_OPEN: 'Cổng đang mở', GATE_CLOSING: 'Đang đóng cổng', COOLDOWN: 'Nghỉ ngắn', HOLD: 'Đang giữ xe', ERROR_RETRY: 'Lỗi, đang thử lại', OFFLINE: 'Mất kết nối' }[s] || s;
    },

    /* ---------- xử lý lượt bị giữ ---------- */
    openOverride(ev, action) {
      const first = ev.fuzzy_candidates && ev.fuzzy_candidates[0];
      this.dlg = { open: true, ev, action, manual: '', sessionId: first ? String(first.session_id) : '', busy: false, error: '' };
      this.$nextTick(() => { const el = document.getElementById('dlg-confirm'); if (el) el.focus(); });
    },
    get sessionOptions() {
      const ev = this.dlg.ev; if (!ev) return [];
      if (ev.status === 'FUZZY') return (ev.fuzzy_candidates || []).map(c => ({ v: String(c.session_id), l: c.plate }));
      return this.sessions.map(s => ({ v: String(s.id), l: s.plate + ' · vào lúc ' + this.timeShort(s.time_in) }));
    },
    get needsSession() { return this.dlg.ev && this.dlg.action === 'PASS' && this.dlg.ev.gate === 'OUT'; },
    async confirmOverride() {
      const d = this.dlg; if (d.busy) return;
      d.error = ''; d.busy = true;
      try {
        const body = { event_id: d.ev.event_id, action: d.action, manual_plate: d.manual.trim() || null, session_id: d.sessionId ? +d.sessionId : null };
        const r = await api.request('POST', '/gate/' + d.ev.gate + '/override', { body });
        this.upsert(this.events, r.event, 'event_id');
        d.open = false;
        this.say(d.action === 'PASS' ? 'Đã cho qua.' : 'Đã từ chối.');
      } catch (e) {
        d.error = e.message + (e.status === 0 ? ' Lệnh chưa được gửi, hãy kiểm tra rồi bấm lại.' : '');
        if (e.status === 409) this.loadEvents();
      }
      d.busy = false;
    },

    /* ---------- người dùng (admin) ---------- */
    async addUser() {
      const n = this.newUser; n.error = ''; n.busy = true;
      try {
        await api.request('POST', '/users', { body: { username: n.username, display_name: n.display_name, role: n.role, password: n.password } });
        Object.assign(n, { username: '', display_name: '', role: 'staff', password: '' });
        this.say('Đã tạo tài khoản. Người dùng sẽ phải đổi mật khẩu khi đăng nhập lần đầu.'); this.loadUsers();
      } catch (e) { n.error = e.message; }
      n.busy = false;
    },
    async setRole(u, role) {
      try { await api.request('PATCH', '/users/' + u.id, { body: { role } }); this.say('Đã đổi vai trò.'); }
      catch (e) { this.say(e.message, 'err'); }
      this.loadUsers();
    },

    /* ---------- tiện ích ---------- */
    say(msg, kind) {
      this.toast = { msg, kind: kind || 'ok' }; clearTimeout(this.toastT);
      this.toastT = setTimeout(() => { this.toast = null; }, 5000);
    },
    toggleSound() {
      this.sound = !this.sound;
      try { localStorage.setItem('gv_sound', this.sound ? '1' : '0'); } catch (_) {}
      if (this.sound) this.beep();
    },
    beep() {
      if (!this.sound) return;
      try {
        const A = window.AudioContext || window.webkitAudioContext; if (!A) return;
        this.audio = this.audio || new A();
        [0, 0.28].forEach(t => {
          const o = this.audio.createOscillator(), g = this.audio.createGain();
          o.frequency.value = 880; g.gain.setValueAtTime(0.08, this.audio.currentTime + t);
          g.gain.exponentialRampToValueAtTime(0.001, this.audio.currentTime + t + 0.22);
          o.connect(g); g.connect(this.audio.destination); o.start(this.audio.currentTime + t); o.stop(this.audio.currentTime + t + 0.24);
        });
      } catch (_) {}
    },
    async sim(kind) { await api.sim(kind); if (kind === 'reset' && !cfg.USE_MOCK) location.reload(); }
  };
}
