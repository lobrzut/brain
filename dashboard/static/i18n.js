// Lightweight i18n for the Brain dashboard. Dictionaries in /i18n/<lang>.json.
const SUPPORTED_LANGS = ['pl', 'en', 'de', 'uk'];
const LANG_NAMES = { pl: 'Polski', en: 'English', de: 'Deutsch', uk: 'Українська' };
const I18N_CACHE_BUST =
  document.currentScript?.src?.split('v=')[1]?.split('&')[0] || Date.now();
let translations = {};
let currentLang = 'pl';

function detectLang() {
  const saved = localStorage.getItem('brain_lang');
  if (saved && SUPPORTED_LANGS.includes(saved)) return saved;
  const nav = (navigator.language || 'pl').slice(0, 2).toLowerCase();
  return SUPPORTED_LANGS.includes(nav) ? nav : 'pl';
}

async function loadLanguage(lang) {
  if (!SUPPORTED_LANGS.includes(lang)) lang = 'pl';
  if (!translations[lang]) {
    const res = await fetch(`/i18n/${lang}.json?v=${I18N_CACHE_BUST}`);
    if (!res.ok) throw new Error(`i18n load failed: ${lang} (${res.status})`);
    translations[lang] = await res.json();
  }
  currentLang = lang;
  localStorage.setItem('brain_lang', lang);
  document.documentElement.lang = lang;
  return translations[lang];
}

function t(key, vars = {}) {
  let str = translations[currentLang]?.[key] || translations.pl?.[key] || key;
  Object.entries(vars).forEach(([k, v]) => { str = str.replace(`{${k}}`, v); });
  return str;
}

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    const attr = el.dataset.i18nAttr;
    const text = t(el.dataset.i18n);
    if (attr) el.setAttribute(attr, text);
    else el.textContent = text;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
}

// Populate a <select> with the language options and wire switching.
function initLangSwitchers(onChange) {
  document.querySelectorAll('select[data-lang-select]').forEach((sel) => {
    sel.innerHTML = SUPPORTED_LANGS.map(
      (l) => `<option value="${l}">${LANG_NAMES[l]}</option>`
    ).join('');
    sel.value = currentLang;
    sel.onchange = async () => {
      await loadLanguage(sel.value);
      applyI18n();
      document.querySelectorAll('select[data-lang-select]').forEach((s) => { s.value = currentLang; });
      if (onChange) onChange(currentLang);
    };
  });
}
