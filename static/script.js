const $ = (id) => document.getElementById(id);
const f2 = (v) => Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

let sw = null; // latest seismic-weight result (feeds the base-shear part)

// ---------- Tabs ----------
function showTab(name) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
    window.scrollTo({ top: 0, behavior: 'smooth' });
}
document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
$('sw-to-bs').addEventListener('click', () => showTab('baseshear'));

// ---------- Shared POST helper ----------
async function post(url, payload, btn) {
    const original = btn.innerHTML;
    btn.innerHTML = '<span style="display:inline-block; animation: spin 1s linear infinite;">↻</span> Calculating...';
    btn.disabled = true;
    try {
        const r = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const j = await r.json();
        if (!r.ok) { alert('Error: ' + j.error); return null; }
        return j;
    } catch (err) {
        alert('Network Error: ' + err.message);
        return null;
    } finally {
        btn.innerHTML = original;
        btn.disabled = false;
    }
}

function reveal(section) {
    section.style.display = 'none';
    section.classList.remove('fade-in');
    void section.offsetWidth;
    section.style.display = 'block';
    section.classList.add('fade-in');
}

// ======================= PART 1: SEISMIC WEIGHT =======================
function buildRows() {
    const n = parseInt($('sw_N_floors').value, 10);
    const body = $('sw-floor-rows');
    const old = [...body.querySelectorAll('tr')].map(tr => ({
        h: tr.querySelector('.fl-h').value,
        LL: tr.querySelector('.fl-ll').value,
        st: tr.querySelector('.fl-st').checked
    }));
    body.innerHTML = '';
    if (!(n >= 1 && n <= 100)) return;
    for (let i = 0; i < n; i++) {
        const roof = i === n - 1;
        const o = old[i] || {};
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>Floor ${i + 1}${roof ? ' (Roof)' : ''}</td>
            <td><input type="number" class="fl-h" min="0.01" step="any" required value="${o.h ?? $('sw_h_all').value}"></td>
            <td><input type="number" class="fl-ll" min="0" step="any" required value="${o.LL ?? $('sw_LL_all').value}"></td>
            <td class="center"><input type="checkbox" class="fl-st" ${o.st ? 'checked' : ''}></td>`;
        body.appendChild(tr);
    }
}
$('sw_N_floors').addEventListener('input', buildRows);
$('sw-apply-all').addEventListener('click', () => {
    document.querySelectorAll('.fl-h').forEach(i => i.value = $('sw_h_all').value);
    document.querySelectorAll('.fl-ll').forEach(i => i.value = $('sw_LL_all').value);
});
buildRows();

$('sw-form').addEventListener('input', () => {
    if (sw) $('bs-stale').style.display = 'block';
});

$('sw-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(e.target).entries());
    payload.floors = [...$('sw-floor-rows').querySelectorAll('tr')].map(tr => ({
        h: tr.querySelector('.fl-h').value,
        LL: tr.querySelector('.fl-ll').value,
        stair: tr.querySelector('.fl-st').checked
    }));
    const res = await post('/calculate_seismic_weight', payload, e.target.querySelector('.btn-primary'));
    if (res) showSeismicWeight(res);
});

function showSeismicWeight(d) {
    sw = d;
    $('sw-tbody').innerHTML = d.rows.map(r => `
        <tr>
            <td>${r.floor}${r.roof ? ' (Roof)' : ''}</td>
            <td>${f2(r.level)}</td>
            <td>${f2(r.W_slab)}</td><td>${f2(r.W_beam)}</td><td>${f2(r.W_col)}</td>
            <td>${f2(r.W_wall)}</td><td>${f2(r.W_stair)}</td>
            <td>${f2(r.DL)}</td><td>${f2(r.LL_seismic)}</td>
            <td><strong>${f2(r.Ws_i)}</strong></td>
        </tr>`).join('');
    setText('sw-total', f2(d.Ws));
    setText('sw-badge', d.N + ' floor' + (d.N > 1 ? 's' : ''));
    reveal($('sw-result'));

    // Feed Part 2
    $('bs-source-body').innerHTML = d.rows.map(r => `
        <tr><td>${r.floor}${r.roof ? ' (Roof)' : ''}</td><td>${f2(r.level)}</td><td>${f2(r.Ws_i)}</td></tr>`).join('');
    setText('bs-source-total', f2(d.Ws));
    $('bs-source').style.display = 'block';
    $('bs-empty').style.display = 'none';
    $('bs-stale').style.display = 'none';
    $('bs-submit').disabled = false;
    $('bs-result').style.display = 'none';
}

// ======================= PART 2: BASE SHEAR =======================
$('bs-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!sw) { alert('Calculate the seismic weight first.'); return; }
    const payload = Object.fromEntries(new FormData(e.target).entries());
    payload.Ws_i = sw.rows.map(r => r.Ws_i);
    payload.h_i = sw.rows.map(r => r.level);
    const res = await post('/calculate_base_shear', payload, $('bs-submit'));
    if (res) showBaseShear(res);
});

function showBaseShear(d) {
    setText('bs-Z', d.Z);
    setText('bs-I', d.I);
    setText('bs-R', d.R);
    setText('bs-Sa', d.Sa_g);
    setText('bs-Ah', d.Ah);
    setText('bs-Ws', f2(d.Ws));
    setText('bs-Vb', f2(d.Vb));
    $('bs-tbody').innerHTML = d.rows.map(r => `
        <tr>
            <td>${r.floor}</td><td>${f2(r.h_i)}</td><td>${f2(r.Ws_i)}</td>
            <td>${f2(r.Wh2)}</td><td><strong>${f2(r.Q_i)}</strong></td><td>${f2(r.V_storey)}</td>
        </tr>`).join('');
    reveal($('bs-result'));
}

function setText(id, v) { $(id).textContent = v; }

// Spin animation for the loading state
const style = document.createElement('style');
style.innerHTML = '@keyframes spin { 100% { transform: rotate(360deg); } }';
document.head.appendChild(style);
