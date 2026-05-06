/**
 * content.js — CV Extractor v5
 *
 * PHILOSOPHY: Extract ONE thing perfectly — the job description text.
 * Title/company/location are unreliable in split-view SPAs. Skip them.
 * The AI has the full description — it can figure out the rest.
 *
 * STRATEGY:
 *  1. JSON-LD  → structured data if available (non-auth pages)
 *  2. Anchor   → find description by text markers, extract that container only
 *  3. Aria     → WCAG-stable description selectors
 *  4. Observer → wait for React to render, then retry 1-3
 *  5. Nuclear  → largest clean text block, noise-stripped
 */

'use strict';

const MIN_LEN = 200;

// ─── SKILLS ──────────────────────────────────────────────────────────────────

const SKILLS = [
  'SIEM','Splunk','ELK','Elasticsearch','Suricata','Wireshark','Fortinet',
  'FortiGate','Palo Alto','Cisco ASA','IDS','IPS','pentest','OWASP','ANSSI',
  'CIS','ISO 27001','Zero Trust','IAM','SOC','MITRE','CVE','Vault','WAF',
  'TCP/IP','BGP','OSPF','VLAN','WireGuard','VPN','5G','LTE','FTTH','DNS',
  'HTTP','SNMP','SolarWinds','Centreon','Azure','AWS','GCP','Kubernetes',
  'k8s','Docker','Terraform','Ansible','GitLab','CI/CD','Prometheus','Grafana',
  'IaC','DevOps','DevSecOps','Python','Java','JavaScript','PHP','Bash','Shell',
  'SQL','PowerShell','Go','Rust','Apache','Nginx','WordPress','Jahia',
  'REST API','CMS','TLS','SSL','Agile','Scrum','SAFe','Linux','Windows Server',
  'VMware','Hyper-V','Active Directory','LDAP','Jenkins','Datadog','Zabbix',
  'MongoDB','PostgreSQL','Redis','Kafka','Juniper','Stormshield','Pfsense',
  'CheckPoint','F5','Bluecoat','LangChain','LangGraph','NLP','PyTorch',
  'TensorFlow','Pandas','FastAPI','Flask','Hirschmann','Siemens','Cisco'
];

function extractSkills(text) {
  const found = new Set();
  for (const kw of SKILLS) {
    if (new RegExp(`\\b${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(text))
      found.add(kw);
  }
  return [...found].sort();
}

function detectContract(text) {
  const t = (text || '').toLowerCase();
  if (t.includes('alternance') || t.includes('apprentissage')) return 'Alternance';
  if (t.includes('stage')      || t.includes('internship'))    return 'Stage';
  if (t.includes('freelance')  || t.includes('indépendant'))   return 'Freelance';
  if (t.includes('cdi'))                                        return 'CDI';
  if (t.includes('cdd'))                                        return 'CDD';
  if (t.includes('mission')    || t.includes('consultant'))    return 'Mission';
  if (t.includes('full-time')  || t.includes('temps plein'))   return 'CDI';
  return '';
}

const clean = t => (t || '').replace(/\s+/g, ' ').trim();

function detectPlatform() {
  const h = window.location.hostname;
  if (h.includes('linkedin.com'))           return 'linkedin';
  if (h.includes('glassdoor'))              return 'glassdoor';
  if (h.includes('indeed'))                 return 'indeed';
  if (h.includes('welcometothejungle.com')) return 'wttj';
  if (h.includes('hellowork.com'))          return 'hellowork';
  if (h.includes('pole-emploi.fr'))         return 'pole-emploi';
  if (h.includes('apec.fr'))               return 'apec';
  return 'unknown';
}

// ─── NOISE CLEANER ───────────────────────────────────────────────────────────
// Strip known platform UI strings that leak into description text.

const NOISE_PATTERNS = [
  /^\d+\s+notifications?\s*/gim,
  /^Passer au contenu principal\s*/gim,
  /^Accueil\s+Mon réseau.*/gim,
  /^Messagerie\s+\d+.*/gim,
  /Candidature simplifiée/gi,
  /^Enregistrer\s*$/gim,
  /Réactiver Premium/gi,
  /Découvrez comment vous vous positionnez[^.]*\./gi,
  /Accédez à des informations exclusives[^.]*\./gi,
  /Promue par un recruteur[^.]*\./gi,
  /Évaluation des candidatures en cours/gi,
  /^Sur site\s*$/gim,
  /^Temps plein\s*$/gim,
  /^Temps partiel\s*$/gim,
  /^Hybride\s*$/gim,
  /^Télétravail\s*$/gim,
  /Republication il y a[^·\n]*/gi,
  /il y a \d+ (semaine|mois|jour)s?/gi,
  /Plus de \d+ candidatures/gi,
  /Personnes que vous pouvez contacter/gi,
  /Rencontrez l['']équipe de recrutement/gi,
  /Auteur de l['']offre d['']emploi/gi,
  /Envoyer un message/gi,
  /Pour les entreprises/gi,
  /^\s*\d+(er|e|ème)\s+/gim,
];

// Everything after these markers is not the job description
const TRUNCATE_AT = [
  'À propos de l\'entreprise',
  'About the company',
  'Activer une alerte emploi',
  'Set a job alert',
  'Aimeriez-vous travailler avec nous',
  'Des recherches d\'emploi plus rapides',
  'Faster job search',
  'Annulez à tout moment',
  // Glassdoor
  'Apply Now',
  'Postuler',
  'Similar Jobs',
  'Emplois similaires',
];

function stripNoise(text) {
  // Truncate at end markers
  for (const marker of TRUNCATE_AT) {
    const idx = text.indexOf(marker);
    if (idx > 100) { text = text.slice(0, idx); break; }
  }
  // Strip noise patterns
  for (const rx of NOISE_PATTERNS) text = text.replace(rx, '');
  // Collapse excess blank lines
  return clean(text.replace(/\n{3,}/g, '\n\n'));
}

// ─── TITLE EXTRACTION ────────────────────────────────────────────────────────

const TITLE_SELECTORS = [
  // LinkedIn
  'h1[class*="top-card-layout__title"]',
  'h1[class*="job-details-jobs-unified-top-card__job-title"]',
  '.job-details-jobs-unified-top-card__job-title h1',
  '.jobs-unified-top-card__job-title h1',
  // Indeed
  'h1[class*="jobsearch-JobInfoHeader-title"]',
  'h1[data-testid="jobsearch-JobInfoHeader-title"]',
  // WTTJ
  'h1[class*="job-title"]',
  'h2[class*="job-title"]',
  // Glassdoor
  'h1[class*="heading"]',
  'h1[data-test="job-title"]',
  // APEC / Hellowork
  'h1[class*="title"]',
  // Generic fallback
  'h1',
];

function extractTitle() {
  // 1. JSON-LD
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const data  = JSON.parse(s.textContent.trim());
      const items = data['@graph'] || [data];
      for (const item of items) {
        if (item['@type'] === 'JobPosting' && item.title)
          return clean(item.title);
      }
    } catch (_) {}
  }

  // 2. Platform selectors
  for (const sel of TITLE_SELECTORS) {
    try {
      const el = document.querySelector(sel);
      if (el) {
        const t = clean(el.innerText || el.textContent || '');
        if (t.length > 2 && t.length < 120) return t;
      }
    } catch (_) {}
  }

  return '';
}

// ─── LAYER 1: JSON-LD ────────────────────────────────────────────────────────

function fromJsonLD() {
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const data  = JSON.parse(s.textContent.trim());
      const items = data['@graph'] || [data];
      for (const item of items) {
        if (item['@type'] !== 'JobPosting') continue;
        const desc = clean((item.description || '').replace(/<[^>]+>/g, ' '));
        if (desc.length > MIN_LEN) return desc;
      }
    } catch (_) {}
  }
  return '';
}

// ─── LAYER 2: ANCHOR EXTRACTION ──────────────────────────────────────────────
// Find the description section by its text markers — no class names needed.
// Works even when LinkedIn strips JSON-LD on authenticated sessions.

const DESC_START_MARKERS = [
  'À propos de l\'offre d\'emploi',
  'About the job',
  'Job description',
  'Description du poste',
  'À propos du poste',
  'Vos missions',
  'Le poste',
  'La mission',
  'Votre mission',
  'Présentation du poste',
];

const DESC_CONTAINER_SELECTORS = [
  // LinkedIn — single job page
  '#job-details',
  '#job-description',
  '[aria-label="Job description"]',
  '[class*="jobs-description__content"]',
  '[class*="description__text"]',
  // LinkedIn — two-column split view (right panel)
  '[class*="jobs-search__job-details"]',
  '[class*="jobs-details__main-content"]',
  '[class*="job-details-jobs-unified-top-card"]',
  '[class*="jobs-description-content"]',
  '[class*="jobs-box__html-content"]',
  'div[class*="scaffold-layout__detail"]',
  // Glassdoor
  '[class*="JobDetails_jobDescription"]',
  '[data-test="jobDescriptionContent"]',
  '[class*="jobDescription"]',
  '[id*="JobDesc"]',
  // WTTJ
  '[data-testid="job-section-description"]',
  '[data-testid="job-description"]',
  // Generic
  '[class*="job-description"]',
  '[class*="jobDescription"]',
  '[id*="job-description"]',
  'article[class*="job"]',
];

function fromAnchor() {
  // First: try known description container selectors
  for (const sel of DESC_CONTAINER_SELECTORS) {
    try {
      const el = document.querySelector(sel);
      if (el) {
        const t = stripNoise(el.innerText || '');
        if (t.length > MIN_LEN) return t;
      }
    } catch (_) {}
  }

  // Second: find by text marker using TreeWalker
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_ELEMENT,
    {
      acceptNode(node) {
        if (['SCRIPT','STYLE','NAV','HEADER','FOOTER'].includes(node.tagName))
          return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    }
  );

  let node;
  while ((node = walker.nextNode())) {
    const text = (node.innerText || '').trim();
    if (text.length > 30000 || text.length < 10) continue;

    for (const marker of DESC_START_MARKERS) {
      if (!text.includes(marker)) continue;

      // Found a container with our marker — find the tightest child
      let best = node;
      for (const child of node.querySelectorAll('*')) {
        const ct = (child.innerText || '').trim();
        if (ct.includes(marker) && ct.length < best.innerText.length && ct.length > MIN_LEN) {
          best = child;
        }
      }

      // Extract and strip the marker header itself + noise
      let desc = (best.innerText || '').trim();
      for (const m of DESC_START_MARKERS) desc = desc.replace(m, '');
      desc = stripNoise(desc);
      if (desc.length > MIN_LEN) return desc;
    }
  }

  return '';
}

// ─── LAYER 3: MUTATION OBSERVER ──────────────────────────────────────────────

function waitForDescription() {
  return new Promise(resolve => {
    const check = () => {
      const d = fromJsonLD() || fromAnchor();
      if (d.length > MIN_LEN) { resolve(d); return true; }
      return false;
    };

    if (check()) return;

    const obs = new MutationObserver(() => { if (check()) obs.disconnect(); });
    obs.observe(document.body, { childList: true, subtree: true, characterData: true });
    setTimeout(() => { obs.disconnect(); resolve(''); }, 12000);
  });
}

// ─── LAYER 4: CLEANED NUCLEAR ────────────────────────────────────────────────

function fromNuclear() {
  const skip = new Set(['SCRIPT','STYLE','NAV','HEADER','FOOTER','NOSCRIPT']);
  let best   = '';

  document.querySelectorAll('div,section,article,main').forEach(el => {
    if (skip.has(el.tagName) || el.closest('nav,header,footer')) return;
    const t = (el.innerText || '').trim();
    if (t.length > best.length && t.length < 40000 && (t.match(/\n/g)||[]).length > 4)
      best = t;
  });

  return best ? stripNoise(best) : '';
}

// ─── LAYER 5: LINKEDIN NUCLEAR ───────────────────────────────────────────────
// LinkedIn blocks JSON-LD on auth sessions and rotates class names constantly.
// Strategy: wait for the SPA to settle, then take the largest clean text block.

async function waitForLinkedIn() {
  return new Promise(resolve => {
    const attempt = () => {
      const d = fromNuclear();
      return d.length > MIN_LEN ? d : '';
    };

    const immediate = attempt();
    if (immediate) { resolve(immediate); return; }

    const obs = new MutationObserver(() => {
      const d = attempt();
      if (d) { obs.disconnect(); resolve(d); }
    });
    obs.observe(document.body, { childList: true, subtree: true, characterData: true });
    setTimeout(() => { obs.disconnect(); resolve(fromNuclear()); }, 12000);
  });
}

// ─── MAIN ────────────────────────────────────────────────────────────────────

async function extractJobPost() {
  const platform = detectPlatform();

  let description;

  if (platform === 'linkedin') {
    // Skip JSON-LD and anchor layers — LinkedIn blocks both on authenticated pages.
    // Go straight to nuclear extraction with DOM-settle wait.
    description = await waitForLinkedIn();
  } else {
    // Standard cascade for all other platforms
    description = fromJsonLD() || fromAnchor();
    if (description.length < MIN_LEN) {
      description = await waitForDescription();
    }
    if (description.length < MIN_LEN) {
      description = fromNuclear();
    }
  }

  const skills   = extractSkills(description);
  const contract = detectContract(description);
  const title    = extractTitle();

  return {
    meta: {
      extracted_at: new Date().toISOString(),
      source_url:   window.location.href,
      platform,
    },
    job: {
      title,
      description,
      contract_type:   contract,
      required_skills: skills,
      word_count:      description.split(/\s+/).filter(Boolean).length,
    },
    for_ai: {
      instruction:  'Use the candidate profile JSON (cv_master_profile.json) and this job post to write a targeted 450-word CV in French. Mirror the job vocabulary exactly. Select only the most relevant experience, skills and projects. Never invent anything.',
      prompt_ready: `Job Title: ${title || 'unknown'}\nContract: ${contract}\n\nJob Description:\n${description}`
    }
  };
}

// ─── LISTENER ────────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'extract') {
    extractJobPost()
      .then(data => sendResponse({ success: true, data }))
      .catch(err  => sendResponse({ success: false, error: err.message }));
    return true;
  }
});
