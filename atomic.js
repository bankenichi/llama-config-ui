// Atomic fork control plane. The browser sends typed configuration to the Python
// adapter; the canonical PowerShell launcher remains the only component that turns
// it into llama-server argv and fork environment variables.

const atomic = {
  description: null,
  profiles: {},
  preview: null,
  statusTimer: null,
};

const atomicEl = id => document.getElementById(id);

function atomicValue(id) {
  const element = atomicEl(id);
  return element ? element.value.trim() : '';
}

function atomicNumber(id) {
  const value = atomicValue(id);
  return value === '' ? undefined : Number(value);
}

function atomicSetState(text, state = 'ready') {
  const element = atomicEl('atomic-state');
  element.textContent = text;
  element.dataset.state = state;
}

function tokenizeAtomicArgs(text) {
  const tokens = [];
  let current = '';
  let quote = null;
  for (const char of text.trim()) {
    if (quote) {
      if (char === quote) quote = null;
      else current += char;
    } else if (char === '"' || char === "'") {
      quote = char;
    } else if (/\s/.test(char)) {
      if (current) {
        tokens.push(current);
        current = '';
      }
    } else {
      current += char;
    }
  }
  if (quote) throw new Error('Additional argv contains an unmatched quote.');
  if (current) tokens.push(current);
  return tokens;
}

function collectAtomicOverrides() {
  const result = {
    port: atomicNumber('atomic-port'),
    vision_enabled: atomicEl('atomic-vision-enabled').checked,
    spec_enabled: atomicEl('atomic-spec-enabled').checked,
    context_shift: atomicEl('atomic-context-shift').checked,
    prefetch_experts: atomicEl('atomic-prefetch').checked,
    pin_host: atomicEl('atomic-pin-host').checked,
    metrics: atomicEl('atomic-metrics').checked,
    reasoning: atomicValue('atomic-reasoning'),
    cache_type_k: atomicValue('atomic-cache-k'),
    cache_type_v: atomicValue('atomic-cache-v'),
    draft_cache_type_k: atomicValue('atomic-draft-cache-k'),
    draft_cache_type_v: atomicValue('atomic-draft-cache-v'),
    extra_arguments: tokenizeAtomicArgs(atomicValue('atomic-extra')),
  };
  const fields = {
    server: 'atomic-server',
    model: 'atomic-model',
    draft_model: 'atomic-draft-model',
    mmproj: 'atomic-mmproj',
    spec_type: 'atomic-spec-type',
  };
  for (const [key, id] of Object.entries(fields)) {
    const value = atomicValue(id);
    if (value !== '') result[key] = value;
  }
  const numeric = {
    ctx_size: 'atomic-ctx-size',
    spec_draft_n_max: 'atomic-draft-max',
    gpu_layers: 'atomic-gpu-layers',
    draft_gpu_layers: 'atomic-draft-gpu-layers',
    n_cpu_moe: 'atomic-n-cpu-moe',
    batch_size: 'atomic-batch-size',
    ubatch_size: 'atomic-ubatch-size',
    prefetch_slots: 'atomic-prefetch-slots',
    turbo_layer_adaptive: 'atomic-turbo-adaptive',
  };
  for (const [key, id] of Object.entries(numeric)) {
    const value = atomicNumber(id);
    if (value !== undefined) result[key] = value;
  }
  if (result.pin_host) result.no_mmap = false;
  return result;
}

function atomicRequestBody(overrides = null) {
  return {
    stack: atomicValue('atomic-stack'),
    preset: atomicValue('atomic-preset') || 'standard',
    overrides: overrides || collectAtomicOverrides(),
  };
}

function setAtomicSelectOptions(element, values) {
  const current = element.value;
  element.replaceChildren(...values.map(value => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    return option;
  }));
  if (values.includes(current)) element.value = current;
}

function populateAtomicConfiguration(config) {
  const text = {
    'atomic-server': config.server,
    'atomic-model': config.model,
    'atomic-draft-model': config.draft_model,
    'atomic-mmproj': config.mmproj,
    'atomic-spec-type': config.spec_type,
    'atomic-port': config.port,
    'atomic-ctx-size': config.ctx_size,
    'atomic-draft-max': config.spec_draft_n_max,
    'atomic-gpu-layers': config.gpu_layers,
    'atomic-draft-gpu-layers': config.draft_gpu_layers,
    'atomic-n-cpu-moe': config.has_moe ? config.n_cpu_moe : '',
    'atomic-cache-k': config.cache_type_k,
    'atomic-cache-v': config.cache_type_v,
    'atomic-draft-cache-k': config.draft_cache_type_k,
    'atomic-draft-cache-v': config.draft_cache_type_v,
    'atomic-batch-size': config.batch_size || '',
    'atomic-ubatch-size': config.ubatch_size || '',
    'atomic-prefetch-slots': config.prefetch_slots || 1,
    'atomic-turbo-adaptive': config.turbo_layer_adaptive ?? '',
    'atomic-reasoning': config.reasoning || 'auto',
  };
  for (const [id, value] of Object.entries(text)) {
    if (atomicEl(id)) atomicEl(id).value = value ?? '';
  }
  atomicEl('atomic-spec-enabled').checked = !!config.spec_enabled;
  atomicEl('atomic-vision-enabled').checked = !!config.vision_enabled;
  atomicEl('atomic-context-shift').checked = !!config.context_shift;
  atomicEl('atomic-prefetch').checked = !!config.prefetch_experts;
  atomicEl('atomic-pin-host').checked = !!config.pin_host;
  atomicEl('atomic-metrics').checked = !!config.metrics;
  updateAtomicApplicability(config);
}

function updateAtomicApplicability(config = null) {
  const stack = atomicValue('atomic-stack');
  const qwen = stack === 'qwen';
  const ternary = stack === 'ternary';
  const dense = stack === 'ternary' || stack === 'gemma12';
  const gemma12 = stack === 'gemma12';

  atomicEl('atomic-draft-model').disabled = qwen || gemma12;
  atomicEl('atomic-spec-enabled').disabled = gemma12;
  atomicEl('atomic-n-cpu-moe').disabled = dense;
  atomicEl('atomic-prefetch').disabled = dense;
  atomicEl('atomic-prefetch-slots').disabled = dense || !atomicEl('atomic-prefetch').checked;
  atomicEl('atomic-draft-max').max = ternary ? 16 : 64;

  const notes = {
    ternary: 'DSpark uses the matching sidecar, lossless q8_0/q8_0 draft KV, four draft tokens by default, at most 16 draft slots, and a runtime-enforced 4096 positions per parallel slot. Target-derived image features keep drafting available for image answers and retained-image follow-ups.',
    qwen: 'NextN is embedded in the target GGUF and uses synchronous multi-step drafting. Leave the draft path empty. Target KV is turbo4/turbo3; the small draft context uses lossless q8_0/q8_0.',
    gemma26: 'The standard profile is target-only. Select the MTP preset to load the external assistant head. With vision configured, the media-aware MTP path can draft image answers and retained-image follow-ups.',
    gemma12: 'This dense model has no configured assistant head. Vision remains available; speculative controls are disabled.',
  };
  atomicEl('atomic-topology-note').textContent = notes[stack] || '';
  if (config && config.spec_type) atomicEl('atomic-spec-type').value = config.spec_type;
}

function renderAtomicPreview(preview) {
  atomic.preview = preview;
  const validation = preview.validation || { valid: false, errors: ['No validation result'], warnings: [] };
  const validationEl = atomicEl('atomic-validation');
  validationEl.hidden = false;
  validationEl.className = `atomic-validation ${validation.valid ? 'valid' : 'invalid'}`;
  const messages = [];
  if (validation.valid) messages.push('Preflight passed.');
  for (const warning of validation.warnings || []) messages.push(`Warning: ${warning}`);
  for (const error of validation.errors || []) messages.push(`Error: ${error}`);
  validationEl.textContent = messages.join('\n');

  const environment = Object.entries(preview.environment || {}).map(([key, value]) => `${key}=${value}`);
  const executable = preview.executable || '';
  const argv = (preview.redacted_arguments || []).map(value => {
    value = String(value);
    return /\s/.test(value) ? `"${value.replaceAll('"', '\\"')}"` : value;
  });
  atomicEl('atomic-command').textContent = [
    environment.length ? `Environment:\n${environment.join('\n')}\n` : 'Environment: no Atomic overrides\n',
    `Executable:\n${executable}`,
    `\nArguments:\n${argv.join(' ')}`,
  ].join('\n');
  atomicEl('atomic-start').disabled = !validation.valid;
  return validation.valid;
}

async function previewAtomic(overrides = null, populate = false) {
  atomicSetState('Validating', 'loading');
  const preview = await api('/api/atomic/preview', { method: 'POST', body: atomicRequestBody(overrides) });
  if (populate && preview.configuration) populateAtomicConfiguration(preview.configuration);
  renderAtomicPreview(preview);
  atomicSetState(preview.validation.valid ? 'Preflight ready' : 'Preflight failed', preview.validation.valid ? 'ready' : 'error');
  return preview;
}

function populateAtomicProfiles(payload) {
  atomic.profiles = payload.profiles || {};
  const select = atomicEl('atomic-profile');
  select.innerHTML = '<option value="">Custom configuration</option>';
  for (const [name, profile] of Object.entries(atomic.profiles)) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = profile.readonly ? `${name} · starter` : name;
    select.appendChild(option);
  }
}

function populateAtomicPresets(stack, selected = null) {
  const stackDefinition = atomic.description?.catalog?.stacks?.[stack];
  const values = Object.keys(stackDefinition?.presets || { standard: {} });
  setAtomicSelectOptions(atomicEl('atomic-preset'), values);
  if (selected && values.includes(selected)) atomicEl('atomic-preset').value = selected;
}

async function refreshAtomicDescription() {
  atomicSetState('Loading capabilities', 'loading');
  const description = await api('/api/atomic/describe');
  atomic.description = description;
  populateAtomicProfiles(description.profiles || {});
  const caches = description.capabilities?.cache_types || ['f16', 'q8_0', 'turbo2', 'turbo3', 'turbo4'];
  for (const id of ['atomic-cache-k', 'atomic-cache-v', 'atomic-draft-cache-k', 'atomic-draft-cache-v']) {
    setAtomicSelectOptions(atomicEl(id), caches);
  }
  const specTypes = description.capabilities?.spec_types || [];
  const featureNames = [
    ...specTypes.map(value => `spec:${value}`),
    ...(description.environment_features || []).filter(item => item.supported).map(item => `env:${item.key}`),
  ];
  atomicEl('atomic-capabilities').replaceChildren(...featureNames.map(value => {
    const chip = document.createElement('span');
    chip.textContent = value;
    return chip;
  }));
  populateAtomicPresets(atomicValue('atomic-stack'));
  atomicSetState('Capabilities current', 'ready');
  return description;
}

async function loadAtomicStackDefaults() {
  populateAtomicPresets(atomicValue('atomic-stack'));
  await previewAtomic({}, true);
}

async function loadAtomicProfile(name) {
  if (!name) return;
  const profile = atomic.profiles[name];
  atomicEl('atomic-stack').value = profile.stack;
  populateAtomicPresets(profile.stack, profile.preset);
  await previewAtomic(profile.overrides || {}, true);
}

async function saveAtomicProfile() {
  const name = prompt('Atomic profile name:');
  if (!name) return;
  const profile = {
    stack: atomicValue('atomic-stack'),
    preset: atomicValue('atomic-preset'),
    overrides: collectAtomicOverrides(),
  };
  const value = await api('/api/atomic/profiles', { method: 'POST', body: { name, profile } });
  populateAtomicProfiles(value);
  atomicEl('atomic-profile').value = name;
  toast('Atomic profile saved', 'success');
}

async function deleteAtomicProfile() {
  const name = atomicValue('atomic-profile');
  if (!name) return;
  const profile = atomic.profiles[name];
  if (profile?.readonly) {
    toast('Starter profiles are read-only', 'error');
    return;
  }
  if (!confirm(`Delete Atomic profile "${name}"?`)) return;
  const value = await api(`/api/atomic/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
  populateAtomicProfiles(value);
  toast('Atomic profile deleted', 'success');
}

async function importAtomicLegacyProfiles() {
  const value = await api('/api/atomic/import-legacy', { method: 'POST', body: {} });
  populateAtomicProfiles(value.profiles);
  const count = Object.keys(value.imported?.profiles || {}).length;
  toast(`Imported ${count} legacy profiles without modifying the source`, 'success');
}

async function startAtomic() {
  atomicSetState('Starting server', 'loading');
  const value = await api('/api/atomic/start', { method: 'POST', body: atomicRequestBody() });
  renderAtomicPreview(value.preview);
  atomicSetState(`Server PID ${value.pid}`, 'running');
  await updateAtomicStatus();
}

async function stopAtomic() {
  atomicSetState('Stopping server', 'loading');
  await api('/api/atomic/stop', { method: 'POST', body: { timeout: 10 } });
  await updateAtomicStatus();
}

async function updateAtomicStatus() {
  const status = await api('/api/atomic/status');
  atomicEl('atomic-status-output').textContent = JSON.stringify({
    running: status.running,
    ready: status.ready,
    pid: status.pid,
    exit_code: status.exit_code,
    health: status.health,
  }, null, 2);
  atomicEl('atomic-start').disabled = status.running || !(atomic.preview?.validation?.valid);
  atomicEl('atomic-stop').disabled = !status.running;
  atomicSetState(status.running ? (status.ready ? `Ready · PID ${status.pid}` : `Loading · PID ${status.pid}`) : 'Stopped', status.running ? 'running' : 'ready');

  const logs = await api('/api/atomic/logs?lines=300');
  atomicEl('atomic-log').textContent = logs.text || 'No log output.';
  if (status.running) {
    const metrics = await api('/api/atomic/metrics');
    atomicEl('atomic-metrics-output').textContent = metrics.available ? metrics.text : `Unavailable: ${metrics.reason}`;
  }
  if (status.running && !atomic.statusTimer) {
    atomic.statusTimer = setInterval(() => updateAtomicStatus().catch(console.error), 2500);
  } else if (!status.running && atomic.statusTimer) {
    clearInterval(atomic.statusTimer);
    atomic.statusTimer = null;
  }
}

async function copyAtomicDiagnostics() {
  const diagnostics = await api('/api/atomic/diagnostics');
  await navigator.clipboard.writeText(JSON.stringify(diagnostics, null, 2));
  toast('Redacted Atomic diagnostics copied', 'success');
}

function bindAtomicEvents() {
  atomicEl('atomic-refresh').addEventListener('click', () => refreshAtomicDescription().then(loadAtomicStackDefaults).catch(atomicFailure));
  atomicEl('atomic-stack').addEventListener('change', () => loadAtomicStackDefaults().catch(atomicFailure));
  atomicEl('atomic-preset').addEventListener('change', () => previewAtomic({}, true).catch(atomicFailure));
  atomicEl('atomic-profile').addEventListener('change', event => loadAtomicProfile(event.target.value).catch(atomicFailure));
  atomicEl('atomic-profile-save').addEventListener('click', () => saveAtomicProfile().catch(atomicFailure));
  atomicEl('atomic-profile-delete').addEventListener('click', () => deleteAtomicProfile().catch(atomicFailure));
  atomicEl('atomic-import-legacy').addEventListener('click', () => importAtomicLegacyProfiles().catch(atomicFailure));
  atomicEl('atomic-preview').addEventListener('click', () => previewAtomic().catch(atomicFailure));
  atomicEl('atomic-start').addEventListener('click', () => startAtomic().catch(atomicFailure));
  atomicEl('atomic-stop').addEventListener('click', () => stopAtomic().catch(atomicFailure));
  atomicEl('atomic-copy-diagnostics').addEventListener('click', () => copyAtomicDiagnostics().catch(atomicFailure));
  atomicEl('atomic-prefetch').addEventListener('change', () => updateAtomicApplicability());
  atomicEl('atomic-spec-enabled').addEventListener('change', event => {
    atomicEl('atomic-draft-max').disabled = !event.target.checked;
  });
  document.querySelector('.legacy-editor').addEventListener('toggle', event => {
    document.body.classList.toggle('legacy-open', event.target.open);
  });
}

function atomicFailure(error) {
  console.error(error);
  atomicSetState('Error', 'error');
  const target = atomicEl('atomic-validation');
  target.hidden = false;
  target.className = 'atomic-validation invalid';
  target.textContent = error.message;
  toast(error.message, 'error');
}

document.addEventListener('DOMContentLoaded', async () => {
  try {
    bindAtomicEvents();
    await refreshAtomicDescription();
    await loadAtomicStackDefaults();
    await updateAtomicStatus();
  } catch (error) {
    atomicFailure(error);
  }
});
