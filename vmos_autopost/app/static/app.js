(() => {
  const qs = new URLSearchParams(location.search);
  const TOKEN = qs.get('t') || sessionStorage.getItem('t') || '';
  if (TOKEN) { sessionStorage.setItem('t', TOKEN); history.replaceState(null, '', location.pathname); }

  const STATUSES = ['QUEUED', 'PREPARING', 'NEEDS_OPERATOR', 'PAUSED', 'REVIEW_REQUIRED', 'VERIFIED', 'FAILED', 'CANCELLED'];
  const LABEL = { QUEUED: 'Antre', PREPARING: 'Menyiapkan', NEEDS_OPERATOR: 'Butuh operator', PAUSED: 'Dijeda',
    REVIEW_REQUIRED: 'Perlu diperiksa', VERIFIED: 'Terverifikasi', FAILED: 'Gagal', CANCELLED: 'Dibatalkan' };

  // h() selalu memakai textContent/TextNode, jadi data dari sheet tidak bisa menyisipkan HTML.
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return e;
  }

  async function api(path, method = 'GET', body) {
    const url = method === 'GET' ? `${path}${path.includes('?') ? '&' : '?'}_t=${Date.now()}` : path;
    const r = await fetch(url, {
      method,
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (r.statusText || 'Error'));
    return data;
  }

  function toast(msg, bad) {
    const t = h('div', { class: bad ? 'bad' : '' }, msg);
    document.getElementById('toast').append(t);
    setTimeout(() => t.remove(), bad ? 7000 : 3500);
  }

  function copyText(text, btn) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      if (btn) {
        const orig = btn.textContent;
        btn.textContent = '✓ Tersalin!';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.textContent = orig;
          btn.classList.remove('copied');
        }, 2000);
      }
      toast('Tersalin ke clipboard!');
    }).catch(() => {
      toast('Gagal menyalin ke clipboard', true);
    });
  }

  async function act(fn, okMsg) {
    try { const r = await fn(); if (okMsg) toast(okMsg); await refresh(); return r; }
    catch (e) { toast(e.message, true); }
  }

  function createSkeleton(type = 'card', count = 3) {
    const wrap = h('div', { class: 'skeleton-wrap' });
    for (let i = 0; i < count; i++) {
      wrap.append(h('div', { class: `skeleton skeleton-${type}` }));
    }
    return wrap;
  }

  function createEmptyState({ icon = '📭', title = 'Tidak Ada Data', desc = '', actionText = '', onAction = null }) {
    const kids = [
      h('div', { class: 'empty-state-icon' }, icon),
      h('div', { class: 'empty-state-title' }, title)
    ];
    if (desc) kids.push(h('div', { class: 'empty-state-desc' }, desc));
    if (actionText && onAction) {
      kids.push(h('button', { class: 'btn primary', onclick: onAction, style: 'font-weight: 600;' }, actionText));
    }
    return h('div', { class: 'empty-state-box' }, ...kids);
  }

  const main = document.getElementById('main');
  let view = 'beranda';
  let poll = null;

  function badge(s) { return h('span', { class: 'badge ' + s }, LABEL[s] || s); }

  // ---------------- Beranda ----------------
  async function viewBeranda() {
    main.replaceChildren(
      h('section', {},
        h('h2', {}, 'Dashboard Sistem & Metrik Utama'),
        createSkeleton('card', 4)
      ),
      h('section', {},
        h('h2', {}, 'Distribusi Status Tugas'),
        createSkeleton('row', 3)
      )
    );

    const [rep, cfg, accts, tasks] = await Promise.all([
      api('/report'),
      api('/config'),
      api('/accounts').catch(() => []),
      api('/tasks').catch(() => [])
    ]);

    const totalAccts = accts.length;
    const queuedTasks = rep.by_status['QUEUED'] || 0;
    const verifiedTasks = rep.by_status['VERIFIED'] || 0;

    // Quick Action Panel untuk Tugas NEEDS_OPERATOR & REVIEW_REQUIRED
    const attentionTasks = (tasks || []).filter(t => t.status === 'NEEDS_OPERATOR' || t.status === 'REVIEW_REQUIRED');
    let attentionPanel = null;

    if (attentionTasks.length > 0) {
      const attentionList = h('div', { class: 'attention-list' });
      attentionTasks.forEach(t => {
        const screenshotUrl = `/api/tasks/${t.id}/screenshot?_t=${Date.now()}`;
        const imgThumb = h('img', {
          class: 'attention-thumb',
          src: screenshotUrl,
          alt: `Layar VMOS ${t.pad_code}`,
          title: 'Klik untuk perbesar layar emulator VMOS'
        });
        const thumbWrap = h('div', {
          class: 'attention-thumb-wrap',
          title: 'Klik untuk membuka tangkapan layar emulator dalam tab baru',
          onclick: () => window.open(screenshotUrl, '_blank')
        }, imgThumb);

        const btnAutoPost = h('button', {
          class: 'btn primary',
          style: 'font-size: 12px; font-weight: 700;',
          onclick: async () => {
            toast(`⚡ Menjalankan ulang Auto-Post untuk #${t.id} (@${t.username})…`);
            try {
              await api(`/tasks/${t.id}/run-full`, 'POST');
              toast(`✅ Tugas #${t.id} (@${t.username}) berhasil dijalankan!`);
              await viewBeranda();
            } catch (e) {
              toast(`Gagal menjalankan tugas: ${e.message}`, true);
              await viewBeranda();
            }
          }
        }, '⚡ Auto-Post Otomatis di VMOS');

        const btnGoPosting = h('button', {
          class: 'btn',
          style: 'font-size: 12px; font-weight: 600;',
          onclick: () => show('posting')
        }, '👉 Buka di Tab Posting');

        const btnCancel = h('button', {
          class: 'btn danger',
          style: 'font-size: 12px;',
          onclick: async () => {
            if (!confirm(`Batalkan tugas #${t.id} (@${t.username})? Aplikasi Shopee di VMOS akan di-force stop.`)) return;
            try {
              await api(`/tasks/${t.id}/cancel`, 'POST', { reason: 'Dibatalkan oleh operator dari Beranda' });
              toast(`✓ Tugas #${t.id} dibatalkan.`);
              await viewBeranda();
            } catch (e) {
              toast(e.message, true);
            }
          }
        }, '🛑 Batalkan Tugas');

        const noteText = t.note || (t.status === 'NEEDS_OPERATOR'
          ? 'Emulator memerlukan tindakan operator (kemungkinan Captcha Shopee, Session Expired, atau Gagal Klik Tombol)'
          : 'Hasil posting belum terkonfirmasi, periksa profil akun');

        const card = h('div', { class: 'attention-card' },
          thumbWrap,
          h('div', { class: 'attention-info' },
            h('div', { class: 'attention-task-id' },
              h('span', {}, `#${t.id} · @${t.username}`),
              h('span', { class: 'badge-device' }, `VMOS: ${t.pad_code}`),
              badge(t.status)
            ),
            h('div', { class: 'attention-note' }, `⚠️ Masalah: ${noteText}`),
            h('div', { class: 'hint', style: 'margin-top: 5px; font-size: 11.5px;' },
              `Percobaan ke-${t.attempt} · Batch: ${t.batch || '-'} · Dibuat: ${(t.created_at || '').replace('T', ' ').slice(0, 19)}`
            )
          ),
          h('div', { class: 'attention-actions' },
            btnAutoPost,
            btnGoPosting,
            btnCancel
          )
        );
        attentionList.append(card);
      });

      attentionPanel = h('div', { class: 'attention-panel' },
        h('div', { class: 'attention-header' },
          h('div', { class: 'attention-title' },
            `⚠️ PERHATIAN OPERATOR: ${attentionTasks.length} TUGAS MEMBUTUHKAN TINDAKAN!`
          ),
          h('button', {
            class: 'btn',
            style: 'font-size: 11px; padding: 4px 10px;',
            onclick: () => viewBeranda()
          }, '🔄 Perbarui Status')
        ),
        h('p', { class: 'hint', style: 'margin: 0 0 12px; color: #92400e; font-size: 12.5px;' },
          'Cuplikan layar VMOS di bawah diambil langsung dari emulator saat tugas terhenti. Periksa apakah emulator terkena Captcha, OTP, Sesi Habis, atau Layar Macet:'
        ),
        attentionList
      );
    }

    const metricGrid = h('div', { class: 'metric-grid' },
      h('div', { class: 'metric-card' },
        h('div', { class: 'metric-icon', style: 'background: #eff6ff; color: #2563eb;' }, '👥'),
        h('div', { class: 'metric-info' },
          h('div', { class: 'metric-num' }, totalAccts),
          h('div', { class: 'metric-label' }, 'Total Akun Terdaftar')
        )
      ),
      h('div', { class: 'metric-card' },
        h('div', { class: 'metric-icon', style: 'background: #fef3c7; color: #d97706;' }, '⏳'),
        h('div', { class: 'metric-info' },
          h('div', { class: 'metric-num' }, queuedTasks),
          h('div', { class: 'metric-label' }, 'Antrean Siap Posting')
        )
      ),
      h('div', { class: 'metric-card' },
        h('div', { class: 'metric-icon', style: 'background: #dcfce7; color: #16a34a;' }, '✅'),
        h('div', { class: 'metric-info' },
          h('div', { class: 'metric-num' }, verifiedTasks),
          h('div', { class: 'metric-label' }, 'Tugas Terverifikasi')
        )
      ),
      h('div', { class: 'metric-card' },
        h('div', { class: 'metric-icon', style: cfg.adapter_ready ? 'background: #dcfce7; color: #16a34a;' : 'background: #f1f5f9; color: #64748b;' }, '📱'),
        h('div', { class: 'metric-info' },
          h('div', { class: 'metric-num', style: 'font-size: 18px; line-height: 1.4;' }, cfg.adapter_ready ? 'VMOS Siap' : 'Belum Konek'),
          h('div', { class: 'metric-label' }, cfg.dry_run ? 'Mode Uji (Dry-Run)' : (cfg.adapter_ready ? 'Online & Terhubung' : 'Buka Tab Pengaturan'))
        )
      )
    );

    const quickGrid = h('div', { class: 'quick-grid' },
      h('button', { class: 'quick-btn', onclick: async () => { await show('posting'); startAutoPilot(); } },
        h('div', { class: 'quick-btn-title' }, '🚀 Jalankan Auto-Pilot Antrean'),
        h('div', { class: 'quick-btn-desc' }, 'Proses seluruh tugas antrean dari awal hingga selesai')
      ),
      h('button', { class: 'quick-btn', onclick: () => show('posting') },
        h('div', { class: 'quick-btn-title' }, '🎬 Studio Pembuat Tugas'),
        h('div', { class: 'quick-btn-desc' }, 'Ambil bahan Shopee & Kuncian Prompt ALIPYOU untuk Flow')
      ),
      h('button', { class: 'quick-btn', onclick: () => show('pengaturan') },
        h('div', { class: 'quick-btn-title' }, '🔄 Sinkron Akun Google Sheet'),
        h('div', { class: 'quick-btn-desc' }, 'Muat atau perbarui daftar akun dari link spreadsheet')
      ),
      h('button', { class: 'quick-btn', onclick: async () => {
        try {
          const res = await api('/api/storage/clean-cache', 'POST');
          toast(`Cache dibersihkan: ${res.deleted} file video`);
        } catch (e) { toast(e.message, true); }
      } },
        h('div', { class: 'quick-btn-title' }, '🧹 Bersihkan Cache Video'),
        h('div', { class: 'quick-btn-desc' }, 'Bebaskan ruang disk dari video Flow yang sudah diposting')
      )
    );

    const stats = h('div', { class: 'grid' }, STATUSES.map(s =>
      h('div', { class: 'stat' }, h('b', {}, rep.by_status[s] || 0), h('span', {}, LABEL[s]))));

    const attention = rep.cleanup_attention.length
      ? h('div', { class: 'banner' }, '⚠️ Pembersihan video perlu perhatian: ',
          rep.cleanup_attention.map(a => `${a.pad_code} (${a.cleanup_status}: ${a.n})`).join(', '))
      : h('p', { class: 'hint' }, '✓ Semua penyimpanan video di ponsel cloud dalam kondisi bersih.');

    const mainKids = [];
    if (attentionPanel) {
      mainKids.push(attentionPanel);
    }
    mainKids.push(
      h('section', {},
        h('h2', {}, 'Dashboard Sistem & Metrik Utama'),
        metricGrid,
        h('h3', { style: 'font-size: 13.5px; font-weight: 700; margin: 16px 0 8px;' }, 'Aksi Cepat (Quick Actions):'),
        quickGrid
      ),
      h('section', {},
        h('h2', {}, 'Distribusi Status Tugas'),
        stats
      ),
      h('section', {},
        h('h2', {}, 'Status Pembersihan Ponsel Cloud VMOS'),
        attention
      )
    );
    main.replaceChildren(...mainKids);
  }

  async function startNext() {
    const t = await api('/queue/start-next', 'POST', {});
    if (!t.id) { toast('Tidak ada tugas yang bisa dimulai (antrean kosong, device terkunci, akun sedang diperiksa, atau batas frekuensi).'); return; }
    toast(`Menyiapkan tugas #${t.id} (@${t.username})…`);
    await api(`/tasks/${t.id}/prepare`, 'POST');
    toast('Materi siap. Lanjutkan di halaman Posting.');
    show('posting');
  }

  // ---------------- Posting ----------------
  let tasksBox;
  let autoPilotRunning = false;
  let autoPilotBanner;
  let btnAutoPilot;
  let autoNextCb;
  let gapTimer = null;

  async function stepAutoPilot() {
    if (!autoPilotRunning) return;
    try {
      if (autoPilotBanner) {
        autoPilotBanner.style.display = 'block';
        autoPilotBanner.textContent = '⏳ Auto-Pilot: Mengambil & memproses tugas... (Unduh video Flow, posting ke Shopee, tonton 2 menit, lalu force close)';
      }
      const res = await api('/queue/process-next', 'POST', {});
      await refreshTasks();
      if (!res.task_id) {
        toast('✅ Semua tugas dalam antrean telah selesai!');
        stopAutoPilot();
        return;
      }
      if (res.ok) {
        toast(`✅ Tugas #${res.task_id} (@${res.username}) selesai diposting & ditonton 2 menit!`);
      } else {
        toast(`⚠️ Tugas #${res.task_id} (@${res.username}) gagal: ${res.error || 'Terjadi kesalahan'}. Menjeda sebelum tugas berikutnya...`, true);
      }
      if (res.has_more && autoPilotRunning) {
        let remainingGap = 60;
        if (gapTimer) clearInterval(gapTimer);
        const updateCountdown = () => {
          if (!autoPilotRunning) {
            if (gapTimer) clearInterval(gapTimer);
            return;
          }
          if (remainingGap > 0) {
            if (autoPilotBanner) {
              const statusPrefix = res.ok ? `✓ Tugas #${res.task_id} (@${res.username}) selesai.` : `⚠️ Tugas #${res.task_id} (@${res.username}) gagal.`;
              autoPilotBanner.innerHTML = `${statusPrefix} ⏳ <b>Menjeda 60 detik</b> sebelum lanjut ke tugas berikutnya (sisa <b>${remainingGap} detik</b>)... <button id="btnSkipGap" class="btn" style="padding: 2px 8px; font-size: 11px; margin-left: 8px; cursor: pointer;">⏩ Lewati Jeda</button>`;
              const skipBtn = document.getElementById('btnSkipGap');
              if (skipBtn) {
                skipBtn.onclick = () => {
                  remainingGap = 0;
                  if (gapTimer) clearInterval(gapTimer);
                  stepAutoPilot();
                };
              }
            }
            remainingGap--;
          } else {
            if (gapTimer) clearInterval(gapTimer);
            if (autoPilotRunning) stepAutoPilot();
          }
        };
        updateCountdown();
        gapTimer = setInterval(updateCountdown, 1000);
      } else {
        toast('✅ Semua tugas dalam antrean telah selesai!');
        stopAutoPilot();
      }
    } catch (e) {
      toast(`Auto-Pilot terhenti: ${e.message}`, true);
      stopAutoPilot();
    }
  }

  function startAutoPilot() {
    if (autoPilotRunning) return;
    autoPilotRunning = true;
    if (btnAutoPilot) {
      btnAutoPilot.textContent = '⏹️ Hentikan Auto-Pilot';
      btnAutoPilot.className = 'btn danger';
    }
    if (autoPilotBanner) {
      autoPilotBanner.style.display = 'block';
      autoPilotBanner.textContent = '🚀 Memulai Auto-Pilot berurutan...';
    }
    toast('🚀 Auto-Pilot dimulai! Tugas akan diproses secara berurutan.');
    stepAutoPilot();
  }

  function stopAutoPilot() {
    autoPilotRunning = false;
    if (gapTimer) {
      clearInterval(gapTimer);
      gapTimer = null;
    }
    if (btnAutoPilot) {
      btnAutoPilot.textContent = '🚀 Jalankan Semua Tugas Otomatis (Auto-Pilot)';
      btnAutoPilot.className = 'btn primary';
    }
    if (autoPilotBanner) {
      autoPilotBanner.style.display = 'none';
    }
    refreshTasks().catch(() => {});
  }

  async function viewPosting() {
    const [accts, vids] = await Promise.all([api('/accounts'), api('/videos')]);
    const vidId = h('input', { placeholder: 'ID video (mis. v001)' });
    const vidPath = h('input', { placeholder: 'Path master video di PC (mis. D:\\video\\v001.mp4)' });
    const vidSel = h('select', {}, vids.map(v => h('option', { value: v.id }, v.id)));
    const batch = h('input', { placeholder: 'Batch (mis. 2026-10-26-pagi)' });
    const caption = h('input', { placeholder: 'Caption (opsional)' });

    // Urutkan akun secara natural berurutan (AKUN1, AKUN2, AKUN3, dst.)
    accts.sort((a, b) => {
      const na = parseInt((a.kode || '').replace(/\D+/g, '') || '0', 10);
      const nb = parseInt((b.kode || '').replace(/\D+/g, '') || '0', 10);
      return na - nb || (a.kode || '').localeCompare(b.kode || '');
    });

    const filter = h('input', { placeholder: 'Cari AKUN, username, atau VMOS...', style: 'flex: 1 1 200px;' });
    const rangeIn = h('input', { placeholder: 'Pilih no. mis. 1-20', style: 'width: 140px;' });
    const countBadge = h('span', { class: 'badge', style: 'font-size: 12.5px; padding: 4px 10px;' }, '0 akun dipilih');
    const headerCb = h('input', { type: 'checkbox', title: 'Pilih semua yang tampil' });

    autoNextCb = h('input', { type: 'checkbox', checked: true, style: 'cursor: pointer; width: 16px; height: 16px;' });
    autoPilotBanner = h('div', {
      class: 'banner',
      style: 'display: ' + (autoPilotRunning ? 'block' : 'none') + '; background: #e8f5e9; border: 1px solid #4caf50; color: #1b5e20; margin-bottom: 12px; font-weight: 600;'
    }, autoPilotRunning ? '🚀 Auto-Pilot aktif...' : '');

    btnAutoPilot = h('button', {
      class: 'btn ' + (autoPilotRunning ? 'danger' : 'primary'),
      style: 'font-weight: 700; padding: 7px 16px;',
      onclick: () => {
        if (autoPilotRunning) {
          stopAutoPilot();
          toast('Auto-Pilot dihentikan.');
        } else {
          startAutoPilot();
        }
      }
    }, autoPilotRunning ? '⏹️ Hentikan Auto-Pilot' : '🚀 Jalankan Semua Tugas Otomatis (Auto-Pilot)');

    const create = h('button', { class: 'btn primary' }, 'Buat tugas untuk akun terpilih');

    function updateCount() {
      const sel = rows.filter(r => r.cb.checked).length;
      countBadge.textContent = `${sel} akun dipilih`;
      create.textContent = sel ? `Buat tugas untuk ${sel} akun terpilih` : 'Buat tugas untuk akun terpilih';
      headerCb.checked = rows.length > 0 && rows.every(r => r.cb.checked);
    }

    const rows = accts.map(a => {
      const cb = h('input', { type: 'checkbox', value: a.username });
      const num = parseInt((a.kode || '').replace(/\D+/g, '') || '0', 10);
      const tr = h('tr', {
        onclick: (e) => {
          if (e.target !== cb) cb.checked = !cb.checked;
          tr.classList.toggle('selected', cb.checked);
          updateCount();
        }
      },
        h('td', { style: 'width: 34px;' }, cb),
        h('td', { style: 'width: 90px; font-weight: 600;' }, a.kode),
        h('td', {}, `@${a.username}`),
        h('td', {}, h('span', { class: 'badge-device' }, `${a.label ? 'VMOS ' + a.label + ' · ' : ''}${a.pad_code}`))
      );
      cb.addEventListener('change', () => {
        tr.classList.toggle('selected', cb.checked);
        updateCount();
      });
      return { a, cb, tr, num, text: `${a.kode} ${a.username} ${a.label || ''} ${a.pad_code}`.toLowerCase() };
    });

    let batchFilterMode = '';
    const batchFilterPills = h('div', { class: 'pill-chips', style: 'margin: 6px 0 10px;' },
      h('div', { class: 'pill-chip active', onclick: (e) => setBatchFilter('', e.currentTarget) }, `🔘 Semua (${rows.length})`),
      h('div', { class: 'pill-chip', onclick: (e) => setBatchFilter('NORMAL', e.currentTarget) }, '🟢 Normal'),
      h('div', { class: 'pill-chip', onclick: (e) => setBatchFilter('PERMANEN', e.currentTarget) }, '🔴 Banned/Permanen')
    );

    function setBatchFilter(mode, el) {
      batchFilterMode = mode;
      batchFilterPills.querySelectorAll('.pill-chip').forEach(c => c.classList.remove('active'));
      el.classList.add('active');
      applyBatchFilter();
    }

    function applyBatchFilter() {
      const q = filter.value.trim().toLowerCase();
      let visible = 0;
      rows.forEach(r => {
        const isPerm = (r.a.status_akun || '').toUpperCase() === 'PERMANEN' || (r.a.status_akun || '').toUpperCase() === 'BANNED';
        let matchStatus = true;
        if (batchFilterMode === 'NORMAL') matchStatus = !isPerm;
        else if (batchFilterMode === 'PERMANEN') matchStatus = isPerm;
        const matchSearch = !q || r.text.includes(q);
        const show = matchStatus && matchSearch;
        r.tr.style.display = show ? '' : 'none';
        if (show) visible++;
      });
      countBadge.textContent = `${rows.filter(r => r.cb.checked).length} terpilih (${visible} tampil)`;
    }

    filter.addEventListener('input', applyBatchFilter);

    const btnAll = h('button', { class: 'btn', type: 'button', onclick: () => {
      rows.forEach(r => {
        if (r.tr.style.display !== 'none') {
          r.cb.checked = true;
          r.tr.classList.add('selected');
        }
      });
      updateCount();
    }}, 'Pilih Semua');

    const btnNone = h('button', { class: 'btn', type: 'button', onclick: () => {
      rows.forEach(r => {
        r.cb.checked = false;
        r.tr.classList.remove('selected');
      });
      updateCount();
    }}, 'Batal Pilih');

    const btnRange = h('button', { class: 'btn', type: 'button', onclick: () => {
      const val = rangeIn.value.trim();
      if (!val) { toast('Ketik rentang nomor, mis. 1-20', true); return; }
      let start = null, end = null;
      if (val.includes('-')) {
        const parts = val.split('-');
        start = parseInt(parts[0], 10);
        end = parseInt(parts[1], 10);
      } else if (!isNaN(parseInt(val, 10))) {
        start = end = parseInt(val, 10);
      }
      if (isNaN(start) || isNaN(end)) { toast('Format rentang tidak valid (contoh: 1-20)', true); return; }
      let checkedCount = 0;
      rows.forEach(r => {
        if (r.num >= start && r.num <= end) {
          r.cb.checked = true;
          r.tr.classList.add('selected');
          checkedCount++;
        }
      });
      updateCount();
      toast(`${checkedCount} akun terpilih (No. ${start} s/d ${end})`);
    }}, 'Pilih Rentang');

    headerCb.addEventListener('change', () => {
      const val = headerCb.checked;
      rows.forEach(r => {
        if (r.tr.style.display !== 'none') {
          r.cb.checked = val;
          r.tr.classList.toggle('selected', val);
        }
      });
      updateCount();
    });

    const btnRefresh = h('button', { class: 'btn', type: 'button', title: 'Muat ulang daftar akun terbaru', onclick: () => viewPosting() }, '🔄 Update List');

    const toolbar = h('div', { class: 'toolbar' },
      filter,
      btnAll,
      btnNone,
      rangeIn,
      btnRange,
      btnRefresh,
      countBadge
    );

    const tbl = h('table', { class: 'acct-table' },
      h('thead', {}, h('tr', {},
        h('th', { style: 'width: 34px;' }, headerCb),
        h('th', { style: 'width: 90px;' }, 'Kode'),
        h('th', {}, 'Username Akun'),
        h('th', {}, 'Device / VMOS'))),
      h('tbody', {}, rows.map(r => r.tr)));

    const listWrap = h('div', { class: 'acct-wrap' }, tbl);

    const addVideo = h('button', { class: 'btn', onclick: () => act(async () => {
      await api('/videos', 'POST', { id: vidId.value.trim(), master_path: vidPath.value.trim() });
      vidId.value = ''; vidPath.value = '';
    }, 'Video didaftarkan') }, 'Daftarkan video');

    create.addEventListener('click', () => act(async () => {
      const usernames = rows.filter(r => r.cb.checked).map(r => r.cb.value);
      if (!usernames.length) throw new Error('Pilih minimal satu akun');
      if (!vidSel.value) throw new Error('Daftarkan dan pilih video dulu');
      const r = await api('/tasks/batch', 'POST', { usernames, video_id: vidSel.value, batch: batch.value, caption: caption.value || null });
      toast(`${r.created.length} tugas dibuat` + (r.errors.length ? `, ${r.errors.length} ditolak: ` + r.errors.map(e => `@${e.username} (${e.error})`).join('; ') : ''), r.errors.length > 0);
    }));

    // =========================================================================
    // STUDIO OPERATOR: INPUT TUGAS SEKUANSIAL PER AKUN (FLOW + SHOPEE)
    // =========================================================================
    const opAcctSel = h('select', { style: 'font-weight: 600; flex: 1 1 240px; padding: 7px 10px;' },
      accts.map(a => h('option', { value: a.username }, `${a.kode} — @${a.username} (${a.label ? 'VMOS ' + a.label : 'VMOS'} · ${a.pad_code})`))
    );
    const opAcctProg = h('span', { class: 'badge', style: 'padding: 5px 12px; font-size: 12px;' }, `Akun 1 dari ${accts.length}`);

    function updateOpProg() {
      const idx = opAcctSel.selectedIndex;
      opAcctProg.textContent = `Akun ${idx + 1} dari ${accts.length}`;
      const nextBtnText = accts[idx] ? `🚀 Simpan Tugas ${accts[idx].kode} & Lanjut ke Akun Berikutnya` : '🚀 Simpan Tugas & Lanjut';
      btnSaveNext.textContent = nextBtnText;
    }
    opAcctSel.addEventListener('change', updateOpProg);

    const PROMPT_CATEGORIES = [
      { label: '🎲 Acak Otomatis (Rekomendasi)', value: 'Random' },
      { label: 'Review / Unboxing', value: 'Review / Unboxing' },
      { label: 'Problem-Solution', value: 'Problem-Solution' },
      { label: 'Price & Value', value: 'Price & Value' },
      { label: 'Lifestyle / Aspirational', value: 'Lifestyle / Aspirational' },
      { label: 'Curiosity / Trending', value: 'Curiosity / Trending' },
      { label: 'Premium UGC / Soft-Sell', value: 'Premium UGC / Soft-Sell' },
      { label: 'POV / Product Only', value: 'POV / Product Only' }
    ];
    const promptCatSel = h('select', { style: 'font-weight: 600; flex: 1 1 180px;' },
      PROMPT_CATEGORIES.map(c => h('option', { value: c.value }, c.label))
    );

    const shopeeLinkIn = h('input', { placeholder: '1. Tempel link produk Shopee (shopee.co.id/... atau s.shopee.co.id/...)', style: 'flex: 2 1 240px;' });
    const btnScrape = h('button', { class: 'btn', type: 'button', style: 'font-weight: 600;' }, '🔍 Ambil Bahan & Kuncian Prompt');
    const flowVideoIn = h('input', { placeholder: 'Tempel link video Google Flow (flow.google.com/shared/video/...) atau nama file video', style: 'flex: 2 1 240px;' });

    // Drag-and-Drop Zone & Video Metadata Validator
    const dropzoneContainer = h('div', { class: 'dropzone-container' });
    const fileInput = h('input', { type: 'file', accept: 'video/mp4,video/*', style: 'display: none;' });
    let videoMetaCard = null;

    function resetVideoSelection() {
      flowVideoIn.value = '';
      if (videoMetaCard) {
        videoMetaCard.remove();
        videoMetaCard = null;
      }
      dropzone.style.display = 'flex';
      fileInput.value = '';
    }

    function handleVideoFile(file) {
      if (!file) return;
      const objectUrl = URL.createObjectURL(file);
      const tempVideo = document.createElement('video');
      tempVideo.preload = 'metadata';
      tempVideo.src = objectUrl;
      flowVideoIn.value = file.name;

      tempVideo.onloadedmetadata = () => {
        const width = tempVideo.videoWidth || 0;
        const height = tempVideo.videoHeight || 1;
        const durSec = tempVideo.duration || 0;
        const ratio = width / height;
        const is916 = ratio <= 0.65;
        const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
        const m = Math.floor(durSec / 60);
        const s = Math.floor(durSec % 60);
        const durStr = `${m}:${s < 10 ? '0' : ''}${s}`;

        const badgeCls = is916 ? 'aspect-badge ok' : 'aspect-badge warn';
        const badgeText = is916
          ? `✅ Rasio 9:16 Vertikal (${width}×${height}) — Format Ideal Shopee Video`
          : `⚠️ Rasio ${width}×${height} (${ratio.toFixed(2)}) — Disarankan video vertikal 9:16`;

        const vidPreview = h('video', {
          class: 'video-preview-thumb',
          src: objectUrl,
          muted: true,
          autoplay: true,
          loop: true,
          playsinline: true
        });

        const btnRemove = h('button', {
          class: 'btn',
          type: 'button',
          style: 'font-size: 11.5px; padding: 4px 10px;',
          onclick: resetVideoSelection
        }, '✕ Ganti Video');

        if (videoMetaCard) videoMetaCard.remove();
        videoMetaCard = h('div', { class: 'video-meta-card' },
          vidPreview,
          h('div', { class: 'video-info-box' },
            h('div', { style: 'font-weight: 700; font-size: 13.5px; color: #1e293b;' }, file.name),
            h('div', { class: 'hint' }, `Ukuran: ${sizeMb} MB · Durasi: ${durStr}`),
            h('div', { class: badgeCls, style: 'margin-top: 4px;' }, badgeText)
          ),
          h('div', {}, btnRemove)
        );

        dropzone.style.display = 'none';
        dropzoneContainer.append(videoMetaCard);
        toast(`Video terdeteksi: ${file.name} (${durStr}, ${sizeMb} MB)`);
      };
    }

    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files[0]) {
        handleVideoFile(fileInput.files[0]);
      }
    });

    const dropzone = h('div', {
      class: 'dropzone',
      onclick: () => fileInput.click(),
      ondragover: (e) => { e.preventDefault(); dropzone.classList.add('dragover'); },
      ondragleave: () => dropzone.classList.remove('dragover'),
      ondrop: (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          handleVideoFile(e.dataTransfer.files[0]);
        }
      }
    },
      h('div', { class: 'dropzone-icon' }, '🎬'),
      h('div', { class: 'dropzone-text' }, 'Tarik & Letakkan Berkas Video MP4 ke Sini, atau Klik untuk Memilih'),
      h('div', { class: 'dropzone-sub' }, 'Otomatis menganalisis durasi, ukuran berkas, dan memvalidasi rasio 9:16 untuk Shopee Video')
    );

    dropzoneContainer.append(dropzone, fileInput);

    const previewContainer = h('div', { class: 'preview-grid', style: 'display: none;' });
    let currentExtractedData = null;

    function renderExtractedPreview(data) {
      previewContainer.replaceChildren();
      previewContainer.style.display = 'grid';

      // Left Box: Foto & Metadata
      const imgElem = h('img', { class: 'prod-thumb', src: data.image || '', alt: data.title });

      const btnDownload = h('button', {
        class: 'btn primary',
        type: 'button',
        style: 'font-size: 12px; padding: 6px 12px; font-weight: 600;',
        onclick: async () => {
          if (!data.image) { toast('Foto produk tidak tersedia', true); return; }
          btnDownload.disabled = true;
          btnDownload.textContent = '⏳ Mengunduh...';
          try {
            const res = await api('/api/shopee/download-image', 'POST', {
              url: data.image,
              filename: `shopee_produk_${data.item_id || 'foto'}.jpg`,
              open_folder: true
            });
            toast(`✓ Foto disimpan di folder Downloads: ${res.filename} (${res.size_kb} KB)`);
          } catch (err) {
            toast(`Gagal mengunduh foto: ${err.message}`, true);
          } finally {
            btnDownload.disabled = false;
            btnDownload.textContent = '⬇️ Unduh Foto ke PC';
          }
        }
      }, '⬇️ Unduh Foto ke PC');

      const btnOpenBrowser = h('a', {
        class: 'btn',
        href: data.image || '#',
        target: '_blank',
        style: 'font-size: 12px; padding: 5px 10px; margin-left: 5px; text-decoration: none; display: inline-flex; align-items: center;'
      }, '🌐 Buka');

      const copyImgBtn = h('button', {
        class: 'btn-copy',
        type: 'button',
        style: 'margin-left: 5px; font-size: 12px; padding: 5px 8px;',
        onclick: () => copyText(data.image, copyImgBtn)
      }, '📋 Salin Link');

      const leftBox = h('div', { class: 'prod-img-box' },
        data.image ? imgElem : h('div', { class: 'hint', style: 'height: 120px; display: flex; align-items: center; justify-content: center; background: #eee; border-radius: 8px;' }, 'Foto tidak tersedia'),
        h('div', { style: 'font-weight: 700; font-size: 13px; margin: 8px 0 4px; text-align: left; line-height: 1.3;' }, data.title),
        h('div', { class: 'hint', style: 'text-align: left;' }, `ID: ${data.item_id || '-'} · Toko: ${data.shop_id || '-'}`),
        h('div', { style: 'margin-top: 8px; text-align: left; display: flex; flex-wrap: wrap; gap: 4px; align-items: center;' }, btnDownload, btnOpenBrowser, copyImgBtn)
      );

      // Right Box: Prompt Cards
      const promptTa = h('textarea', { rows: 8 }, data.kuncian_prompt?.video_prompt || '');
      const copyPromptBtn = h('button', { class: 'btn-copy', type: 'button', onclick: () => copyText(promptTa.value, copyPromptBtn) }, '📋 Salin Prompt Flow (ALIPYOU)');

      const voTa = h('textarea', { rows: 3 }, data.kuncian_prompt?.voiceover || '');
      const copyVoBtn = h('button', { class: 'btn-copy', type: 'button', onclick: () => copyText(voTa.value, copyVoBtn) }, '📋 Salin Naskah VO');

      const capTa = h('textarea', { rows: 3 }, data.caption || '');
      const copyCapBtn = h('button', { class: 'btn-copy', type: 'button', onclick: () => copyText(capTa.value, copyCapBtn) }, '📋 Salin Caption');

      const promptPanel = h('div', { class: 'prompt-panel' },
        h('div', { class: 'prompt-card' },
          h('div', { class: 'prompt-card-header' },
            h('span', {}, `🤖 Kuncian Prompt ALIPYOU AUTO POST · ${data.kuncian_prompt?.category || 'Review'} (${data.kuncian_prompt?.template_id || 'TungTung'})`),
            copyPromptBtn
          ),
          promptTa
        ),
        h('div', { class: 'prompt-card' },
          h('div', { class: 'prompt-card-header' },
            h('span', {}, '🎙️ Naskah Narasi / Hook Ringkas'),
            copyVoBtn
          ),
          voTa
        ),
        h('div', { class: 'prompt-card' },
          h('div', { class: 'prompt-card-header' },
            h('span', {}, '📝 Caption & Hashtags Shopee Video'),
            copyCapBtn
          ),
          capTa
        )
      );

      previewContainer.append(leftBox, promptPanel);
    }

    btnScrape.addEventListener('click', async () => {
      const url = shopeeLinkIn.value.trim();
      if (!url) { toast('Harap tempel link produk Shopee terlebih dahulu', true); return; }
      btnScrape.disabled = true;
      btnScrape.textContent = '⏳ Mengambil data...';
      try {
        const res = await api('/api/shopee/extract', 'POST', { url, category: promptCatSel.value });
        if (!res.success) throw new Error('Gagal mengekstrak produk');
        currentExtractedData = res;
        renderExtractedPreview(res);
        if (res.kuncian_prompt?.video_prompt) {
          navigator.clipboard.writeText(res.kuncian_prompt.video_prompt).catch(() => {});
          toast(`✓ Bahan siap & Kuncian Prompt ALIPYOU otomatis disalin ke clipboard! (Tinggal paste di Google Flow)`);
        } else {
          toast(`Bahan & Kuncian Prompt ALIPYOU siap! Silakan salin prompt ke Google Flow.`);
        }
      } catch (err) {
        toast(`Gagal mengambil data Shopee: ${err.message}`, true);
      } finally {
        btnScrape.disabled = false;
        btnScrape.textContent = '🔍 Ambil Bahan & Kuncian Prompt';
      }
    });

    shopeeLinkIn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        btnScrape.click();
      }
    });

    const btnSaveNext = h('button', { class: 'btn primary', style: 'padding: 8px 18px; font-weight: 700; font-size: 13.5px;' },
      `🚀 Simpan Tugas & Lanjut ke Akun Berikutnya`);

    btnSaveNext.addEventListener('click', () => act(async () => {
      const username = opAcctSel.value;
      if (!username) throw new Error('Pilih akun target');
      const videoUrl = flowVideoIn.value.trim();
      if (!videoUrl) throw new Error('Harap tempel link video Google Flow atau path video');
      const shopeeUrl = shopeeLinkIn.value.trim();

      const cap = currentExtractedData ? currentExtractedData.caption : null;
      const prompt = currentExtractedData ? currentExtractedData.kuncian_prompt?.video_prompt : null;
      const prodLink = currentExtractedData ? currentExtractedData.canonical_url : shopeeUrl;

      await api('/api/tasks/operator', 'POST', {
        username,
        video_url: videoUrl,
        product_link: prodLink || null,
        caption: cap || null,
        prompt: prompt || null
      });

      const currentIdx = opAcctSel.selectedIndex;
      const nextIdx = (currentIdx + 1) < accts.length ? currentIdx + 1 : 0;
      const prevKode = accts[currentIdx]?.kode || username;
      const nextKode = accts[nextIdx]?.kode || 'Selesai';

      // Reset input form
      shopeeLinkIn.value = '';
      flowVideoIn.value = '';
      resetVideoSelection();
      currentExtractedData = null;
      previewContainer.style.display = 'none';

      // Advance to next account!
      opAcctSel.selectedIndex = nextIdx;
      updateOpProg();
      shopeeLinkIn.focus();

      toast(`✓ Tugas ${prevKode} (@${username}) berhasil disimpan! Sekarang giliran ${nextKode}.`);
      await refreshTasks();
    }));

    if (accts.length > 0) updateOpProg();

    const studioSection = h('section', { class: 'studio-box' },
      h('div', { class: 'studio-header' },
        h('div', { class: 'studio-title' },
          '🎬 Studio Operator: Input Cepat Tugas per Akun (Flow + Shopee)'
        ),
        opAcctProg
      ),
      h('div', { class: 'row' },
        h('label', { style: 'font-weight: 600;' }, 'Akun Target:'),
        opAcctSel
      ),
      h('div', { class: 'row' },
        shopeeLinkIn,
        h('label', { style: 'font-size: 12.5px; font-weight: 600;' }, 'Kategori Prompt:'),
        promptCatSel,
        btnScrape
      ),
      previewContainer,
      h('div', { style: 'margin-top: 14px;' },
        h('label', { style: 'font-weight: 700; font-size: 13px; color: #1e293b; margin-bottom: 6px; display: block;' },
          'Unggah Berkas Video Shopee (Dropzone 9:16) atau Tautan Google Flow:'
        ),
        dropzoneContainer,
        h('div', { class: 'row', style: 'margin-top: 10px;' },
          flowVideoIn,
          btnSaveNext
        )
      ),
      h('p', { class: 'hint', style: 'margin: 6px 0 0;' },
        '💡 Alur: Tempel link Shopee → Klik Ambil Bahan → Salin Foto & Kuncian Prompt ke Google Flow → Tarik file video MP4 ke dropzone (atau tempel link video Flow) → Klik Simpan & Lanjut ke Akun Berikutnya.'
      )
    );

    tasksBox = h('div', {});

    let currentQueueFilter = '';
    const queueFilterPills = h('div', { class: 'pill-chips', style: 'margin: 10px 0 14px;' },
      h('div', { class: 'pill-chip active', onclick: (e) => setQueueFilter('', e.currentTarget) }, '🔘 Semua'),
      h('div', { class: 'pill-chip', onclick: (e) => setQueueFilter('NEEDS_OPERATOR', e.currentTarget) }, '⚠️ Butuh Operator'),
      h('div', { class: 'pill-chip', onclick: (e) => setQueueFilter('QUEUED', e.currentTarget) }, '⏳ Antre Siap Post'),
      h('div', { class: 'pill-chip', onclick: (e) => setQueueFilter('FAILED', e.currentTarget) }, '❌ Gagal')
    );

    function setQueueFilter(status, el) {
      currentQueueFilter = status;
      queueFilterPills.querySelectorAll('.pill-chip').forEach(c => c.classList.remove('active'));
      el.classList.add('active');
      refreshTasks(currentQueueFilter);
    }

    const queueSection = h('section', { class: 'queue-box' },
      h('div', { class: 'queue-header' },
        h('div', { class: 'queue-title' }, '📋 Tugas Aktif & Antrean Posting Auto-Pilot'),
        h('div', { style: 'display: flex; gap: 10px; align-items: center; flex-wrap: wrap;' },
          btnAutoPilot,
          h('label', { style: 'font-size: 13px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 6px;' },
            autoNextCb, 'Auto-Lanjut Tugas Selanjutnya'
          )
        )
      ),
      autoPilotBanner,
      queueFilterPills,
      tasksBox
    );

    const batchDetails = h('details', { class: 'collapse-box' },
      h('summary', { class: 'collapse-summary' },
        h('span', {}, '📦 Mode Batch Masal & Pendaftaran Video PC (Opsional / Lanjutan)'),
        h('span', { class: 'hint' }, '▼ Klik untuk buka/tutup')
      ),
      h('div', { class: 'collapse-content' },
        h('h3', { style: 'font-size: 13.5px; font-weight: 700; margin: 0 0 10px;' }, `Pilih Akun Sekaligus (${accts.length} akun terdaftar)`),
        h('div', { class: 'row' }, h('label', {}, 'Video: ', vidSel), batch, caption),
        toolbar,
        batchFilterPills,
        listWrap,
        h('div', { class: 'row', style: 'margin-top: 10px;' }, create),
        h('hr', { style: 'margin: 16px 0; border: none; border-top: 1px dashed var(--line);' }),
        h('h3', { style: 'font-size: 13.5px; font-weight: 700; margin: 0 0 10px;' }, 'Daftarkan Master Video dari PC'),
        h('div', { class: 'row' }, vidId, vidPath, addVideo)
      )
    );

    main.replaceChildren(
      queueSection,
      studioSection,
      batchDetails
    );
    listWrap.scrollTop = 0;
    await refreshTasks();
  }

  let activeQueueFilter = '';
  async function refreshTasks(filterStatus) {
    if (filterStatus !== undefined) activeQueueFilter = filterStatus;
    if (!tasksBox || !tasksBox.isConnected) return;
    const busy = [...tasksBox.querySelectorAll('input')].some(i => i === document.activeElement || i.value);
    if (busy) return;
    const all = await api('/tasks');
    const today = new Date().toISOString().slice(0, 10);
    let live = all.filter(t => ['QUEUED', 'PREPARING', 'NEEDS_OPERATOR', 'PAUSED', 'REVIEW_REQUIRED'].includes(t.status) ||
      (t.status === 'FAILED' && (t.finished_at || '').startsWith(today)));

    if (activeQueueFilter) {
      live = live.filter(t => {
        if (activeQueueFilter === 'NEEDS_OPERATOR') return t.status === 'NEEDS_OPERATOR' || t.status === 'REVIEW_REQUIRED';
        if (activeQueueFilter === 'QUEUED') return t.status === 'QUEUED' || t.status === 'PREPARING';
        if (activeQueueFilter === 'FAILED') return t.status === 'FAILED';
        return true;
      });
    }

    if (!live.length) {
      tasksBox.replaceChildren(createEmptyState({
        icon: '🎬',
        title: 'Antrean Tugas Kosong',
        desc: activeQueueFilter
          ? 'Tidak ada tugas yang sesuai dengan filter ini.'
          : 'Tidak ada tugas aktif atau antrean saat ini. Buat tugas baru melalui Studio Operator di bawah atau sinkronkan data akun dari Google Sheets.',
        actionText: '🔄 Sinkronkan Google Sheets Sekarang',
        onAction: () => show('pengaturan')
      }));
    } else {
      tasksBox.replaceChildren(...live.map(taskCard));
    }

    const qBadge = document.getElementById('queueBadge');
    if (qBadge) {
      const queuedCount = all.filter(t => ['QUEUED', 'PREPARING'].includes(t.status)).length;
      if (queuedCount > 0) {
        qBadge.textContent = queuedCount;
        qBadge.style.display = 'inline-block';
      } else {
        qBadge.style.display = 'none';
      }
    }
  }

  function taskCard(t) {
    const note = h('input', { placeholder: 'Catatan / alasan' });
    const ev = h('input', { placeholder: 'Bukti (nama file screenshot / link video)' });
    const confirm = h('input', { placeholder: 'Ketik username: ' + t.username });
    const vid = h('input', { placeholder: 'ID video Shopee (opsional)' });
    const tr = (to, extra = {}, ok = 'Status diperbarui') => act(() =>
      api(`/tasks/${t.id}/transition`, 'POST', { to, actor: 'operator', reason: note.value.trim(), ...extra }), ok);
    const btn = (label, fn, cls = '') => h('button', { class: 'btn ' + cls, onclick: fn }, label);

    const cancelAction = (reasonMsg = 'Dibatalkan oleh operator') => act(async () => {
      stopAutoPilot();
      toast(`Membatalkan tugas #${t.id} dan menghentikan Shopee di VMOS…`);
      await api(`/tasks/${t.id}/cancel`, 'POST', { reason: reasonMsg });
      toast(`✓ Tugas #${t.id} dibatalkan & Shopee di VMOS telah di-force stop!`);
      await refreshTasks();
    }, 'Tugas dibatalkan');

    const btnCancel = btn('Batal', () => {
      const r = prompt('Catatan pembatalan tugas:', note.value.trim() || 'Dibatalkan oleh operator');
      if (r === null) return;
      cancelAction(r.trim() || 'Dibatalkan oleh operator');
    }, 'danger');

    let body = [];
    if (t.status === 'QUEUED') {
      const btnRunFull = btn('🚀 Mulai Auto-Post Sekarang', async () => {
        toast(`Sedang memproses tugas #${t.id} (@${t.username}) secara penuh di VMOS…`);
        try {
          await api(`/tasks/${t.id}/run-full`, 'POST');
          toast(`✅ Berhasil auto-posting video untuk @${t.username}! (Ditonton 2 menit & Shopee di-force close)`);
          await refreshTasks();
          if (autoNextCb && autoNextCb.checked) {
            startAutoPilot();
          }
        } catch (e) {
          toast(`Gagal menjalankan tugas: ${e.message}`, true);
          await refreshTasks();
        }
      }, 'primary');
      body = [h('div', { class: 'row' }, btnRunFull, btn('Jeda', () => tr('PAUSED')), btnCancel)];
    } else if (t.status === 'PREPARING') {
      const btnRunFull = btn('🚀 Lanjutkan Auto-Post', async () => {
        toast(`Melanjutkan tugas #${t.id} (@${t.username}) di VMOS…`);
        try {
          await api(`/tasks/${t.id}/run-full`, 'POST');
          toast(`✅ Berhasil auto-posting video untuk @${t.username}!`);
          await refreshTasks();
        } catch (e) {
          toast(`Gagal: ${e.message}`, true);
        }
      }, 'primary');
      body = [h('div', { class: 'row' }, btnRunFull, note, btnCancel)];
    } else if (t.status === 'NEEDS_OPERATOR') {
      const btnAutoPost = btn('⚡ Auto-Post Otomatis di VMOS', async () => {
        toast(`Sedang menjalankan auto-posting di device ${t.pad_code}… Mohon tunggu.`);
        try {
          await api(`/tasks/${t.id}/run-full`, 'POST');
          toast(`✅ Berhasil auto-posting video untuk @${t.username}! (Ditonton 2 menit & Shopee di-force close)`);
          await refreshTasks();
          if (autoNextCb && autoNextCb.checked) {
            startAutoPilot();
          }
        } catch (e) {
          toast(`Gagal auto-post: ${e.message}`, true);
        }
      }, 'good');
      body = [
        h('div', { class: 'banner' }, `Di device ${t.pad_code}: pastikan shop aktif @${t.username} (Me › Switch Shop). Klik tombol Auto-Post di bawah untuk posting otomatis.`),
        h('div', { class: 'row' }, btnAutoPost, btnCancel),
        h('div', { class: 'row' }, confirm, ev, vid),
        h('div', { class: 'row' }, note),
        h('div', { class: 'row' },
          btn('Berhasil diposting', () => {
            const conf = confirm.value.trim().replace(/^@/, '').toLowerCase();
            if (conf !== t.username.toLowerCase()) {
              toast(`Ketik username yang benar (@${t.username}) untuk konfirmasi`, true);
              confirm.focus();
              return;
            }
            if (!ev.value.trim()) {
              toast('Bukti posting (screenshot / link) wajib diisi', true);
              ev.focus();
              return;
            }
            tr('VERIFIED', { confirmed_username: confirm.value.trim(), evidence: ev.value.trim(), video_post_id: vid.value.trim() || null }, 'Terverifikasi');
          }, 'good'),
          btn('Tidak terposting', () => tr('FAILED')),
          btn('Tidak yakin', () => tr('REVIEW_REQUIRED')),
          btn('Jeda', () => tr('PAUSED')),
          btnCancel
        )
      ];
    } else if (t.status === 'PAUSED') {
      body = [h('div', { class: 'row' }, btn('Lanjut', () => tr(t.prev_status), 'primary'), btnCancel)];
    } else if (t.status === 'REVIEW_REQUIRED') {
      body = [
        h('div', { class: 'banner' }, 'Hasil belum pasti. Periksa profil @' + t.username + ' dulu. Jangan posting ulang sebelum jelas.'),
        h('div', { class: 'row' }, ev, vid, note),
        h('div', { class: 'row' },
          btn('Ternyata terposting', () => {
            if (!ev.value.trim()) {
              toast('Bukti posting wajib diisi saat menyelesaikan verifikasi', true);
              ev.focus();
              return;
            }
            if (!note.value.trim()) {
              const r = prompt('Catatan penyelesaian review wajib diisi:');
              if (!r) return;
              note.value = r;
            }
            tr('VERIFIED', { evidence: ev.value.trim(), video_post_id: vid.value.trim() || null }, 'Terverifikasi');
          }, 'good'),
          btn('Ternyata tidak terposting', () => {
            if (!note.value.trim()) {
              const r = prompt('Catatan alasan kegagalan wajib diisi:');
              if (!r) return;
              note.value = r;
            }
            tr('FAILED');
          }))];
    } else if (t.status === 'FAILED') {
      body = [h('div', { class: 'row' },
        btn('Coba lagi (retry)', () => tr('QUEUED', {}, 'Dikembalikan ke antrean'), 'primary'),
        t.device_file_path && ['NONE', 'FAILED'].includes(t.cleanup_status)
          ? btn('Hapus file di device', () => act(() => api(`/tasks/${t.id}/cleanup/request`, 'POST'), 'Pembersihan diminta')) : null)];
    }
    const extras = [];
    if (t.product_link) {
      const copyLinkBtn = h('button', { class: 'btn-copy', type: 'button', onclick: (e) => { e.stopPropagation(); copyText(t.product_link, copyLinkBtn); } }, '📋 Salin Link');
      extras.push(h('div', { class: 'pill-info' }, '🔗 Link Produk: ', h('a', { href: t.product_link, target: '_blank', style: 'color: #ee4d2d; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;' }, t.product_link), copyLinkBtn));
    }
    if (t.caption) {
      const copyCapBtn = h('button', { class: 'btn-copy', type: 'button', onclick: (e) => { e.stopPropagation(); copyText(t.caption, copyCapBtn); } }, '📋 Salin Caption');
      extras.push(h('div', { class: 'pill-info' }, '📝 Caption: ', h('span', { style: 'max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;' }, t.caption.slice(0, 36) + '...'), copyCapBtn));
    }
    if (t.prompt) {
      const copyPromptBtn = h('button', { class: 'btn-copy', type: 'button', onclick: (e) => { e.stopPropagation(); copyText(t.prompt, copyPromptBtn); } }, '📋 Salin Prompt Flow');
      extras.push(h('div', { class: 'pill-info' }, '🤖 Kuncian Prompt', copyPromptBtn));
    }

    return h('div', { class: 'card' },
      h('h3', {}, `#${t.id} · @${t.username} · video ${t.video_id} `, badge(t.status)),
      h('div', { class: 'hint' }, `Device ${t.pad_code} · batch ${t.batch || '-'} · percobaan ${t.attempt} · pembersihan: ${t.cleanup_status}` + (t.note ? ` · catatan: ${t.note}` : '')),
      ...(extras.length ? [h('div', { class: 'row', style: 'margin: 6px 0; gap: 8px;' }, ...extras)] : []),
      ...body);
  }

  // ---------------- Riwayat ----------------
  async function viewRiwayat() {
    const sel = h('select', { style: 'font-weight: 600;' },
      h('option', { value: '' }, 'Semua Status'),
      STATUSES.map(s => h('option', { value: s }, LABEL[s]))
    );
    const searchIn = h('input', { placeholder: 'Cari ID (#...), Username (@...), atau Device Pad Code...', style: 'flex: 1 1 240px;' });
    const countBadge = h('span', { class: 'badge', style: 'padding: 5px 10px; font-size: 12px;' });
    const detail = h('div', {});
    const tbl = h('div', {});
    let allRows = [];
    let currentRiwayatFilter = '';

    const filterPills = h('div', { class: 'pill-chips', style: 'margin: 6px 0 12px;' },
      h('div', { class: 'pill-chip active', onclick: (e) => setRiwayatFilter('', e.currentTarget) }, '🔘 Semua'),
      h('div', { class: 'pill-chip', onclick: (e) => setRiwayatFilter('NEEDS_OPERATOR', e.currentTarget) }, '⚠️ Butuh Operator'),
      h('div', { class: 'pill-chip', onclick: (e) => setRiwayatFilter('QUEUED', e.currentTarget) }, '⏳ Antre'),
      h('div', { class: 'pill-chip', onclick: (e) => setRiwayatFilter('FAILED', e.currentTarget) }, '❌ Gagal'),
      h('div', { class: 'pill-chip', onclick: (e) => setRiwayatFilter('VERIFIED', e.currentTarget) }, '✅ Selesai')
    );

    function setRiwayatFilter(st, el) {
      currentRiwayatFilter = st;
      filterPills.querySelectorAll('.pill-chip').forEach(c => c.classList.remove('active'));
      el.classList.add('active');
      renderFiltered();
    }

    function renderFiltered() {
      const q = searchIn.value.trim().toLowerCase();
      const filtered = allRows.filter(t => {
        if (currentRiwayatFilter) {
          if (currentRiwayatFilter === 'NEEDS_OPERATOR' && !['NEEDS_OPERATOR', 'REVIEW_REQUIRED'].includes(t.status)) return false;
          if (currentRiwayatFilter === 'QUEUED' && !['QUEUED', 'PREPARING'].includes(t.status)) return false;
          if (currentRiwayatFilter === 'FAILED' && !['FAILED', 'CANCELLED'].includes(t.status)) return false;
          if (currentRiwayatFilter === 'VERIFIED' && t.status !== 'VERIFIED') return false;
        }
        if (!q) return true;
        const text = `${t.id} ${t.username} ${t.pad_code} ${t.video_id || ''} ${t.status} ${t.batch || ''}`.toLowerCase();
        return text.includes(q);
      });
      countBadge.textContent = `${filtered.length} riwayat ditemukan`;

      if (!filtered.length) {
        tbl.replaceChildren(createEmptyState({
          icon: '📜',
          title: 'Riwayat Tugas Tidak Ditemukan',
          desc: q
            ? `Tidak ada tugas dengan kata kunci "${q}". Coba kata kunci lain atau pilih filter "Semua".`
            : 'Belum ada data tugas yang sesuai dengan kriteria penyaringan saat ini.',
          actionText: '👉 Buka Studio Posting',
          onAction: () => show('posting')
        }));
        return;
      }

      tbl.replaceChildren(h('div', { class: 'table-wrap' },
        h('table', { class: 'acct-table' },
          h('thead', {}, h('tr', {}, ['#ID', 'Username Akun', 'Device VMOS', 'Video', 'Status', 'Pembersihan', 'Waktu Dibuat'].map(x => h('th', {}, x)))),
          h('tbody', {}, filtered.map(t => h('tr', { class: 'click', onclick: () => showHistory(t) },
            h('td', { style: 'font-weight: 700;' }, `#${t.id}`),
            h('td', { style: 'font-weight: 600;' }, `@${t.username}`),
            h('td', {}, h('span', { class: 'badge-device' }, t.pad_code)),
            h('td', {}, t.video_id || 'Flow Video'),
            h('td', {}, badge(t.status)),
            h('td', { style: 'font-size: 12px; color: var(--mute);' }, t.cleanup_status || '—'),
            h('td', { style: 'font-size: 12px; color: var(--mute);' }, (t.created_at || '').replace('T', ' ').slice(0, 19))
          )))
        )
      ));
    }

    async function load() {
      tbl.replaceChildren(createSkeleton('row', 6));
      const rows = await api('/tasks' + (sel.value ? '?status=' + sel.value : ''));
      allRows = rows.slice().reverse();
      renderFiltered();
    }

    async function showHistory(t) {
      const hist = await api(`/tasks/${t.id}/history`);
      const screenshotUrl = `/api/tasks/${t.id}/screenshot?_t=${Date.now()}`;
      detail.replaceChildren(h('section', { style: 'margin-top: 18px;' },
        h('div', { style: 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;' },
          h('h2', { style: 'margin: 0;' }, `Riwayat Transisi Tugas #${t.id} (@${t.username})`),
          h('button', { class: 'btn', style: 'font-size: 12px; padding: 3px 8px;', onclick: () => detail.replaceChildren() }, '✖ Tutup Detail')
        ),
        h('div', { style: 'display: grid; grid-template-columns: 120px 1fr; gap: 16px; margin-bottom: 14px; align-items: center;' },
          h('div', {
            class: 'attention-thumb-wrap',
            style: 'width: 120px; height: 180px;',
            title: 'Klik untuk membuka tangkapan layar penuh',
            onclick: () => window.open(screenshotUrl, '_blank')
          },
            h('img', { class: 'attention-thumb', src: screenshotUrl, alt: 'Cuplikan Layar' })
          ),
          h('div', {},
            h('div', { style: 'font-weight: 700; font-size: 14px;' }, `#${t.id} · @${t.username} · VMOS ${t.pad_code}`),
            h('div', { style: 'margin: 4px 0;' }, badge(t.status)),
            h('div', { class: 'hint' }, `Catatan: ${t.note || '—'}`),
            h('div', { class: 'hint' }, `Pembersihan device: ${t.cleanup_status || '—'} · Percobaan: ${t.attempt}`)
          )
        ),
        h('div', { class: 'table-wrap' },
          h('table', { class: 'acct-table' },
            h('thead', {}, h('tr', {}, ['Waktu', 'Perubahan Status', 'Aktor', 'Alasan / Catatan'].map(x => h('th', {}, x)))),
            h('tbody', {}, hist.map(x => h('tr', {},
              h('td', { style: 'font-size: 12px;' }, (x.at || '').replace('T', ' ').slice(0, 19)),
              h('td', { style: 'font-weight: 600;' }, `${x.from_status || '—'} ➔ ${x.to_status}`),
              h('td', {}, x.actor),
              h('td', { style: 'font-size: 12.5px;' }, x.reason || '—')
            )))
          )
        )
      ));
      detail.scrollIntoView({ behavior: 'smooth' });
    }

    sel.addEventListener('change', load);
    searchIn.addEventListener('input', renderFiltered);

    main.replaceChildren(
      h('section', {},
        h('h2', {}, 'Riwayat Tugas Posting Shopee Video'),
        h('div', { class: 'toolbar' },
          sel,
          searchIn,
          countBadge
        ),
        filterPills,
        tbl
      ),
      detail
    );
    await load();
  }

  // ---------------- Pengaturan ----------------
  async function viewPengaturan() {
    const cfg = await api('/config');
    const out = h('div', {});
    const tableContainer = h('div', {});

    // --- 0. Pengaturan API VMOS Cloud ---
    let vmosConfig = { access_key: '', secret_key: '', base_url: 'https://api.vmoscloud.com', ready: false };
    try {
      vmosConfig = await api('/api/vmos/config');
    } catch (_) {}

    const vmosStatusBadge = h('span', {
      class: 'badge',
      style: vmosConfig.ready
        ? 'background: #dcf3e5; color: #1f9d55; font-size: 12px; padding: 4px 10px; font-weight: 600;'
        : 'background: #f1f5f9; color: #64748b; font-size: 12px; padding: 4px 10px; font-weight: 600;'
    }, vmosConfig.ready ? '🟢 VMOS Siap Digunakan' : '⚪ Belum Terhubung');

    const akInput = h('input', {
      type: 'text',
      placeholder: 'Masukkan Access Key ID (mis. ZdWwUF99di4WfaFfBRwGPky1jEJWs9bT)',
      value: vmosConfig.access_key || '',
      style: 'width: 100%; font-family: monospace; font-size: 13px;'
    });

    const skInput = h('input', {
      type: 'password',
      placeholder: 'Masukkan Secret Access Key (mis. FTopsjQgLBBslfz6QOMeRQzb)',
      value: vmosConfig.secret_key || '',
      style: 'width: 100%; font-family: monospace; font-size: 13px;'
    });

    const btnEye = h('button', {
      type: 'button',
      class: 'btn-toggle-eye',
      title: 'Tampilkan/Sembunyikan Secret Key',
      onclick: () => {
        if (skInput.type === 'password') {
          skInput.type = 'text';
          btnEye.textContent = '🙈';
        } else {
          skInput.type = 'password';
          btnEye.textContent = '👁️';
        }
      }
    }, '👁️');

    const urlInput = h('input', {
      type: 'text',
      placeholder: 'https://api.vmoscloud.com',
      value: vmosConfig.base_url || 'https://api.vmoscloud.com',
      style: 'width: 100%; font-family: monospace; font-size: 13px;'
    });

    const vmosFeedback = h('div', {});

    const btnTestVmos = h('button', {
      class: 'btn',
      style: 'font-weight: 600; padding: 7px 16px;',
      onclick: async () => {
        const ak = akInput.value.trim();
        const sk = skInput.value.trim();
        const burl = urlInput.value.trim() || 'https://api.vmoscloud.com';
        if (!ak || !sk) {
          toast('Access Key ID dan Secret Access Key harus diisi!', true);
          return;
        }
        btnTestVmos.disabled = true;
        btnTestVmos.textContent = '⏳ Menguji Koneksi...';
        vmosFeedback.replaceChildren(h('div', { class: 'banner', style: 'background: #f0f7ff; border-color: #bcd9ff; color: #0c5460;' },
          '⏳ Menguji kredensial ke server API VMOS Cloud... Mohon tunggu.'));
        try {
          const res = await api('/api/vmos/test', 'POST', { access_key: ak, secret_key: sk, base_url: burl });
          if (res.ok) {
            vmosFeedback.replaceChildren(h('div', { class: 'banner', style: 'background: #e8f5e9; border-color: #2e7d32; color: #1b5e20; font-weight: 600;' },
              `✅ ${res.msg}`));
            toast('Koneksi ke API VMOS Cloud Berhasil!');
          } else {
            vmosFeedback.replaceChildren(h('div', { class: 'banner bad', style: 'font-weight: 600;' },
              `❌ ${res.msg}`));
            toast(res.msg, true);
          }
        } catch (e) {
          vmosFeedback.replaceChildren(h('div', { class: 'banner bad' }, `❌ Gagal menghubungi backend: ${e.message}`));
          toast(e.message, true);
        } finally {
          btnTestVmos.disabled = false;
          btnTestVmos.textContent = '🔍 Uji Koneksi API VMOS';
        }
      }
    }, '🔍 Uji Koneksi API VMOS');

    const btnSaveVmos = h('button', {
      class: 'btn primary',
      style: 'font-weight: 600; padding: 7px 18px;',
      onclick: async () => {
        const ak = akInput.value.trim();
        const sk = skInput.value.trim();
        const burl = urlInput.value.trim() || 'https://api.vmoscloud.com';
        if (!ak || !sk) {
          toast('Access Key ID dan Secret Access Key tidak boleh kosong!', true);
          return;
        }
        btnSaveVmos.disabled = true;
        btnSaveVmos.textContent = '💾 Menyimpan...';
        try {
          const res = await api('/api/vmos/config', 'POST', { access_key: ak, secret_key: sk, base_url: burl });
          if (res.ok) {
            vmosFeedback.replaceChildren(h('div', { class: 'banner', style: 'background: #e8f5e9; border-color: #2e7d32; color: #1b5e20; font-weight: 600;' },
              `✅ ${res.msg}`));
            toast('Pengaturan API VMOS berhasil disimpan & diaktifkan!');
            vmosStatusBadge.textContent = '🟢 VMOS Siap Digunakan';
            vmosStatusBadge.style.background = '#dcf3e5';
            vmosStatusBadge.style.color = '#1f9d55';
            updateHeaderMode();
          } else {
            toast(res.msg || 'Gagal menyimpan konfigurasi VMOS', true);
          }
        } catch (e) {
          toast(e.message, true);
        } finally {
          btnSaveVmos.disabled = false;
          btnSaveVmos.textContent = '💾 Simpan Pengaturan VMOS';
        }
      }
    }, '💾 Simpan Pengaturan VMOS');

    const vmosSection = h('section', { class: 'vmos-box' },
      h('div', { class: 'vmos-header' },
        h('div', { class: 'vmos-title' }, '🌐 Hubungkan API VMOS Cloud (Akun Cloud Phone)'),
        vmosStatusBadge
      ),
      h('p', { class: 'hint', style: 'margin-top: 0; margin-bottom: 14px;' },
        'Setiap pengguna dapat menghubungkan akun VMOS Cloud masing-masing dengan memasukkan Access Key ID dan Secret Access Key. Kredensial akan disimpan secara aman dan otomatis menghubungkan ADB ke ponsel cloud Anda.'),
      h('div', { class: 'form-group' },
        h('label', {}, 'Access Key ID:'),
        akInput
      ),
      h('div', { class: 'form-group' },
        h('label', {}, 'Secret Access Key:'),
        h('div', { class: 'input-with-action' }, skInput, btnEye)
      ),
      h('div', { class: 'form-group', style: 'margin-bottom: 14px;' },
        h('label', {}, 'API Base URL (Default: https://api.vmoscloud.com):'),
        urlInput
      ),
      h('div', { class: 'row', style: 'gap: 10px; margin-top: 10px;' },
        btnTestVmos,
        btnSaveVmos
      ),
      vmosFeedback,
      h('div', { style: 'background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 12px; margin-top: 14px; font-size: 12.5px; color: #475569;' },
        h('b', { style: 'color: #1e293b;' }, '💡 Cara Mendapatkan Kredensial VMOS Cloud:'),
        h('ol', { style: 'margin: 6px 0 0; padding-left: 18px; line-height: 1.5;' },
          h('li', {}, 'Buka website resmi VMOS Cloud di ', h('a', { href: 'https://www.vmoscloud.com', target: '_blank', style: 'color: #2563eb; text-decoration: underline;' }, 'vmoscloud.com'), ' dan login ke akun Anda.'),
          h('li', {}, 'Buka menu Profil Pengguna / User Center → API Management (atau Kunci Akses / Access Keys).'),
          h('li', {}, 'Buat atau salin Access Key ID dan Secret Access Key, lalu tempelkan pada kolom di atas dan klik "Simpan Pengaturan VMOS".')
        )
      )
    );

    function renderAccountTable(accts) {
      if (!accts || !accts.length) {
        return createEmptyState({
          icon: '👥',
          title: 'Belum Ada Akun Shopee yang Dimuat',
          desc: 'Daftar akun masih kosong. Masukkan link Google Sheet Anda pada form di atas dan klik tombol "Update List (Muat Akun)".',
          actionText: '🔄 Sinkronkan Google Sheets Sekarang',
          onAction: () => syncUrlBtn.click()
        });
      }
      accts.sort((a, b) => {
        const na = parseInt((a.kode || '').replace(/\D+/g, '') || '0', 10);
        const nb = parseInt((b.kode || '').replace(/\D+/g, '') || '0', 10);
        return na - nb || (a.kode || '').localeCompare(b.kode || '');
      });

      const permCount = accts.filter(a => ['PERMANEN', 'BANNED'].includes((a.status_akun || '').toUpperCase())).length;
      const normalCount = accts.length - permCount;

      let currentAccountFilter = '';
      const filterPills = h('div', { class: 'pill-chips', style: 'margin: 6px 0 10px;' },
        h('div', { class: 'pill-chip active', onclick: (e) => setAccountFilter('', e.currentTarget) }, `🔘 Semua (${accts.length})`),
        h('div', { class: 'pill-chip', onclick: (e) => setAccountFilter('NORMAL', e.currentTarget) }, `🟢 Normal (${normalCount})`),
        h('div', { class: 'pill-chip', onclick: (e) => setAccountFilter('PERMANEN', e.currentTarget) }, `🔴 Banned/Permanen (${permCount})`)
      );

      function setAccountFilter(st, el) {
        currentAccountFilter = st;
        filterPills.querySelectorAll('.pill-chip').forEach(c => c.classList.remove('active'));
        el.classList.add('active');
        applyAccountFilter();
      }

      const searchIn = h('input', { placeholder: 'Cari Kode, Username, atau Pad Code...', style: 'flex: 1 1 200px;' });
      const countBadge = h('span', { class: 'badge', style: 'font-size: 12.5px; padding: 4px 10px;' }, `${accts.length} Akun Terdaftar`);

      const rows = accts.map((a, idx) => {
        const isPerm = (a.status_akun || '').toUpperCase() === 'PERMANEN' || (a.status_akun || '').toUpperCase() === 'BANNED';
        const statusBadge = isPerm
          ? h('span', { class: 'badge-status permanen' }, 'PERMANEN')
          : h('span', { class: 'badge-status normal' }, a.status_akun || 'NORMAL');

        const tr = h('tr', {},
          h('td', { style: 'width: 45px; text-align: center; color: var(--mute); font-size: 12px;' }, idx + 1),
          h('td', { style: 'width: 95px; font-weight: 600;' }, a.kode),
          h('td', { style: 'font-weight: 500;' }, `@${a.username}`),
          h('td', {}, h('span', { class: 'badge-device' }, a.pad_code)),
          h('td', { style: 'font-weight: 600; text-align: center;' }, a.label ? `VMOS ${a.label}` : '—'),
          h('td', {}, statusBadge)
        );
        return { a, tr, isPerm, text: `${idx + 1} ${a.kode} ${a.username} ${a.pad_code} ${a.label || ''} ${a.status_akun || ''}`.toLowerCase() };
      });

      function applyAccountFilter() {
        const q = searchIn.value.trim().toLowerCase();
        let visibleCount = 0;
        rows.forEach(r => {
          let matchStatus = true;
          if (currentAccountFilter === 'NORMAL') matchStatus = !r.isPerm;
          else if (currentAccountFilter === 'PERMANEN') matchStatus = r.isPerm;
          const matchSearch = !q || r.text.includes(q);
          const show = matchStatus && matchSearch;
          r.tr.style.display = show ? '' : 'none';
          if (show) visibleCount++;
        });
        countBadge.textContent = `${visibleCount} dari ${accts.length} Akun`;
      }

      searchIn.addEventListener('input', applyAccountFilter);

      return h('div', {},
        h('div', { class: 'toolbar', style: 'margin-top: 10px;' },
          searchIn,
          countBadge
        ),
        filterPills,
        h('div', { class: 'table-wrap acct-wrap', style: 'max-height: 420px;' },
          h('table', { class: 'acct-table' },
            h('thead', {}, h('tr', {},
              h('th', { style: 'width: 45px; text-align: center;' }, 'No'),
              h('th', { style: 'width: 95px;' }, 'Kode'),
              h('th', {}, 'Username Shopee'),
              h('th', {}, 'VMOS Pad Code'),
              h('th', { style: 'text-align: center;' }, 'VMOS'),
              h('th', {}, 'Status Akun')
            )),
            h('tbody', {}, rows.map(r => r.tr))
          )
        )
      );
    }

    async function loadCurrentAccounts() {
      try {
        tableContainer.replaceChildren(createSkeleton('row', 5));
        const accts = await api('/accounts');
        tableContainer.replaceChildren(renderAccountTable(accts));
      } catch (e) {
        tableContainer.replaceChildren(h('p', { class: 'hint' }, 'Gagal membaca daftar akun: ' + e.message));
      }
    }

    // 1. Google Sheets via Link (Utama)
    const defaultUrl = localStorage.getItem('sheet_url') || 'https://docs.google.com/spreadsheets/d/17bQC4dF0C3f21Y3IdCS50cVC4w87HvSjvnm2_IK4af8/edit?gid=898202278#gid=898202278';
    const gSheetUrl = h('input', {
      placeholder: 'Paste link Google Sheet di sini (https://docs.google.com/spreadsheets/d/...)',
      value: defaultUrl,
      style: 'flex: 1;'
    });
    const gSheetRows = h('input', {
      placeholder: 'Mis. 2-50 (atau kosongkan untuk semua)',
      value: localStorage.getItem('sheet_rows') || '2-50',
      style: 'max-width: 220px;'
    });

    const clearPrevCb = h('input', { type: 'checkbox', id: 'clearPrevCb', checked: true });
    const clearPrevLabel = h('label', { for: 'clearPrevCb', style: 'font-weight: 500; cursor: pointer; display: flex; align-items: center; gap: 6px;' },
      clearPrevCb, 'Bersihkan & ganti total akun & tugas sebelumnya (Fresh Update)');

    const filterActiveCb = h('input', { type: 'checkbox', id: 'filterActiveCb', checked: true });
    const filterActiveLabel = h('label', { for: 'filterActiveCb', style: 'font-weight: 500; cursor: pointer; display: flex; align-items: center; gap: 6px;' },
      filterActiveCb, 'Hanya muat akun aktif (lewati status PERMANEN / Banned)');

    const syncUrlBtn = h('button', { class: 'btn primary', style: 'font-weight: 600; padding: 7px 16px;', onclick: async () => {
      const url = gSheetUrl.value.trim();
      if (!url) { toast('Link Google Sheet tidak boleh kosong', true); return; }
      const row_range = gSheetRows.value.trim() || null;
      localStorage.setItem('sheet_url', url);
      if (row_range) localStorage.setItem('sheet_rows', row_range);
      else localStorage.removeItem('sheet_rows');

      tableContainer.replaceChildren(h('div', { class: 'banner', style: 'background: #f0f7ff; border-color: #bcd9ff; color: #0c5460; text-align: center; padding: 18px;' },
        '⏳ Mengunduh dan membaca data terbaru dari Google Sheet… Mohon tunggu sebentar.'));

      toast(`Membaca Google Sheet ${row_range ? '(' + row_range + ')' : ''}…`);
      try {
        const r = await api('/sync/url', 'POST', {
          url,
          row_range,
          clear_previous: clearPrevCb.checked,
          filter_active_only: filterActiveCb.checked
        });
        out.replaceChildren(
          h('div', { class: 'banner', style: 'background: #e8f5e9; border-color: #2e7d32; color: #1b5e20;' },
            `✅ ${r.synced} akun (${r.range}) berhasil dimuat & daftar akun telah diperbarui secara bersih!`),
          h('div', { class: 'row', style: 'margin-top: 8px;' },
            h('button', { class: 'btn primary', onclick: () => show('posting') }, '👉 Buka Halaman Posting Sekarang')),
          ...(r.problems.length ? [
            h('p', { class: 'hint' }, `Catatan: ${r.problems.length} baris dilewati:`),
            h('div', { style: 'max-height: 140px; overflow-y: auto;' },
              r.problems.slice(0, 30).map(p => h('div', { class: 'banner' }, `Baris ${p[0]}: ${p[1]}`)))
          ] : [])
        );
        toast(`Berhasil update list ${r.synced} akun (${r.range})!`);
        await loadCurrentAccounts();
      } catch (e) {
        out.replaceChildren(h('div', { class: 'banner bad' }, `Gagal: ${e.message}`));
        toast(e.message, true);
        await loadCurrentAccounts();
      }
    } }, '🔄 Update List (Muat Akun)');

    const btnResetAll = h('button', {
      class: 'btn danger',
      style: 'font-weight: 600;',
      onclick: async () => {
        if (!confirm('Peringatan: Ini akan mengosongkan semua data akun dan riwayat tugas di aplikasi agar kembali bersih dari awal. Lanjutkan?')) return;
        try {
          await api('/api/reset-all', 'POST');
          toast('Semua data akun & riwayat tugas telah dikosongkan!');
          out.replaceChildren(h('div', { class: 'banner' }, '✅ Semua data akun & riwayat tugas lama telah dikosongkan bersih.'));
          await loadCurrentAccounts();
        } catch (e) {
          toast(e.message, true);
        }
      }
    }, '🗑️ Kosongkan Semua Data Lama');

    // 2. CSV Lokal (Alternatif)
    const csv = h('input', { placeholder: 'Path CSV lokal di PC (mis. D:\\data\\akun.csv)' });
    const syncCsv = h('button', { class: 'btn', onclick: async () => {
      try {
        if (!csv.value.trim()) { toast('Masukkan path file CSV', true); return; }
        const r = await api('/sync/csv', 'POST', { path: csv.value.trim() });
        out.replaceChildren(
          h('div', { class: 'banner' }, `✅ ${r.synced} akun disinkronkan dari CSV.`),
          ...r.problems.map(p => h('div', { class: 'banner' }, `Baris ${p[0]}: ${p[1]}`))
        );
        toast(`${r.synced} akun disinkronkan`);
        await loadCurrentAccounts();
      } catch (e) { toast(e.message, true); }
    } }, 'Sync CSV');

    // --- 3. Manajemen Penyimpanan & Log ---
    const storageBox = h('div', { class: 'card', style: 'background: #fbfbfd; border: 1px solid #e2e8f0; padding: 14px;' });
    const logBox = h('div', { style: 'margin-top: 10px; display: none;' });
    const logPre = h('pre', {
      style: 'background: #1e1e24; color: #a5d6a7; padding: 12px; border-radius: 6px; font-size: 11.5px; max-height: 280px; overflow-y: auto; font-family: monospace; white-space: pre-wrap;'
    });
    logBox.replaceChildren(
      h('div', { style: 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;' },
        h('b', { style: 'font-size: 12.5px;' }, 'Log Aktivitas Sistem (Terbaru):'),
        h('button', { class: 'btn', style: 'font-size: 11px; padding: 2px 8px;', onclick: () => { logBox.style.display = 'none'; } }, 'Tutup Log')
      ),
      logPre
    );

    function formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const k = 1024;
      const dm = 1;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    async function refreshStorageStats() {
      try {
        const s = await api('/api/storage/stats');
        storageBox.replaceChildren(
          h('div', { style: 'display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 12px;' },
            h('div', { class: 'pill-info' }, '🗄️ Database: ', h('b', {}, formatBytes(s.db_size_bytes))),
            h('div', { class: 'pill-info' }, '🎬 Cache Video: ', h('b', {}, `${formatBytes(s.cache_size_bytes)} (${s.cache_files_count} file)`)),
            h('div', { class: 'pill-info' }, '📜 Log Sistem: ', h('b', {}, formatBytes(s.log_size_bytes)))
          ),
          h('div', { class: 'row', style: 'gap: 8px;' },
            h('button', {
              class: 'btn',
              style: 'font-size: 12px;',
              onclick: async () => {
                if (!confirm('Hapus seluruh video di cache lokal? (Video di VMOS dan tugas di database tidak terpengaruh).')) return;
                try {
                  const res = await api('/api/storage/clean-cache', 'POST');
                  toast(`Berhasil membersihkan ${res.deleted} file cache (${formatBytes(res.freed_bytes)})`);
                  await refreshStorageStats();
                } catch (e) {
                  toast(e.message, true);
                }
              }
            }, '🧹 Bersihkan Cache Video Lokal'),
            h('button', {
              class: 'btn',
              style: 'font-size: 12px;',
              onclick: async () => {
                try {
                  const res = await api('/api/logs/recent');
                  logPre.textContent = (res.lines && res.lines.length) ? res.lines.join('\n') : 'Belum ada catatan log aktivitas.';
                  logBox.style.display = 'block';
                  logPre.scrollTop = logPre.scrollHeight;
                } catch (e) {
                  toast(e.message, true);
                }
              }
            }, '📋 Lihat Log Aktivitas (Live)')
          ),
          logBox
        );
      } catch (_) {}
    }
    refreshStorageStats();

    const storageSection = h('section', {},
      h('h2', {}, 'Manajemen Penyimpanan & Log Sistem'),
      h('p', { class: 'hint' }, 'Pantau pemakaian ruang penyimpanan database SQLite, file video sementara, dan log aktivitas.'),
      storageBox
    );

    // Inisialisasi daftar akun saat halaman dibuka
    loadCurrentAccounts();

    // --- 4. Flow AI Prompt Studio & Live Preview ---
    function createPromptStudio() {
      const PRESETS = [
        {
          name: '⭐ TungTung Review & UGC (Default Shopee)',
          prompt: 'Cinematic ultra-realistic product review video of {title}. High resolution 4k, vertical 9:16 mobile orientation, dynamic camera movement rotating 360 around the item on a clean modern studio desk with warm studio lighting. Authentic aesthetic, crisp textures, depth of field.',
          vo: 'Wajib banget punya ini! Review jujur {title} dari toko {shop}, kualitasnya beneran premium dan worth it banget buat kalian yang lagi nyari {category}. Cek keranjang kuning sekarang sebelum diskonnya habis!',
          caption: 'Rekomendasi terbaik buat kalian! {title} dari {shop}. Jangan sampai kehabisan diskon dan gratis ongkirnya ya! ✨ #racunshopee #shopeevideo #shopeehaul #spillracunshopee #rekomendasiproduk #viral #fyp'
        },
        {
          name: '💡 Problem - Solution Storytelling',
          prompt: 'Problem to solution storytelling commercial for {title}. Starting with frustrated expression solving everyday trouble, transitioning to satisfying smooth usage of {title} in bright aesthetic room, 9:16 portrait view, modern colors.',
          vo: 'Dulu sering banget kesel sama masalah ini, sampai akhirnya nemu {title}! Praktis banget dipakai sehari-hari, bener-bener ngebantu buat {category}. Buruan checkout di keranjang kuning di bawah ya!',
          caption: 'Solusi praktis anti ribet! {title} bikin hidup jadi lebih gampang. Yuk checkout sekarang sebelum voucher diskonnya hangus! 🔥 #solusipraktis #racunshopee #shopeefeed #racuntiktok #gadgetmurah'
        },
        {
          name: '🏷️ Flash Sale Promo & Value',
          prompt: 'Fast-paced trendy promotional showcase for {title}. Bright energetic lighting, macro close-up of fine craftsmanship and materials, smooth vertical panning 9:16, vibrant Shopee style.',
          vo: 'Harga semurah ini dapet barang sebagus {title}? Jangan kaget ya! Langsung klaim voucher diskon dan gratis ongkir sekarang juga di keranjang kuning!',
          caption: 'Flash sale termurah hari ini! {title} original bergaransi resmi dari {shop}. Klik keranjang kuning sekarang! 💥 #promoshopee #diskonspesial #shopeecheck #gratisongkir #murahlebay'
        },
        {
          name: '✨ POV Aesthetic & Minimalist',
          prompt: 'POV aesthetic lifestyle showcase of {title}. Soft natural morning sunlight pouring through window, wooden minimalist table, slow-motion gentle touch, ultra crisp 4k 9:16 vertical cinematography.',
          vo: 'Satu barang kecil yang bikin hari-hari lebih rapi dan aesthetic. Ini dia {title}. Simpel tapi fungsinya luar biasa. Cek keranjang kuning ya!',
          caption: 'Menambah sentuhan aesthetic di keseharianmu ✨ {title} dari {shop}. Checkout di keranjang kuning sekarang! #aesthetic #shopeelook #racunshopee #minimalist'
        }
      ];

      const sampleTitle = h('input', {
        value: localStorage.getItem('prompt_sample_title') || 'TWS Bluetooth 5.3 Earphone Bass Stereo Waterproof',
        placeholder: 'Judul Contoh Produk...',
        style: 'width: 100%; font-size: 13px;'
      });
      const sampleShop = h('input', {
        value: localStorage.getItem('prompt_sample_shop') || 'Official Store Indonesia',
        placeholder: 'Nama Toko...',
        style: 'width: 100%; font-size: 13px;'
      });
      const sampleCat = h('input', {
        value: localStorage.getItem('prompt_sample_cat') || 'Elektronik & Audio',
        placeholder: 'Kategori...',
        style: 'width: 100%; font-size: 13px;'
      });

      const promptTa = h('textarea', { rows: 5, style: 'width: 100%; font-size: 12px; font-family: monospace;' });
      const voTa = h('textarea', { rows: 4, style: 'width: 100%; font-size: 12px;' });
      const captionTa = h('textarea', { rows: 4, style: 'width: 100%; font-size: 12px;' });

      const presetSel = h('select', { style: 'font-weight: 600; width: 100%;' },
        PRESETS.map((p, idx) => h('option', { value: idx }, p.name))
      );

      function applyPreset(idx) {
        const p = PRESETS[idx] || PRESETS[0];
        promptTa.value = p.prompt;
        voTa.value = p.vo;
        captionTa.value = p.caption;
        updatePreview();
      }

      presetSel.addEventListener('change', () => applyPreset(parseInt(presetSel.value, 10)));

      const outPromptBox = h('div', { style: 'font-size: 12px; line-height: 1.45; color: #334155; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; max-height: 110px; overflow-y: auto; font-family: monospace; white-space: pre-wrap;' });
      const outVoBox = h('div', { style: 'font-size: 12px; line-height: 1.45; color: #1e293b; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; max-height: 90px; overflow-y: auto; white-space: pre-wrap;' });
      const mockCaptionBox = h('div', { class: 'mock-caption' });
      const mockProdTitle = h('span', { style: 'font-size: 11.5px; font-weight: 600; color: #f8fafc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; display: inline-block;' });

      const copyLivePromptBtn = h('button', {
        class: 'btn-copy',
        type: 'button',
        onclick: () => copyText(outPromptBox.textContent, copyLivePromptBtn)
      }, '📋 Salin');

      const copyLiveVoBtn = h('button', {
        class: 'btn-copy',
        type: 'button',
        onclick: () => copyText(outVoBox.textContent, copyLiveVoBtn)
      }, '📋 Salin');

      function updatePreview() {
        const title = sampleTitle.value.trim() || 'Produk Shopee';
        const shop = sampleShop.value.trim() || 'Toko Resmi';
        const cat = sampleCat.value.trim() || 'Rekomendasi';

        localStorage.setItem('prompt_sample_title', title);
        localStorage.setItem('prompt_sample_shop', shop);
        localStorage.setItem('prompt_sample_cat', cat);

        const fill = (text) => text
          .replace(/\{title\}/gi, title)
          .replace(/\{shop\}/gi, shop)
          .replace(/\{category\}/gi, cat);

        const renderedPrompt = fill(promptTa.value);
        const renderedVo = fill(voTa.value);
        const renderedCaption = fill(captionTa.value);

        outPromptBox.textContent = renderedPrompt;
        outVoBox.textContent = renderedVo;
        mockProdTitle.textContent = title;

        mockCaptionBox.replaceChildren();
        const parts = renderedCaption.split(/(\s+)/);
        parts.forEach(part => {
          if (part.startsWith('#') && part.length > 1) {
            mockCaptionBox.append(h('span', { class: 'tag-pill' }, part));
          } else {
            mockCaptionBox.append(document.createTextNode(part));
          }
        });
      }

      [sampleTitle, sampleShop, sampleCat, promptTa, voTa, captionTa].forEach(el => {
        el.addEventListener('input', updatePreview);
      });

      applyPreset(0);

      const phoneMockup = h('div', { class: 'phone-mockup' },
        h('div', { class: 'phone-screen' },
          h('div', { style: 'display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px;' },
            h('div', { style: 'display: flex; align-items: center; gap: 8px;' },
              h('div', { style: 'width: 28px; height: 28px; border-radius: 50%; background: #ee4d2d; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700;' }, 'S'),
              h('div', {},
                h('div', { style: 'font-size: 12px; font-weight: 700;' }, '@shopee_affiliate'),
                h('div', { style: 'font-size: 10px; color: #94a3b8;' }, 'Shopee Video Creator')
              )
            ),
            h('span', { style: 'background: #ee4d2d; color: #fff; font-size: 10.5px; padding: 3px 8px; border-radius: 12px; font-weight: 600;' }, '+ Ikuti')
          ),
          h('div', { style: 'height: 150px; background: linear-gradient(180deg, #1e293b, #0f172a); border-radius: 10px; display: flex; flex-direction: column; align-items: center; justify-content: center; position: relative; border: 1px solid #334155;' },
            h('div', { style: 'font-size: 36px; filter: drop-shadow(0 2px 8px rgba(238,77,45,0.4));' }, '▶️'),
            h('div', { style: 'font-size: 11px; color: #94a3b8; margin-top: 6px;' }, 'Format Video Vertikal (9:16)'),
            h('div', { style: 'position: absolute; right: 10px; bottom: 10px; display: flex; flex-direction: column; gap: 6px; align-items: center; font-size: 10px;' },
              h('div', { style: 'display: flex; flex-direction: column; align-items: center;' }, h('span', { style: 'font-size: 15px;' }, '❤️'), '14.8k'),
              h('div', { style: 'display: flex; flex-direction: column; align-items: center;' }, h('span', { style: 'font-size: 15px;' }, '💬'), '829'),
              h('div', { style: 'display: flex; flex-direction: column; align-items: center;' }, h('span', { style: 'font-size: 15px;' }, '↗️'), 'Bagikan')
            )
          ),
          h('div', { style: 'background: rgba(238,77,45,0.15); border: 1px solid rgba(238,77,45,0.4); border-radius: 6px; padding: 6px 10px; display: flex; align-items: center; gap: 8px;' },
            h('span', { style: 'font-size: 15px;' }, '🛒'),
            h('div', { style: 'display: flex; flex-direction: column; overflow: hidden;' },
              h('span', { style: 'font-size: 10px; color: #ff8a65; font-weight: 700;' }, 'KERANJANG KUNING SHOPEE'),
              mockProdTitle
            )
          ),
          mockCaptionBox
        )
      );

      const splitView = h('div', { class: 'split-view' },
        h('div', { class: 'editor-panel' },
          h('h3', { style: 'font-size: 14px; font-weight: 700; margin: 0; color: #1e293b;' }, '⚙️ Formula Prompt & Templat Variabel'),
          h('div', { class: 'form-group' },
            h('label', { style: 'font-weight: 600; font-size: 12.5px;' }, 'Pilih Preset Templat:'),
            presetSel
          ),
          h('div', { style: 'display: grid; grid-template-columns: 1fr 1fr; gap: 8px;' },
            h('div', {},
              h('label', { style: 'font-size: 11.5px; font-weight: 600;' }, 'Contoh Variabel {title}:'),
              sampleTitle
            ),
            h('div', {},
              h('label', { style: 'font-size: 11.5px; font-weight: 600;' }, 'Contoh Variabel {shop}:'),
              sampleShop
            )
          ),
          h('div', {},
            h('label', { style: 'font-size: 11.5px; font-weight: 600;' }, 'Contoh Variabel {category}:'),
            sampleCat
          ),
          h('div', {},
            h('label', { style: 'font-weight: 600; font-size: 12px; display: flex; justify-content: space-between;' },
              h('span', {}, '🎬 Templat Prompt Google Flow:'),
              h('span', { class: 'hint', style: 'font-size: 11px;' }, 'Pakai {title}, {shop}, {category}')
            ),
            promptTa
          ),
          h('div', {},
            h('label', { style: 'font-weight: 600; font-size: 12px;' }, '🎙️ Templat Naskah Voiceover / Hook:'),
            voTa
          ),
          h('div', {},
            h('label', { style: 'font-weight: 600; font-size: 12px;' }, '📝 Templat Caption & Hashtag Shopee:'),
            captionTa
          )
        ),
        h('div', { class: 'preview-panel' },
          h('h3', { style: 'font-size: 14px; font-weight: 700; margin: 0; color: #1e293b;' }, '📱 Pratinjau Langsung (Side-by-Side Live Preview)'),
          h('p', { class: 'hint', style: 'margin: 0; font-size: 12px;' }, 'Perubahan formula di sebelah kiri otomatis ter-render langsung ke cuplikan Shopee Video dan Google Flow:'),
          phoneMockup,
          h('div', { style: 'margin-top: 10px;' },
            h('div', { style: 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;' },
              h('b', { style: 'font-size: 12px; color: #1e293b;' }, '🎬 Hasil Prompt Google Flow:'),
              copyLivePromptBtn
            ),
            outPromptBox
          ),
          h('div', { style: 'margin-top: 8px;' },
            h('div', { style: 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;' },
              h('b', { style: 'font-size: 12px; color: #1e293b;' }, '🎙️ Hasil Voiceover / Hook:'),
              copyLiveVoBtn
            ),
            outVoBox
          )
        )
      );

      return h('section', {},
        h('h2', {}, 'Flow AI Prompt Studio & Live Preview'),
        h('p', { class: 'hint' }, 'Kembangkan dan uji templat prompt Google Flow serta caption Shopee Video secara berdampingan tanpa harus membuat tugas antrean terlebih dahulu:'),
        splitView
      );
    }

    const promptStudioSection = createPromptStudio();

    // --- 5. Online Update & Versi Aplikasi ---
    const updateFeedback = h('div', { style: 'margin-top: 10px;' });
    const btnCheckUpdate = h('button', {
      class: 'btn primary',
      style: 'font-weight: 600; padding: 7px 18px;',
      onclick: async () => {
        btnCheckUpdate.disabled = true;
        btnCheckUpdate.textContent = '⏳ Memeriksa ke GitHub...';
        updateFeedback.replaceChildren(h('div', { class: 'banner', style: 'background: #f0f7ff; color: #0c5460;' },
          '⏳ Menghubungi server GitHub untuk memeriksa versi rilis terbaru...'));
        try {
          const verInfo = await api('/api/version');
          const currentVer = verInfo.version || '1.0.0';
          const r = await fetch('https://api.github.com/repos/alkrnwn/alipyou-post-video/releases/latest', {
            headers: { 'Accept': 'application/vnd.github.v3+json' }
          });
          if (r.status === 404) {
            updateFeedback.replaceChildren(h('div', { class: 'banner', style: 'background: #e8f5e9; color: #1b5e20; font-weight: 600;' },
              `✓ Anda menggunakan versi terbaru (v${currentVer}). Belum ada rilis update baru di GitHub.`));
          } else if (r.ok) {
            const data = await r.json();
            const latestTag = (data.tag_name || '').replace(/^v/, '');
            if (latestTag && latestTag !== currentVer) {
              const downloadAsset = (data.assets || []).find(a => a.name.endsWith('.exe')) || { browser_download_url: data.html_url };
              updateFeedback.replaceChildren(h('div', { class: 'banner', style: 'background: #fffbeb; border-color: #f59e0b; color: #b45309;' },
                h('div', { style: 'font-size: 14px; font-weight: 700; margin-bottom: 6px;' }, `🎉 Pembaruan Tersedia: Versi ${data.tag_name}!`),
                h('div', { style: 'font-size: 12.5px; margin-bottom: 10px; color: #78350f;' }, data.body || 'Pembaruan stabilitas, perbaikan fitur, dan performa aplikasi.'),
                h('a', {
                  href: downloadAsset.browser_download_url || data.html_url,
                  target: '_blank',
                  class: 'btn primary',
                  style: 'text-decoration: none; display: inline-flex; align-items: center; gap: 6px; font-weight: 700;'
                }, `⬇️ Unduh Installer ${data.tag_name} (${downloadAsset.name || 'Setup .exe'})`)
              ));
            } else {
              updateFeedback.replaceChildren(h('div', { class: 'banner', style: 'background: #e8f5e9; color: #1b5e20; font-weight: 600;' },
                `✓ Aplikasi sudah dalam versi terbaru (v${currentVer}). Tidak ada pembaruan baru.`));
            }
          } else {
            throw new Error(`Server GitHub merespons status ${r.status}`);
          }
        } catch (e) {
          updateFeedback.replaceChildren(h('div', { class: 'banner bad' },
            `Gagal memeriksa pembaruan: ${e.message}. Buka halaman rilis resmi di ` +
            `https://github.com/alkrnwn/alipyou-post-video/releases`));
        } finally {
          btnCheckUpdate.disabled = false;
          btnCheckUpdate.textContent = '🔄 Periksa Pembaruan Sekarang';
        }
      }
    }, '🔄 Periksa Pembaruan Sekarang');

    const updateSection = h('section', { class: 'card', style: 'background: #ffffff; border: 1.5px solid var(--line); padding: 18px; border-radius: 12px; margin-top: 18px;' },
      h('div', { style: 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;' },
        h('h3', { style: 'font-size: 15px; font-weight: 700; margin: 0; display: flex; align-items: center; gap: 8px;' },
          '🌐 Pembaruan Aplikasi Online (Online Update)',
          h('span', { class: 'badge', style: 'background: #dbeafe; color: #1e40af; font-size: 11.5px; padding: 2px 8px;' }, 'v1.0.0')
        ),
        h('a', {
          href: 'https://github.com/alkrnwn/alipyou-post-video/releases',
          target: '_blank',
          class: 'btn',
          style: 'font-size: 12px; text-decoration: none;'
        }, '🔗 Halaman Rilis GitHub')
      ),
      h('p', { class: 'hint', style: 'margin: 0 0 12px; font-size: 13px;' },
        'Aplikasi dapat memeriksa versi pembaruan terbaru secara online langsung dari server repositori GitHub.'),
      h('div', { class: 'row', style: 'gap: 10px;' }, btnCheckUpdate),
      updateFeedback
    );

    main.replaceChildren(
      vmosSection,
      h('section', {},
        h('h2', {}, 'Muat Akun Shopee (Google Sheets)'),
        h('p', { class: 'hint' }, 'Paste link Google Sheet dan rentang baris (mis. 2-50, atau kosongkan untuk semua baris), lalu klik tombol Update List:'),
        h('div', { class: 'row' }, gSheetUrl),
        h('div', { class: 'row' },
          h('label', {}, 'Rentang baris: ', gSheetRows),
          syncUrlBtn,
          btnResetAll
        ),
        h('div', { class: 'row', style: 'margin-top: 10px; gap: 20px;' },
          clearPrevLabel,
          filterActiveLabel
        )
      ),
      out,
      h('section', {},
        h('h2', {}, 'Daftar Akun yang Dimuat'),
        tableContainer
      ),
      promptStudioSection,
      h('details', { class: 'collapse-box' },
        h('summary', { class: 'collapse-summary' },
          h('span', {}, '📁 Alternatif: Impor Akun dari File CSV Lokal PC'),
          h('span', { class: 'hint' }, '▼ Klik jika tidak memakai Google Sheet')
        ),
        h('div', { class: 'collapse-content' },
          h('p', { class: 'hint', style: 'margin-top: 0;' }, 'Gunakan opsi ini jika Anda ingin mengimpor akun langsung dari spreadsheet CSV di komputer:'),
          h('div', { class: 'row' }, csv, syncCsv)
        )
      ),
      h('p', { class: 'hint' }, 'Kolom yang dibaca otomatis: KODE, USERNAME, PAD CODE, VMOS, STATUS. Kolom kredensial pribadi (password, email, cookie) diabaikan demi privasi dan keamanan akun Anda.'),
      storageSection,
      updateSection,
      h('details', { class: 'collapse-box' },
        h('summary', { class: 'collapse-summary' },
          h('span', {}, '⚙️ Parameter Konfigurasi Sistem (Lanjutan / Advanced)'),
          h('span', { class: 'hint' }, '▼ Klik untuk melihat konfigurasi internal')
        ),
        h('div', { class: 'collapse-content' },
          h('div', { class: 'table-wrap' },
            h('table', { class: 'acct-table' },
              h('thead', {}, h('tr', {}, h('th', {}, 'Parameter'), h('th', {}, 'Nilai'))),
              h('tbody', {}, Object.entries(cfg).map(([k, v]) => h('tr', {},
                h('td', { style: 'font-weight: 600; font-family: monospace; font-size: 12.5px;' }, k),
                h('td', { style: 'font-family: monospace; font-size: 12.5px;' }, String(v))
              )))
            )
          )
        )
      )
    );
  }

  async function updateHeaderMode() {
    try {
      const [c, tasks] = await Promise.all([
        api('/config'),
        api('/tasks').catch(() => [])
      ]);
      const modeEl = document.getElementById('mode');
      if (modeEl) {
        if (c.dry_run) {
          modeEl.className = 'mode-pill dry-run';
          modeEl.replaceChildren(
            h('span', { class: 'status-dot pulse' }),
            document.createTextNode('Mode Uji (Dry-Run)')
          );
        } else if (c.adapter_ready) {
          modeEl.className = 'mode-pill ready';
          modeEl.replaceChildren(
            h('span', { class: 'status-dot pulse' }),
            document.createTextNode('VMOS Cloud Siap')
          );
        } else {
          modeEl.className = 'mode-pill not-ready';
          modeEl.replaceChildren(
            h('span', { class: 'status-dot' }),
            document.createTextNode('VMOS Belum Konek')
          );
        }
      }
      const qBadge = document.getElementById('queueBadge');
      if (qBadge) {
        const queuedCount = tasks.filter(t => ['QUEUED', 'PREPARING'].includes(t.status)).length;
        if (queuedCount > 0) {
          qBadge.textContent = queuedCount;
          qBadge.style.display = 'inline-block';
        } else {
          qBadge.style.display = 'none';
        }
      }
    } catch (_) {}
  }

  // ---------------- navigasi ----------------
  const VIEWS = { beranda: viewBeranda, posting: viewPosting, riwayat: viewRiwayat, pengaturan: viewPengaturan };
  async function refresh() { try { await VIEWS[view](); } catch (e) { toast(e.message, true); } }
  async function show(v) {
    view = v;
    document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('on', b.dataset.view === v));
    await refresh();
  }
  document.querySelectorAll('#nav button').forEach(b => b.addEventListener('click', () => show(b.dataset.view)));
  setInterval(() => {
    if (view === 'posting') refreshTasks().catch(() => {});
    updateHeaderMode().catch(() => {});
  }, 6000);
  updateHeaderMode();
  show('beranda');
})();
