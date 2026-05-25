// ── Helpers ─────────────────────────────────────────────────────────────────

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const err = await res.json();
      if (err.error) msg = err.error;
    } catch { /* non-JSON body */ }
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg, type = '') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

function isDefault(field, value) {
  const defaults = window._defaults;
  if (!defaults || !defaults[field]) return false;
  return defaults[field] === value;
}

// ── Build command from form ────────────────────────────────────────────────

// Reverse lookup: form field id → arg name (built lazily from idMap).
// When multiple arg names map to the same field (e.g. 'c' and 'ctx-size' both
// point at 'f-ctx-size'), prefer the longest — that's the canonical long-form
// llama.cpp flag, not the short alias.
let _fieldToArg = null;
function fieldToArg(fieldId) {
  if (!_fieldToArg) {
    _fieldToArg = {};
    for (const [arg, field] of Object.entries(idMap)) {
      const cur = _fieldToArg[field];
      if (!cur || arg.length > cur.length) _fieldToArg[field] = arg;
    }
  }
  return _fieldToArg[fieldId] || fieldId.replace(/^f-/, '');
}

// Get the default value of a <select> — value of <option ... selected>, or
// the first option's value if nothing is marked selected.
function selectDefault(sel) {
  const opt = sel.querySelector('option[selected]') || sel.options[0];
  return opt ? opt.value : '';
}

// Args that we loaded but don't have a UI field for — preserved on save
window._unknownArgs = {};

// Checkboxes that came from --no-X (so unchecked = explicit False, not "absent")
window._negatedFields = new Set();

function buildArgs() {
  const fields = document.querySelectorAll('#app input, #app select, #app textarea');
  const args = {};
  fields.forEach(f => {
    if (!f.id.startsWith('f-')) return;
    const fieldId = f.id;
    const argName = fieldToArg(fieldId);

    if (f.type === 'checkbox') {
      // Only emit when the user diverges from the HTML default.
      // Same value as default → omit (no need to clutter args.txt).
      // Checked & default-unchecked      → --X
      // Unchecked & default-checked       → --no-X
      // Unchecked & default-unchecked but
      //   explicitly loaded as --no-X    → --no-X  (preserve user intent)
      if (f.checked !== f.defaultChecked) {
        args[argName] = !!f.checked;
      } else if (!f.checked && window._negatedFields.has(fieldId)) {
        args[argName] = false;
      }

    } else if (f.tagName === 'SELECT') {
      const val = (f.value || '').trim();
      const def = selectDefault(f);
      if (val && val !== def) args[argName] = val;

    } else if (f.type !== 'hidden') {
      const val = (f.value || '').trim();
      if (val) args[argName] = val;
    }
  });
  // round-trip any args we didn't have a UI for
  for (const [k, v] of Object.entries(window._unknownArgs)) {
    if (!(k in args)) args[k] = v;
  }
  return args;
}

function updatePreview() {
  const args = buildArgs();
  const parts = [];
  for (const [name, value] of Object.entries(args)) {
    if (value === true) {
      parts.push(`--${name}`);
    } else if (value === false) {
      parts.push(`--no-${name}`);
    } else if (value === '' || value === null || value === undefined) {
      continue;
    } else {
      const v = String(value);
      parts.push(v.includes(' ') ? `--${name} "${v}"` : `--${name} ${v}`);
    }
  }
  document.querySelector('#preview-output code').textContent =
    parts.length ? parts.join(' ') : 'No arguments set';
}

// ── Form population ────────────────────────────────────────────────────────

// Map canonical llama-server long-form arg names → form field IDs.
// Short-aliased flags (e.g. -m, -c, -np) are normalized by the server's
// SHORT_TO_LONG table before they reach here, so we only handle long form.
const idMap = {
  'model': 'f-model',
  'mmproj': 'f-mmproj-path',
  'mmproj-url': 'f-mmproj-url',
  'mmproj-offload': 'f-mmproj-offload',
  'mmproj-auto': 'f-mmproj-auto',
  'n-gpu-layers': 'f-gpu-layers',
  'split-mode': 'f-split-mode',
  'tensor-split': 'f-tensor-split',
  'device': 'f-device',
  'main-gpu': 'f-main-gpu',
  'fit': 'f-fit',
  'fit-target': 'f-fit-target',
  'fit-ctx': 'f-fit-ctx',
  'override-tensor': 'f-override-tensor',
  'check-tensors': 'f-check-tensors',
  'mlock': 'f-mlock',
  'mmap': 'f-mmap',
  'direct-io': 'f-direct-io',
  'kv-offload': 'f-kv-offload',
  'repack': 'f-repack',
  'cache-type-k': 'f-cache-type-k',
  'cache-type-v': 'f-cache-type-v',
  'ctx-size': 'f-ctx-size',
  'n-predict': 'f-n-predict',
  'batch-size': 'f-batch-size',
  'ubatch-size': 'f-ubatch-size',
  'keep': 'f-keep',
  'swap-full': 'f-swap-full',
  'rope-scaling': 'f-rope-scaling',
  'rope-scale': 'f-rope-scale',
  'rope-freq-base': 'f-rope-freq-base',
  'rope-freq-scale': 'f-rope-freq-scale',
  'yarn-orig-ctx': 'f-yarn-orig-ctx',
  'yarn-ext-factor': 'f-yarn-ext-factor',
  'context-shift': 'f-context-shift',
  'checkpoint-every-n-tokens': 'f-checkpoint-every',
  'cache-ram': 'f-cache-ram',
  'kv-unified': 'f-kv-unified',
  'cache-idle-slots': 'f-cache-idle',
  'temperature': 'f-temperature',
  'top-k': 'f-top-k',
  'top-p': 'f-top-p',
  'min-p': 'f-min-p',
  'top-nsigma': 'f-top-n-sigma',
  'xtc-probability': 'f-xtc-probability',
  'xtc-threshold': 'f-xtc-threshold',
  'typical-p': 'f-typical-p',
  'repeat-last-n': 'f-repeat-last-n',
  'repeat-penalty': 'f-repeat-penalty',
  'presence-penalty': 'f-presence-penalty',
  'frequency-penalty': 'f-frequency-penalty',
  'seed': 'f-seed',
  'samplers': 'f-samplers',
  'dynatemp-range': 'f-dynatemp-range',
  'dynatemp-exp': 'f-dynatemp-exp',
  'adaptive-target': 'f-adaptive-target',
  'adaptive-decay': 'f-adaptive-decay',
  'mirostat': 'f-mirostat',
  'mirostat-lr': 'f-mirostat-lr',
  'mirostat-ent': 'f-mirostat-tau',
  'logit-bias': 'f-logit-bias',
  'jinja': 'f-jinja',
  'grammar': 'f-grammar',
  'grammar-file': 'f-grammar-file',
  'ignore-eos': 'f-ignore-eos',
  'dry-multiplier': 'f-dry-multiplier',
  'dry-base': 'f-dry-base',
  'dry-allowed-length': 'f-dry-allowed-length',
  'dry-penalty-last-n': 'f-dry-penalty-last-n',
  'dry-sequence-breaker': 'f-dry-sequence-breaker',
  'host': 'f-host',
  'port': 'f-port',
  'reuse-port': 'f-reuse-port',
  'path': 'f-static-path',
  'api-prefix': 'f-api-prefix',
  'timeout': 'f-timeout',
  'threads-http': 'f-threads-http',
  'parallel': 'f-parallel',
  'cont-batching': 'f-cont-batching',
  'webui': 'f-webui',
  'embedding': 'f-embedding',
  'rerank': 'f-rerank',
  'api-key': 'f-api-key',
  'api-key-file': 'f-api-key-file',
  'ssl-key-file': 'f-ssl-key-file',
  'ssl-cert-file': 'f-ssl-cert-file',
  'log-verbosity': 'f-log-verbosity',
  'log-colors': 'f-log-colors',
  'log-prefix': 'f-log-prefix',
  'log-timestamps': 'f-log-timestamps',
  'chat-template': 'f-chat-template',
  'reasoning': 'f-reasoning',
  'reasoning-format': 'f-reasoning-format',
  'reasoning-budget': 'f-reasoning-budget',
  'reasoning-budget-message': 'f-reasoning-budget-message',
  'warmup': 'f-warmup',
  'cache-prompt': 'f-cache-prompt',
  'cache-reuse': 'f-cache-reuse',
  'reverse-prompt': 'f-reverse-prompt',
  'special': 'f-special',
  'flash-attn': 'f-flash-att',
  'escape': 'f-escape',
  'pooling': 'f-pooling',
  'lora': 'f-lora',
  'lora-scaled': 'f-lora-scaled',
  'control-vector': 'f-control-vector',
  'control-vector-scaled': 'f-control-vector-scaled',
  'control-vector-layer-range': 'f-control-vector-layer',
  'alias': 'f-alias',
  'tags': 'f-tags',
  'spec-type': 'f-spec-type',
  'spec-draft-n-max': 'f-spec-draft-n-max',
  'spec-draft-n-min': 'f-spec-draft-n-min',
  'spec-draft-p-split': 'f-spec-draft-p-split',
  'spec-draft-p-min': 'f-spec-draft-p-min',
  'spec-draft-model': 'f-spec-draft-model',
  'spec-draft-hf': 'f-spec-draft-hf',
  'spec-draft-threads': 'f-spec-draft-threads',
  'spec-draft-ctx-size': 'f-spec-draft-ctx-size',
  'spec-draft-ngl': 'f-spec-draft-ngl',
  'spec-draft-device': 'f-spec-draft-device',
  'spec-replace': 'f-spec-replace',
  'spec-draft-threads-batch': 'f-spec-draft-threads-batch',
  'spec-draft-prio': 'f-spec-draft-prio',
  'spec-draft-poll': 'f-spec-draft-poll',
  'spec-draft-cpu-mask': 'f-spec-draft-cpu-mask',
  'spec-draft-cpu-range': 'f-spec-draft-cpu-range',
  'spec-draft-cpu-strict': 'f-spec-draft-cpu-strict',
  'spec-draft-cpu-mask-batch': 'f-spec-draft-cpu-mask-batch',
  'spec-draft-cpu-strict-batch': 'f-spec-draft-cpu-strict-batch',
  'spec-draft-prio-batch': 'f-spec-draft-prio-batch',
  'spec-draft-poll-batch': 'f-spec-draft-poll-batch',
  'spec-draft-override-tensor': 'f-spec-draft-override-tensor',
  'spec-draft-cpu-moe': 'f-spec-draft-cpu-moe',
  'spec-draft-n-cpu-moe': 'f-spec-draft-n-cpu-moe',
  'spec-draft-type-k': 'f-spec-draft-cache-type-k',
  'spec-draft-type-v': 'f-spec-draft-cache-type-v',
  'cpu-mask': 'f-cpu-mask',
  'cpu-range': 'f-cpu-range',
  'cpu-strict': 'f-cpu-strict',
  'prio': 'f-prio',
  'poll': 'f-poll',
  'cpu-mask-batch': 'f-cpu-mask-batch',
  'cpu-range-batch': 'f-cpu-range-batch',
  'cpu-strict-batch': 'f-cpu-strict-batch',
  'prio-batch': 'f-prio-batch',
  'poll-batch': 'f-poll-batch',
  'numa': 'f-numa',
  'cpu-moe': 'f-cpu-moe',
  'n-cpu-moe': 'f-n-cpu-moe',
  'offline': 'f-offline',
  'no-host': 'f-no-host',
  'op-offload': 'f-op-offload',
  'perf': 'f-perf',
  'verbosity': 'f-verbosity',
  'log-file': 'f-log-file',
  'hf-repo': 'f-hf-repo',
  'hf-file': 'f-hf-file',
  'hf-token': 'f-hf-token',
  'hf-repo-v': 'f-hf-repo-v',
  'hf-file-v': 'f-hf-file-v',
  'webui-config': 'f-webui-config',
  'webui-config-file': 'f-webui-config-file',
  'webui-mcp-proxy': 'f-webui-mcp',
  'tools': 'f-tools',
  'chat-template-kwargs': 'f-chat-template-kwargs',
  'override-kv': 'f-override-kv',
  'lookup-cache-static': 'f-lookup-cache-static',
  'lookup-cache-dynamic': 'f-lookup-cache-dynamic',
  'ctx-checkpoints': 'f-ctx-checkpoints',
  'image-min-tokens': 'f-image-min-tokens',
  'image-max-tokens': 'f-image-max-tokens',
  'json-schema': 'f-json-schema',
  'json-schema-file': 'f-json-schema-file',
};

function setField(id, value) {
  const el = document.getElementById(id);
  if (!el) return false;
  if (el.type === 'checkbox') {
    if (value === true || value === 'true') {
      el.checked = true;
    } else if (value === false || value === 'false') {
      el.checked = false;
      window._negatedFields.add(id);
    } else {
      // truthy non-boolean string in a checkbox slot — treat as on
      el.checked = !!value;
    }
  } else {
    el.value = String(value);
  }
  return true;
}

function clearAllFields() {
  document.querySelectorAll('#app input, #app select, #app textarea').forEach(el => {
    if (!el.id.startsWith('f-')) return;
    if (el.type === 'checkbox') {
      el.checked = el.defaultChecked;
    } else {
      el.value = '';
    }
  });
  window._negatedFields = new Set();
  window._unknownArgs = {};
}

function populateArgs(args) {
  if (args == null || typeof args !== 'object') {
    console.warn('populateArgs: non-object payload', args);
    args = {};
  }
  clearAllFields();
  for (const [key, value] of Object.entries(args)) {
    const field = idMap[key];
    if (!field || !setField(field, value)) {
      // Unknown flag — preserve so it round-trips on save
      window._unknownArgs[key] = value;
    }
  }
  updatePreview();
}

// ── Profile management ────────────────────────────────────────────────────

let profiles = {};

async function loadProfiles() {
  try {
    const data = await api('/api/profiles');
    profiles = data.profiles;
    const sel = document.getElementById('profile-select');
    sel.innerHTML = '<option value="">— No profile —</option>';
    for (const name of Object.keys(profiles)) {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    }
  } catch (e) {
    console.error('Failed to load profiles:', e);
  }
}

async function saveProfile() {
  const sel = document.getElementById('profile-select');
  let name = sel.value.trim();
  if (!name) {
    name = prompt('Profile name:');
    if (!name) return;
    sel.value = name;
    sel.innerHTML += `<option value="${name}">${name}</option>`;
  }

  const args = buildArgs();
  await api('/api/profiles', { method: 'POST', body: { name, args } });
  toast('Profile saved', 'success');
}

async function loadProfile(name) {
  try {
    // POST: the /load endpoint returns {ok, args}. A plain GET on
    // /api/profiles/<name> returns {profile} which is the wrong shape.
    const data = await api(`/api/profiles/${encodeURIComponent(name)}/load`, { method: 'POST' });
    populateArgs(data.args || {});
    toast('Profile loaded', 'success');
  } catch (e) {
    toast('Failed to load profile: ' + e.message, 'error');
  }
}

async function deleteProfile(name) {
  if (!confirm(`Delete profile "${name}"?`)) return;
  try {
    await api(`/api/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
    toast('Profile deleted', 'success');
    await loadProfiles();
  } catch (e) {
    toast('Failed to delete: ' + e.message, 'error');
  }
}

// ── Server management ─────────────────────────────────────────────────────

async function updateStatus() {
  try {
    const data = await api('/api/status');
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');
    const statusText = document.getElementById('status-text');

    if (data.running) {
      btnStop.disabled = false;
      btnStart.disabled = true;
      document.getElementById('btn-opencode').disabled = false;
      statusText.textContent = `Running (PID ${data.pid})`;
      statusText.className = 'status running';
      statusText.innerHTML = '<span class="status-dot running"></span>Running (PID ' + data.pid + ')';
    } else {
      btnStop.disabled = true;
      btnStart.disabled = false;
      document.getElementById('btn-opencode').disabled = true;
      statusText.textContent = 'Stopped';
      statusText.className = 'status stopped';
    }
  } catch (e) {
    console.error('Status check failed:', e);
  }
}

async function startServer() {
  try {
    const data = await api('/api/start', { method: 'POST' });
    toast('Server started', 'success');
    await updateStatus();
  } catch (e) {
    toast('Failed to start: ' + e.message, 'error');
  }
}

async function stopServer() {
  try {
    await api('/api/stop', { method: 'POST' });
    toast('Server stopped', 'success');
    await updateStatus();
  } catch (e) {
    toast('Failed to stop: ' + e.message, 'error');
  }
}

// ── Model discovery ────────────────────────────────────────────────────────

async function discoverModels(dir, opts = {}) {
  const { silent = false } = opts;
  try {
    const url = '/api/models' + (dir ? `?dir=${encodeURIComponent(dir)}` : '');
    const data = await api(url, { method: 'GET' });
    const selModel = document.getElementById('sel-model');
    const selMmproj = document.getElementById('sel-mmproj');

    selModel.innerHTML = '<option value="">— Select model —</option>';
    selMmproj.innerHTML = '<option value="">— No mmproj —</option>';

    for (const path of data.models) {
      const name = path.split(/[/\\]/).pop();
      const optM = document.createElement('option');
      optM.value = path;
      optM.textContent = name;
      selModel.appendChild(optM);

      const optP = document.createElement('option');
      optP.value = path;
      optP.textContent = name;
      selMmproj.appendChild(optP);
    }

    // Echo the resolved path back to the input
    if (data.dir) document.getElementById('model-dir').value = data.dir;

    // Pre-select whatever the model/mmproj fields currently hold
    const curModel = document.getElementById('f-model').value.trim();
    const curMmproj = document.getElementById('f-mmproj-path').value.trim();
    if (curModel) selModel.value = curModel;
    if (curMmproj) selMmproj.value = curMmproj;

    return data.models.length;
  } catch (e) {
    if (!silent) toast('Failed to discover models: ' + e.message, 'error');
    return 0;
  }
}

// ── Folder browser modal ───────────────────────────────────────────────────

let browserCurrentPath = '';

async function openBrowser(startPath = '') {
  const modal = document.getElementById('browser-modal');
  modal.hidden = false;
  // start at the current model-dir, BASE, or drive list
  if (!startPath) {
    startPath = document.getElementById('model-dir').value.trim();
  }
  if (!startPath) {
    try {
      const d = await api('/api/current-dir');
      startPath = d.dir;
    } catch { /* ignore */ }
  }
  await loadBrowserPath(startPath);
}

function closeBrowser() {
  document.getElementById('browser-modal').hidden = true;
}

async function loadBrowserPath(path) {
  const listEl = document.getElementById('browser-list');
  const pathEl = document.getElementById('browser-path');
  const statusEl = document.getElementById('browser-status');
  listEl.innerHTML = '<div class="browser-empty">Loading…</div>';
  statusEl.textContent = '';

  try {
    const data = await api(`/api/browse?dir=${encodeURIComponent(path || '')}`);
    if (data.error) {
      listEl.innerHTML = `<div class="browser-empty error">${data.error}</div>`;
      return;
    }
    browserCurrentPath = data.path || '';
    pathEl.value = browserCurrentPath || '(drives)';

    const rows = [];

    // Drives shortcut row (only shown when at the drives view)
    if (!data.path && data.drives && data.drives.length) {
      for (const d of data.drives) {
        rows.push(browserRow('💽', d, () => loadBrowserPath(d)));
      }
    }

    // Subdirectories
    for (const name of data.dirs || []) {
      const childPath = joinPath(data.path, name);
      rows.push(browserRow('📁', name, () => loadBrowserPath(childPath)));
    }

    // .gguf files (shown for confirmation; click does nothing destructive)
    for (const f of data.files || []) {
      rows.push(browserRow('📄', f.name, null, 'gguf'));
    }

    if (!rows.length) {
      listEl.innerHTML = '<div class="browser-empty">Empty.</div>';
    } else {
      listEl.innerHTML = '';
      rows.forEach(r => listEl.appendChild(r));
    }

    const ggufCount = (data.files || []).length;
    statusEl.textContent = ggufCount
      ? `${ggufCount} .gguf file${ggufCount === 1 ? '' : 's'} here`
      : (data.path ? 'No .gguf files in this folder.' : '');
  } catch (e) {
    listEl.innerHTML = `<div class="browser-empty error">${e.message}</div>`;
  }
}

function browserRow(icon, label, onClick, extraClass = '') {
  const row = document.createElement('div');
  row.className = 'browser-row ' + extraClass;
  row.innerHTML = `<span class="icon">${icon}</span><span class="label"></span>`;
  row.querySelector('.label').textContent = label;
  if (onClick) {
    row.classList.add('clickable');
    row.addEventListener('click', onClick);
  }
  return row;
}

function joinPath(base, child) {
  if (!base) return child;
  const sep = base.includes('\\') ? '\\' : '/';
  return base.endsWith(sep) ? base + child : base + sep + child;
}

function browserGoUp() {
  // Ask the server for the parent (handles drive roots correctly)
  api(`/api/browse?dir=${encodeURIComponent(browserCurrentPath)}`).then(d => {
    if (d.parent != null) loadBrowserPath(d.parent);
    else loadBrowserPath('drives');
  });
}

function browserSelectCurrent() {
  if (!browserCurrentPath) {
    toast('Pick a folder first', 'error');
    return;
  }
  document.getElementById('model-dir').value = browserCurrentPath;
  discoverModels(browserCurrentPath);
  closeBrowser();
}

// ── Section toggles ────────────────────────────────────────────────────────

function toggleSection(name) {
  const sec = document.getElementById('sec-' + name);
  const header = sec.querySelector('.section-header');
  const content = sec.querySelector('.section-content');
  const isVisible = !content.hidden;

  content.hidden = isVisible;
  header.textContent = header.textContent.replace(/\s*[▾▸]$/, '') + (isVisible ? ' ▸' : ' ▾');
}

// ── Advanced mode toggle ───────────────────────────────────────────────────

const LS_ADVANCED = 'llamaui.showAdvanced';

function applyAdvancedMode(on) {
  document.body.classList.toggle('show-advanced', !!on);
  try { localStorage.setItem(LS_ADVANCED, on ? '1' : '0'); } catch {}
}

function initAdvancedToggle() {
  const cb = document.getElementById('toggle-advanced');
  if (!cb) return;
  let saved = '0';
  try { saved = localStorage.getItem(LS_ADVANCED) || '0'; } catch {}
  cb.checked = saved === '1';
  applyAdvancedMode(cb.checked);
  cb.addEventListener('change', (e) => applyAdvancedMode(e.target.checked));
}

// ── Init ───────────────────────────────────────────────────────────────────

async function init() {
  // Load defaults from llama-args.txt
  try {
    const { args } = await api('/api/args');
    window._defaults = args;
    populateArgs(args);
  } catch (e) {
    console.warn('Could not load llama-args.txt defaults:', e.message);
    window._defaults = {};
  }

  await loadProfiles();
  await updateStatus();

  // Auto-discover models from the llamacpp directory
  try {
    const { dir } = await api('/api/current-dir');
    document.getElementById('model-dir').value = dir;
    await discoverModels(dir, { silent: true });
  } catch (e) {
    console.warn('Skipping initial model scan:', e.message);
  }
}

// ── Event handlers ────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {

  // Render hint text from data-hint attributes
  document.querySelectorAll('[data-hint]').forEach(el => {
    const hint = el.getAttribute('data-hint');
    if (!hint) return;
    const span = document.createElement('span');
    span.className = 'hint';
    span.textContent = hint;
    const label = el.closest('label');
    if (label) {
      const input = el;
      label.insertBefore(span, input);
    }
  });

  // Args change → update preview
  document.getElementById('app').addEventListener('input', updatePreview);

  // Advanced settings toggle
  initAdvancedToggle();

  // Profile actions
  document.getElementById('profile-select').addEventListener('change', (e) => {
    if (e.target.value) loadProfile(e.target.value);
  });

  document.getElementById('btn-new-profile').addEventListener('click', async () => {
    const name = prompt('New profile name:');
    if (!name) return;
    await api('/api/profiles', { method: 'POST', body: { name, args: {} } });
    await loadProfiles();
    document.getElementById('profile-select').value = name;
    toast('Profile created', 'success');
  });

  document.getElementById('btn-save-profile').addEventListener('click', saveProfile);

  document.getElementById('btn-delete-profile').addEventListener('click', () => {
    const sel = document.getElementById('profile-select');
    if (!sel.value) return;
    deleteProfile(sel.value);
  });

  document.getElementById('btn-reset').addEventListener('click', async () => {
    const argsData = await api('/api/args');
    populateArgs(argsData.args);
    toast('Reset to defaults', 'success');
  });

  document.getElementById('btn-save').addEventListener('click', async () => {
    try {
      const args = buildArgs();
      await api('/api/save', { method: 'POST', body: args });
      toast('Saved to args.txt', 'success');
    } catch (e) {
      toast('Save failed: ' + e.message, 'error');
    }
  });

  document.getElementById('btn-current-dir').addEventListener('click', async () => {
    try {
      const data = await api('/api/current-dir');
      document.getElementById('model-dir').value = data.dir;
      await discoverModels(data.dir);
    } catch (e) {
      toast('Could not get current directory: ' + e.message, 'error');
    }
  });

  // Folder browser modal
  document.getElementById('btn-browse-dir').addEventListener('click', () => openBrowser());
  document.getElementById('btn-browser-close').addEventListener('click', closeBrowser);
  document.getElementById('btn-browser-cancel').addEventListener('click', closeBrowser);
  document.getElementById('btn-browser-up').addEventListener('click', browserGoUp);
  document.getElementById('btn-browser-drives').addEventListener('click', () => loadBrowserPath('drives'));
  document.getElementById('btn-browser-select').addEventListener('click', browserSelectCurrent);
  document.getElementById('btn-browser-go').addEventListener('click', () => {
    const p = document.getElementById('browser-path').value.trim();
    if (p) loadBrowserPath(p);
  });
  document.getElementById('browser-path').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const p = e.target.value.trim();
      if (p) loadBrowserPath(p);
    }
  });
  // Click on the backdrop closes
  document.querySelector('#browser-modal .modal-backdrop').addEventListener('click', closeBrowser);
  // Esc closes
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !document.getElementById('browser-modal').hidden) {
      closeBrowser();
    }
  });

  // When the user picks a model from the dropdown, mirror it into f-model
  document.getElementById('sel-model').addEventListener('change', (e) => {
    if (e.target.value) {
      document.getElementById('f-model').value = e.target.value;
      updatePreview();
    }
  });
  document.getElementById('sel-mmproj').addEventListener('change', (e) => {
    if (e.target.value) {
      document.getElementById('f-mmproj-path').value = e.target.value;
      updatePreview();
    }
  });

  document.getElementById('model-dir').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const val = e.target.value.trim();
      if (val) discoverModels(val);
    }
  });

  document.getElementById('model-dir').addEventListener('change', (e) => {
    if (e.target.value) discoverModels(e.target.value);
  });

  document.getElementById('btn-start').addEventListener('click', startServer);
  document.getElementById('btn-stop').addEventListener('click', stopServer);
  document.getElementById('btn-opencode').addEventListener('click', async () => {
    try {
      await api('/api/opencode', { method: 'POST' });
      toast('Opencode launched', 'success');
    } catch (e) {
      toast('Failed to launch: ' + e.message, 'error');
    }
  });

  // Periodic status refresh
  setInterval(updateStatus, 10000);

  try {
    init();
  } catch (e) {
    toast('Failed to load: ' + e.message, 'error');
    console.error('Init error:', e);
  }
});
