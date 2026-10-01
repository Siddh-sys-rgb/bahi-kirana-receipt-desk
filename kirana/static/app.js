const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const inr = value => new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR', maximumFractionDigits:2}).format(Number(value || 0));
const dateLabel = value => value ? new Date(value + 'T12:00:00').toLocaleDateString('en-IN', {day:'numeric', month:'short', year:'numeric'}) : 'Date to check';
const state = {csrf:'', filter:'all', input:'image', receipt:null, busy:false, routeVersion:0};

async function api(path, options = {}) {
  const headers = {...options.headers};
  if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  const response = await fetch(path, {...options, headers});
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || 'Something went wrong. Please retry.');
    error.data = data;
    throw error;
  }
  return data;
}
const jsonOptions = (method, body) => ({method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.remove('hidden');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => $('#toast').classList.add('hidden'), 4500);
}
function statusLabel(receipt) {
  if (receipt.status === 'review' && !receipt.checks.balanced) return ['mismatch', 'Check totals'];
  return [receipt.status, {review:'Ready to review', approved:'Approved', rejected:'Rejected'}[receipt.status]];
}
function card(receipt) {
  const [status, label] = statusLabel(receipt);
  const name = receipt.fields.merchant || 'Supplier to check';
  const initials = name.split(' ').slice(0,2).map(word => word[0]).join('');
  const source = receipt.source === 'demo-transcript' ? 'Sample bill' : receipt.source === 'rapidocr' ? 'Image upload' : 'Pasted text';
  return `<a class="bill-card" href="#review/${encodeURIComponent(receipt.id)}"><span class="bill-avatar">${esc(initials)}</span><span class="bill-main"><strong>${esc(name)}</strong><small>${esc(dateLabel(receipt.fields.purchase_date))} · ${source}</small></span><span class="bill-amount"><strong>${receipt.fields.total ? inr(receipt.fields.total) : 'Total to check'}</strong><span class="badge ${status}">${label}</span></span><span class="bill-arrow">↗</span></a>`;
}
function metric(label, value, note, icon, highlighted = false) {
  return `<article class="metric ${highlighted?'metric-highlight':''}"><span class="metric-label">${label}</span><strong>${value}</strong><small>${note}</small><span class="metric-icon">${icon}</span></article>`;
}
async function route() {
  const version = ++state.routeVersion;
  const hash = location.hash.slice(1) || 'dashboard';
  const name = hash.startsWith('review/') ? 'review' : ['dashboard','bills','ledger'].includes(hash) ? hash : 'dashboard';
  $$('.view').forEach(view => view.classList.toggle('hidden', view.id !== `${name}-view`));
  $$('[data-nav]').forEach(link => link.classList.toggle('active', link.dataset.nav === (name === 'review' ? 'bills' : name)));
  $('#page-label').textContent = {dashboard:'Overview', bills:'Bill inbox', ledger:'Purchase khata', review:'Review bill'}[name];
  try {
    if (name === 'review') {
      state.receipt = null;
      $('#review-title').textContent = 'Loading your bill…';
      $('.review-grid').classList.add('hidden');
      const [receipt, inbox] = await Promise.all([
        api('/api/receipts/' + encodeURIComponent(decodeURIComponent(hash.slice(7)))),
        api('/api/receipts?status=review')
      ]);
      if (version !== state.routeVersion) return;
      $('#nav-count').textContent = inbox.summary.pending;
      renderReview(receipt);
      const history = await api(`/api/receipts/${encodeURIComponent(receipt.id)}/events`);
      if (version !== state.routeVersion) return;
      $('#event-history').innerHTML = history.events.map(event => `<p>${esc({extracted:'Receipt added', review_saved:'Review changes saved', approved:'Approved into khata', rejected:'Bill rejected'}[event.action] || event.action)}<small>${esc(new Date(event.created_at).toLocaleString('en-IN'))}</small></p>`).join('');
      return;
    }
    const data = await api('/api/receipts?status=' + (name === 'bills' ? state.filter : 'all'));
    if (version !== state.routeVersion) return;
    $('#nav-count').textContent = data.summary.pending;
    if (name === 'dashboard') {
      $('#metrics').innerHTML = metric('Approved purchases', inr(data.summary.approved_total), 'Recorded in your khata', '₹', true)
        + metric('Bills to review', data.summary.pending, 'A quick check before posting', '▤')
        + metric('Bills accounted for', data.summary.approved_count, 'Reviewed & approved by you', '✓');
      const pending = data.receipts.filter(receipt => receipt.status === 'review');
      $('#pending-bills').innerHTML = pending.length ? pending.slice(0,4).map(card).join('') : '<div class="empty-state">All caught up. Add your next supplier bill when you’re ready.</div>';
    } else if (name === 'bills') {
      $('#all-bills').innerHTML = data.receipts.length ? data.receipts.map(card).join('') : '<div class="empty-state">No bills in this view yet.</div>';
    } else {
      const ledger = await api('/api/ledger');
      if (version !== state.routeVersion) return;
      $('#ledger-metrics').innerHTML = metric('Approved purchases', inr(data.summary.approved_total), 'Exact INR totals from checked bills', '₹', true)
        + metric('Ledger entries', ledger.entries.length, 'One entry per approved receipt', '▦');
      $('#ledger-rows').innerHTML = ledger.entries.map(entry => `<tr><td>${esc(dateLabel(entry.purchase_date))}</td><td>${esc(entry.merchant)}</td><td>${esc(entry.category)}</td><td>${inr(entry.amount)}</td><td><a href="#review/${encodeURIComponent(entry.receipt_id)}">View bill ↗</a></td></tr>`).join('');
      $('#ledger-empty').classList.toggle('hidden', ledger.entries.length > 0);
    }
  } catch (error) {
    toast(error.message);
    if (name === 'review') {
      $('#review-title').textContent = 'Bill could not be loaded';
      $('.review-grid').classList.add('hidden');
    }
  }
}
function itemRow(item, index) {
  return `<div class="item-row"><input data-item="name" aria-label="Item ${index+1} name" maxlength="100" value="${esc(item.name)}" required><input data-item="quantity" aria-label="Item ${index+1} quantity" inputmode="decimal" value="${esc(item.quantity)}" required><input data-item="unit_price" aria-label="Item ${index+1} rate" inputmode="decimal" value="${esc(item.unit_price)}" required><input data-item="amount" aria-label="Item ${index+1} amount" inputmode="decimal" value="${esc(item.amount)}" required><button type="button" data-remove-item aria-label="Remove item ${index+1}">×</button></div>`;
}
function renderReview(receipt) {
  state.receipt = receipt;
  const fields = receipt.fields;
  $('.review-grid').classList.remove('hidden');
  $('#review-title').textContent = fields.merchant || 'Check your bill';
  $('#review-subtitle').textContent = `${receipt.filename} · ${dateLabel(fields.purchase_date)}`;
  const [status, label] = statusLabel(receipt);
  $('#review-status').className = 'badge ' + status;
  $('#review-status').textContent = label;
  $('#merchant').value = fields.merchant;
  $('#purchase-date').value = fields.purchase_date;
  $('#category').value = fields.category;
  $('#tax').value = fields.tax;
  $('#discount').value = fields.discount;
  $('#total').value = fields.total;
  $('#item-rows').innerHTML = fields.items.map(itemRow).join('');
  $('#raw-text').textContent = receipt.raw_text;
  $('#receipt-image').classList.toggle('hidden', !receipt.image_url);
  $('#no-image').classList.toggle('hidden', Boolean(receipt.image_url));
  if (receipt.image_url) $('#receipt-image').src = receipt.image_url;
  const score = receipt.extraction.ocr_score;
  $('#source-note').textContent = receipt.source === 'rapidocr'
    ? `Read on this computer with RapidOCR${score !== null ? ` · mean text recognition score ${Math.round(score*100)}%` : ''}. Recognition scores do not prove field accuracy.`
    : receipt.source === 'demo-transcript' ? 'Fictional sample receipt with a supplied transcript. Upload a photo to exercise the local OCR model.' : 'Added from pasted text. Fields were suggested by parsing rules; inspect the text above.';
  $('#review-warnings').innerHTML = receipt.extraction.warnings.map(warning => `<p class="warning">${esc(warning)}</p>`).join('');
  const closed = receipt.status !== 'review';
  $$('#review-form input, #review-form select, #review-form button').forEach(element => element.disabled = closed);
  $('#verified').checked = false;
  $('#verification-label').classList.toggle('hidden', closed);
  $('.review-actions').classList.toggle('hidden', closed);
  $('#reject-review').classList.toggle('hidden', closed);
  $('#add-item').classList.toggle('hidden', closed);
  $('#closed-receipt').classList.toggle('hidden', !closed);
  $('#closed-receipt').textContent = receipt.status === 'approved' ? '✓ Approved and recorded in your purchase khata. This record is closed for edits.' : 'This receipt was rejected. It has no ledger entry.';
  $('#review-error').classList.add('hidden');
  updateMath();
}
function fieldsFromForm() {
  return {merchant:$('#merchant').value, purchase_date:$('#purchase-date').value, currency:state.receipt.fields.currency,
    category:$('#category').value, tax:$('#tax').value, discount:$('#discount').value, total:$('#total').value,
    items:$$('.item-row').map(row => Object.fromEntries([...row.querySelectorAll('[data-item]')].map(input => [input.dataset.item, input.value])))};
}
function updateMath() {
  if (!state.receipt) return;
  const fields = fieldsFromForm();
  const subtotal = fields.items.reduce((sum, item) => sum + Number(item.amount), 0);
  const calculated = subtotal + Number(fields.tax) - Number(fields.discount);
  const difference = Number(fields.total) - calculated;
  const invalid = !fields.items.length || fields.items.some(item => !item.amount.trim()) || !fields.total.trim() || !Number.isFinite(calculated) || !Number.isFinite(difference);
  const balanced = !invalid && Math.abs(difference) < .011;
  $('#math-check').classList.toggle('bad', !balanced);
  $('#math-check').textContent = invalid ? 'Add the amounts and total to reconcile this bill.' : balanced
    ? `✓ Totals line up: ${inr(subtotal)} + ${inr(fields.tax)} tax − ${inr(fields.discount)} discount = ${inr(calculated)}.`
    : `Check this difference: item amounts + tax − discount = ${inr(calculated)}. Receipt says ${inr(fields.total)} (${inr(Math.abs(difference))} ${difference >= 0 ? 'more' : 'less'}).`;
}
async function saveCurrent(receipt, fields) {
  return api(`/api/receipts/${encodeURIComponent(receipt.id)}`, jsonOptions('PUT', {revision:receipt.revision, fields}));
}
async function reviewAction(action) {
  if (state.busy || !state.receipt || state.receipt.status !== 'review') return;
  if (action === 'approve' && !$('#verified').checked) {
    $('#review-error').textContent = 'Check the confirmation box after comparing the fields with your receipt.';
    $('#review-error').classList.remove('hidden');
    return;
  }
  state.busy = true;
  const version = state.routeVersion;
  let reviewed = state.receipt;
  const fields = fieldsFromForm();
  $$('.review-actions button, #reject-review').forEach(button => button.disabled = true);
  try {
    if (action === 'save' || action === 'approve') reviewed = await saveCurrent(reviewed, fields);
    if (action === 'approve') {
      const result = await api(`/api/receipts/${reviewed.id}/approve`, jsonOptions('POST', {revision:reviewed.revision, verified:true}));
      reviewed = result.receipt;
    }
    if (action === 'reject') reviewed = await api(`/api/receipts/${reviewed.id}/reject`, jsonOptions('POST', {revision:reviewed.revision}));
    if (version === state.routeVersion) state.receipt = reviewed;
    toast({save:'Changes saved. Your bill is still waiting for approval.', approve:'Bill approved. One less thing on your list.', reject:'Bill rejected. No ledger entry was added.'}[action]);
    if (version === state.routeVersion) await route();
  } catch (error) {
    if (version === state.routeVersion) {
      state.receipt = reviewed;
      $('#review-error').textContent = error.message;
      $('#review-error').classList.remove('hidden');
    } else toast(error.message);
  } finally {
    state.busy = false;
    if (state.receipt?.status === 'review') $$('.review-actions button, #reject-review').forEach(button => button.disabled = false);
  }
}
function openUpload() {
  $('#upload-error').classList.add('hidden');
  $('#upload-dialog').showModal();
}
document.addEventListener('click', event => {
  const upload = event.target.closest('[data-upload]');
  if (upload) openUpload();
  const filter = event.target.closest('[data-filter]');
  if (filter) {state.filter = filter.dataset.filter; $$('[data-filter]').forEach(button => button.classList.toggle('active', button === filter)); route();}
  const input = event.target.closest('[data-input]');
  if (input) {
    state.input = input.dataset.input;
    $$('[data-input]').forEach(button => button.classList.toggle('active', button === input));
    $('#image-input').classList.toggle('hidden', state.input !== 'image');
    $('#text-input').classList.toggle('hidden', state.input !== 'text');
    $('#upload-error').classList.add('hidden');
  }
  const evidence = event.target.closest('[data-evidence]');
  if (evidence) {
    $$('[data-evidence]').forEach(button => button.classList.toggle('active', button === evidence));
    $('#receipt-image-wrap').classList.toggle('hidden', evidence.dataset.evidence !== 'image');
    $('#raw-text').classList.toggle('hidden', evidence.dataset.evidence !== 'text');
  }
  const remove = event.target.closest('[data-remove-item]');
  if (remove) {remove.closest('.item-row').remove(); updateMath();}
});
$('#close-upload').onclick = () => $('#upload-dialog').close();
$('#receipt-file').onchange = () => $('#file-name').textContent = $('#receipt-file').files[0]?.name || 'PNG, JPG or WebP · up to 5 MB';
$('#add-item').onclick = () => {$('#item-rows').insertAdjacentHTML('beforeend', itemRow({name:'',quantity:'1',unit_price:'0.00',amount:'0.00'}, $$('.item-row').length)); updateMath();};
$('#review-form').oninput = updateMath;
$('#review-form').onsubmit = event => {event.preventDefault(); reviewAction('save');};
$('#approve-review').onclick = () => reviewAction('approve');
$('#reject-review').onclick = () => reviewAction('reject');
$('#upload-form').onsubmit = async event => {
  event.preventDefault();
  const button = $('#upload-submit');
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = state.input === 'image' ? 'Reading your receipt…' : 'Finding the fields…';
  $('#upload-error').classList.add('hidden');
  try {
    let options;
    if (state.input === 'image') {
      const file = $('#receipt-file').files[0];
      if (!file) throw new Error('Choose a receipt photo first.');
      if (file.size > 5*1024*1024) throw new Error('Use an image smaller than 5 MB.');
      const body = new FormData(); body.append('receipt', file); options = {method:'POST', body};
    } else options = jsonOptions('POST', {text:$('#receipt-text').value});
    const receipt = await api('/api/receipts', options);
    $('#upload-dialog').close();
    $('#upload-form').reset();
    $('#file-name').textContent = 'PNG, JPG or WebP · up to 5 MB';
    location.hash = 'review/' + receipt.id;
    toast('Receipt added. Check the fields before approving.');
  } catch (error) {
    $('#upload-error').textContent = error.message;
    if (error.data?.existing_id) {
      const link = document.createElement('a'); link.href = '#review/' + encodeURIComponent(error.data.existing_id); link.textContent = ' Open existing bill →';
      link.onclick = () => $('#upload-dialog').close(); $('#upload-error').appendChild(link);
    }
    $('#upload-error').classList.remove('hidden');
  } finally {button.disabled = false; button.textContent = 'Read receipt →';}
};
window.addEventListener('hashchange', route);
(async () => {
  try {const config = await api('/api/bootstrap'); state.csrf = config.csrf_token; await route();}
  catch (error) {toast(error.message);}
})();
