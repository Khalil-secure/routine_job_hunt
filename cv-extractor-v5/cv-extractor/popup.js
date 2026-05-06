'use strict';

let extractedData  = null;
let selectedOutput = 'cv';       // 'cv' | 'letter' | 'both'
let selectedLang   = 'fr';       // 'fr' | 'en'
let selectedStyle  = 'two_col';  // 'two_col' | 'one_col'

const API_URL        = 'http://localhost:8000/generate-cv';
const LETTER_API_URL = 'http://localhost:8000/generate-letter';

const PLATFORM_LABELS = {
  linkedin:'LinkedIn', glassdoor:'Glassdoor', indeed:'Indeed',
  wttj:'WTTJ', hellowork:'Hellowork', 'pole-emploi':'Pôle Emploi',
  apec:'APEC', unknown:'?'
};

function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function toast(msg, ms = 1800) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), ms);
}

function initOptionGroups() {
  document.querySelectorAll('.opt-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const group = btn.dataset.group;
      document.querySelectorAll(`.opt-btn[data-group="${group}"]`).forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      if (group === 'output') selectedOutput = btn.dataset.value;
      if (group === 'lang')   selectedLang   = btn.dataset.value;
      if (group === 'style')  selectedStyle  = btn.dataset.value;
    });
  });
}

function bgRequest(msg) {
  return new Promise((resolve) =>
    chrome.runtime.sendMessage(msg, (resp) => resolve(resp || {}))
  );
}

async function detectPlatform() {
  try {
    const { url } = await bgRequest({ action: 'getActiveTab' });
    const key = Object.keys(PLATFORM_LABELS).find(k => (url || '').includes(k)) || 'unknown';
    document.getElementById('platformBadge').textContent = PLATFORM_LABELS[key];
  } catch (_) {}
}

function renderResult(data) {
  const { job } = data;

  // Stats
  document.getElementById('statWords').textContent    = job.word_count || 0;
  document.getElementById('statSkills').textContent   = (job.required_skills || []).length;
  document.getElementById('statContract').textContent = job.contract_type || '?';

  // Job title
  const titleEl = document.getElementById('jobTitle');
  if (titleEl) {
    titleEl.textContent = job.title || '';
    titleEl.style.display = job.title ? 'block' : 'none';
  }

  // Skills
  const grid   = document.getElementById('resultSkills');
  grid.innerHTML = '';
  (job.required_skills || []).slice(0, 20).forEach(s => {
    const chip = document.createElement('span');
    chip.className   = 'skill-chip';
    chip.textContent = s;
    grid.appendChild(chip);
  });
  if ((job.required_skills || []).length > 20) {
    const m = document.createElement('span');
    m.className   = 'skill-chip muted';
    m.textContent = `+${job.required_skills.length - 20}`;
    grid.appendChild(m);
  }

  // Description preview (first 400 chars)
  const desc = job.description || '';
  document.getElementById('descPreview').textContent =
    desc.slice(0, 400) + (desc.length > 400 ? '…' : '');

  showScreen('screenResult');
}

function setLoading(msg, hint = '') {
  document.getElementById('loadingMsg').textContent  = msg;
  document.getElementById('loadingHint').textContent = hint;
}

async function extract() {
  setLoading('Extracting job description…', 'Waiting for page render (up to 8s)');
  showScreen('screenLoading');
  try {
    // Ask background for the real active tab (it holds the activeTab grant)
    const { tabId, url, error: tabErr } = await bgRequest({ action: 'getActiveTab' });
    if (!tabId) throw new Error(tabErr || 'No active tab found.');

    // Inject content script via background (also has activeTab grant)
    await bgRequest({ action: 'injectAndQuery', tabId });

    await new Promise(r => setTimeout(r, 400));

    const response = await chrome.tabs.sendMessage(tabId, { action: 'extract' });
    if (!response?.success) throw new Error(response?.error || 'Extraction failed.');

    extractedData = response.data;
    // Inject user-selected options into meta
    extractedData.meta.lang  = selectedLang;
    extractedData.meta.style = selectedStyle;

    if ((extractedData.job.description || '').length < 150) {
      throw new Error(
        'Could not find a job description on this page.\n\n' +
        '• Make sure you are on a specific job listing page.\n' +
        '• On LinkedIn: open the full job page (click the title, not the card).\n' +
        '• Wait for the page to fully load, then try again.'
      );
    }

    // Show result screen, then auto-trigger selected generation(s)
    renderResult(extractedData);
    if (selectedOutput === 'cv'     || selectedOutput === 'both') generateCV(true);
    if (selectedOutput === 'letter' || selectedOutput === 'both') generateLetter(true);

  } catch (err) {
    const msg = err.message || 'Unknown error';
    // Extraction content failures → paste fallback; hard errors (no tab, etc.) → error screen
    if (msg.includes('Extraction failed') || msg.includes('Could not find')) {
      document.getElementById('pasteArea').value = '';
      document.getElementById('pasteStatus').style.display = 'none';
      showScreen('screenPaste');
    } else {
      document.getElementById('errorMessage').innerHTML = msg.replace(/\n/g, '<br>');
      showScreen('screenError');
    }
  }
}

async function copyJSON() {
  if (!extractedData) return;
  const json = JSON.stringify(extractedData, null, 2);
  try { await navigator.clipboard.writeText(json); }
  catch {
    const ta = document.createElement('textarea');
    ta.value = json; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy');
    document.body.removeChild(ta);
  }
  const btn = document.getElementById('btnCopy');
  btn.textContent = '✅ Copied!';
  btn.classList.add('success');
  toast('JSON copied to clipboard!');
  setTimeout(() => { btn.textContent = '📋 Copy JSON'; btn.classList.remove('success'); }, 2000);
}

function downloadJSON() {
  if (!extractedData) return;
  const json  = JSON.stringify(extractedData, null, 2);
  const blob  = new Blob([json], { type: 'application/json' });
  const url   = URL.createObjectURL(blob);
  const a     = document.createElement('a');
  const date  = new Date().toISOString().slice(0, 10);
  const plat  = extractedData.meta.platform || 'job';
  a.href      = url;
  a.download  = `jobpost_${plat}_${date}.json`;
  a.click();
  URL.revokeObjectURL(url);
  toast('⬇ JSON downloaded!');
}

async function callAPI(url, data) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.timeout = 120000;
    xhr.onload    = () => { try { resolve(JSON.parse(xhr.responseText)); } catch { reject(new Error(`Bad response: ${xhr.responseText.slice(0, 100)}`)); } };
    xhr.onerror   = () => reject(new Error('Cannot reach backend — run: python backend.py'));
    xhr.ontimeout = () => reject(new Error('Timed out after 2 min'));
    xhr.send(JSON.stringify(data));
  });
}

async function generateCV(auto = false) {
  if (!extractedData) return;

  const btn    = document.getElementById('btnGenerateCV');
  const status = document.getElementById('cvStatus');

  btn.disabled    = true;
  btn.textContent = auto ? '⏳ Auto-generating CV…' : '⏳ Generating…';
  status.style.display = 'block';
  status.style.color   = 'var(--muted)';
  status.textContent   = '🤖 Groq is tailoring your CV (~15s)…';

  try {
    const result = await callAPI(API_URL, extractedData);
    if (!result.success) throw new Error(result.error || 'Server error');

    status.style.color = 'var(--green)';
    status.textContent = `✅ ${result.filename}`;
    btn.textContent    = '✅ CV Ready!';
    btn.classList.add('success');
    toast('CV generated!', 3000);

    setTimeout(() => {
      btn.textContent = '🧠 Regenerate CV';
      btn.classList.remove('success');
      btn.disabled = false;
    }, 4000);

  } catch (err) {
    status.style.color = 'var(--red)';
    status.textContent = `❌ ${err.message}`;
    btn.textContent = '🧠 Regenerate CV';
    btn.disabled    = false;
  }
}

async function generateLetter(auto = false) {
  if (!extractedData) return;

  const btn    = document.getElementById('btnGenerateLetter');
  const status = document.getElementById('letterStatus');

  btn.disabled    = true;
  btn.textContent = auto ? '⏳ Auto-writing letter…' : '⏳ Writing letter…';
  status.style.display = 'block';
  status.style.color   = 'var(--muted)';
  status.textContent   = '✍️ Groq is writing your cover letter…';

  try {
    const result = await callAPI(LETTER_API_URL, extractedData);
    if (!result.success) throw new Error(result.error || 'Server error');

    status.style.color = 'var(--green)';
    status.textContent = `✅ ${result.filename}`;
    btn.textContent    = '✅ Letter Ready!';
    btn.classList.add('success');
    toast('Cover letter saved!', 3000);

    setTimeout(() => {
      btn.textContent = '✉️ Regenerate Letter';
      btn.classList.remove('success');
      btn.disabled = false;
    }, 4000);

  } catch (err) {
    status.style.color = 'var(--red)';
    status.textContent = `❌ ${err.message}`;
    btn.textContent = '✉️ Generate Cover Letter';
    btn.disabled    = false;
  }
}

async function generateFromPaste() {
  const text = document.getElementById('pasteArea').value.trim();
  if (!text || text.length < 80) {
    toast('⚠ Paste a longer job description first', 2500);
    return;
  }

  const btn    = document.getElementById('btnPasteGenerate');
  const status = document.getElementById('pasteStatus');
  btn.disabled    = true;
  btn.textContent = '⏳ Generating…';
  status.style.display = 'block';
  status.style.color   = 'var(--muted)';
  status.textContent   = '🤖 Groq is tailoring your CV (~15s)…';

  const words = text.trim().split(/\s+/).length;
  extractedData = {
    meta: { platform: 'manual', source_url: '', lang: selectedLang, style: selectedStyle, company: '' },
    job:  { description: text, title: '', company: '', required_skills: [], word_count: words, contract_type: '?' },
    for_ai: { prompt_ready: text },
  };

  try {
    const result = await callAPI(API_URL, extractedData);
    if (!result.success) throw new Error(result.error || 'Server error');

    status.style.color = 'var(--green)';
    status.textContent = `✅ ${result.filename}`;
    btn.textContent    = '✅ CV Ready!';
    btn.classList.add('success');
    toast('CV generated!', 3000);

    setTimeout(() => {
      btn.textContent = '🧠 Generate CV';
      btn.classList.remove('success');
      btn.disabled = false;
    }, 4000);

  } catch (err) {
    status.style.color = 'var(--red)';
    status.textContent = `❌ ${err.message}`;
    btn.textContent = '🧠 Generate CV';
    btn.disabled    = false;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  detectPlatform();
  initOptionGroups();
  document.getElementById('btnExtract').addEventListener('click',        extract);
  document.getElementById('btnRetry').addEventListener('click',          () => showScreen('screenIdle'));
  document.getElementById('btnReset').addEventListener('click',          () => { extractedData = null; showScreen('screenIdle'); });
  document.getElementById('btnCopy').addEventListener('click',           copyJSON);
  document.getElementById('btnDownload').addEventListener('click',       downloadJSON);
  document.getElementById('btnGenerateCV').addEventListener('click',     () => generateCV());
  document.getElementById('btnGenerateLetter').addEventListener('click', generateLetter);
  document.getElementById('btnPasteGenerate').addEventListener('click',  generateFromPaste);
  document.getElementById('btnPasteBack').addEventListener('click',      () => showScreen('screenIdle'));
});
