/* VertCut — клиент */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Какой экран создания клипов выбран в настройках.
const wizardInterface = () => (localStorage.getItem("vertcut.interface") || "wizard") === "wizard";

const fmtDur = (sec) => {
  sec = Math.max(0, Math.round(sec || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
};

const plural = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 0 || (m10 >= 5 && m10 <= 9) || (m100 >= 11 && m100 <= 14)) return many;
  if (m10 === 1) return one;
  return few;
};

const ICONS = {
  play: '<svg viewBox="0 0 24 24" fill="white"><path d="M8 5.14v13.72c0 .8.87 1.3 1.56.9l11.2-6.86a1.05 1.05 0 0 0 0-1.8L9.56 4.24A1.05 1.05 0 0 0 8 5.14z"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>',
  zip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 8v13H3V8M1 3h22v5H1zM10 12h4"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5m7-7-7 7 7 7"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  spark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1M7.7 16.3l-2.1 2.1"/></svg>'
};

const ACCENT_OPTIONS = [
  ["yellow", "#FFE24A", "Жёлтый"], ["gold", "#FFC53D", "Золото"],
  ["orange", "#FF8A3D", "Оранжевый"], ["coral", "#FF6B6B", "Коралл"],
  ["red", "#FF3D57", "Красный"], ["rose", "#FF5C8A", "Роза"],
  ["pink", "#FF6BD6", "Розовый"], ["magenta", "#E84BFF", "Маджента"],
  ["violet", "#B36BFF", "Фиолетовый"], ["purple", "#8B5CF6", "Пурпур"],
  ["indigo", "#6B7CFF", "Индиго"], ["blue", "#3D8BFF", "Синий"],
  ["sky", "#3DC8FF", "Небесный"], ["cyan", "#6BE8FF", "Циан"],
  ["teal", "#2DE0C8", "Бирюза"], ["mint", "#6BFFB0", "Мята"],
  ["green", "#6BFF8C", "Зелёный"], ["lime", "#C6FF4A", "Лайм"],
  ["peach", "#FFB38A", "Персик"], ["lavender", "#C9B6FF", "Лаванда"],
  ["white", "#FFFFFF", "Белый"]
];
const ACCENT_HEX = Object.fromEntries(ACCENT_OPTIONS.map(([k, c]) => [k, c]));

function swatchesHTML(selected) {
  return ACCENT_OPTIONS.map(([key, color, label]) =>
    `<button class="swatch ${selected === key ? "active" : ""}" data-val="${key}" style="background:${color}" title="${label}"></button>`
  ).join("");
}

const BUNDLED_FONT_OPTIONS = [
  { key: "montserrat", label: "Montserrat", group: "База" },
  { key: "inter", label: "Inter Black", group: "База" },
  { key: "manrope", label: "Manrope ExtraBold", group: "База" },
  { key: "robotocond", label: "Roboto Condensed", group: "База" },
  { key: "lato", label: "Lato Black", group: "База" },
  { key: "ptsans", label: "PT Sans Narrow", group: "Узкие" },
  { key: "oswald", label: "Oswald", group: "Узкие" },
  { key: "rubik", label: "Rubik ExtraBold", group: "Плотные" },
  { key: "exo2", label: "Exo 2", group: "Плотные" },
  { key: "unbounded", label: "Unbounded", group: "Плотные" },
  { key: "russo", label: "Russo One", group: "Акцентные" },
  { key: "play", label: "Play", group: "Акцентные" },
  { key: "philosopher", label: "Philosopher", group: "Акцентные" },
  { key: "yeseva", label: "Yeseva One", group: "Акцентные" },
  { key: "comfortaa", label: "Comfortaa", group: "Акцентные" },
  { key: "caveat", label: "Caveat", group: "Акцентные" },
  { key: "golos", label: "Golos Text", group: "CapCut" },
  { key: "onest", label: "Onest", group: "CapCut" },
  { key: "marmelad", label: "Marmelad", group: "CapCut" },
  { key: "badscript", label: "Bad Script", group: "Акцентные" },
  { key: "marckscript", label: "Marck Script", group: "Акцентные" },
  { key: "ruslan", label: "Ruslan Display", group: "Акцентные" },
  { key: "stalinist", label: "Stalinist One", group: "Акцентные" },
  { key: "underdog", label: "Underdog", group: "Акцентные" }
];

const BUNDLED_GROUPS = Object.fromEntries(BUNDLED_FONT_OPTIONS.map((f) => [f.key, f.group]));
let FONT_OPTIONS = BUNDLED_FONT_OPTIONS.slice();

function fontOptionsHTML(selected) {
  const groups = [];
  FONT_OPTIONS.forEach((f) => { if (!groups.includes(f.group)) groups.push(f.group); });
  return groups.map((g) => `<optgroup label="${esc(g)}">` + FONT_OPTIONS
    .filter((f) => f.group === g)
    .map((f) => `<option value="${esc(f.key)}" ${selected === f.key ? "selected" : ""}>${esc(f.label)}</option>`)
    .join("") + "</optgroup>").join("");
}

const BUNDLED_FONT_CSS = {
  montserrat: "VCMontserrat",
  russo: "VCRusso",
  ptsans: "VCPTSans",
  lato: "VCLato",
  play: "VCPlay",
  philosopher: "VCPhilosopher",
  oswald: "VCOswald",
  robotocond: "VCRobotoCond",
  inter: "VCInter",
  rubik: "VCRubik",
  manrope: "VCManrope",
  unbounded: "VCUnbounded",
  caveat: "VCCaveat",
  yeseva: "VCYeseva",
  exo2: "VCExo2",
  comfortaa: "VCComfortaa",
  golos: "VCGolos",
  onest: "VCOnest",
  marmelad: "VCMarmelad",
  badscript: "VCBadScript",
  marckscript: "VCMarckScript",
  ruslan: "VCRuslan",
  stalinist: "VCStalinist",
  underdog: "VCUnderdog"
};
let FONT_CSS = { ...BUNDLED_FONT_CSS };

async function loadFontCatalog() {
  try {
    const data = await api("/api/fonts");
    if (!Array.isArray(data) || !data.length) return;
    FONT_OPTIONS = data.map((f) => ({
      key: f.key,
      label: f.label,
      group: f.custom ? "Мои шрифты" : (BUNDLED_GROUPS[f.key] || "Другие")
    }));
    FONT_CSS = { ...BUNDLED_FONT_CSS };
    data.forEach((f) => { if (f.css) FONT_CSS[f.key] = f.css; });
  } catch (_) { /* офлайн: остаёмся на встроенных */ }
}

function refreshFontSelects(selected, target) {
  ["#fontSelect", "#tpFont", "#edFont"].forEach((sel) => {
    const el = $(sel);
    if (!el) return;
    const value = (target && sel === target) ? selected : el.value;
    el.innerHTML = fontOptionsHTML(value);
  });
}

async function uploadFont(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  let entry;
  try {
    const res = await fetch("/api/fonts", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Не удалось загрузить шрифт");
    entry = data;
  } catch (err) {
    toast(err.message, "err");
    return;
  }
  const link = $("#customFontsCss");
  if (link) link.href = "/api/fonts.css?v=" + Date.now();
  await loadFontCatalog();
  const target = state.fontTarget || "#fontSelect";
  refreshFontSelects(entry.key, target);
  state.opts.subFont = entry.key;
  const select = $(target);
  if (select) {
    select.value = entry.key;
    select.dispatchEvent(new Event("change"));
  }
  toast(`Шрифт «${entry.label}» добавлен`);
  if (entry.has_cyrillic === false) {
    setTimeout(() => toast("В этом шрифте нет кириллицы — русские буквы могут замениться", "err"), 500);
  }
}

const SUB_POSITIONS = [
  ["bottom", "Снизу"],
  ["middle", "По центру"],
  ["top", "Сверху"]
];


const OPT_ICONS = {
  count: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h10"/></svg>',
  duration: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  aspect: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="6" y="3" width="12" height="18" rx="2.5"/></svg>',
  frame: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8V4h4M20 8V4h-4M4 16v4h4M20 16v4h-4"/></svg>',
  subs: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 10h5M7 14h9"/></svg>',
  style: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 18 8.5 6 13 18M6 14h5"/><path d="M17 18v-4.5a2.5 2.5 0 0 1 5 0V18"/></svg>',
  access: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="10" width="14" height="10" rx="3"/><path d="M8 10V8a4 4 0 0 1 8 0v2"/></svg>',
};
function optIcon(name, tone) {
  return `<span class="opt-ico ${tone || "ico-purple"}">${OPT_ICONS[name] || ""}</span>`;
}

const SUB_SPEEDS = [
  ["calm", "Спокойно"],
  ["normal", "Обычно"],
  ["fast", "Быстро"]
];

// Сдвиг субтитров — в пикселях кадра 1080x1920: от нижнего края до верхнего.
const SUB_OFFSET_MIN = -1600;
const SUB_OFFSET_MAX = 1600;
const pxClamp = (value, low, high) => Math.min(high, Math.max(low, value));
const SPEED_MS = { calm: 640, normal: 440, fast: 300 };

const STYLE_PRESETS = [
  { key: "tiktok", label: "TikTok", opts: { subFont: "montserrat", subSize: 132, subPos: "bottom", subOffset: 10, accent: "yellow", uppercase: true } },
  { key: "reels", label: "Reels", opts: { subFont: "lato", subSize: 118, subPos: "middle", subOffset: 0, accent: "pink", uppercase: true } },
  { key: "soft", label: "Мягкий", opts: { subFont: "play", subSize: 110, subPos: "bottom", subOffset: 0, accent: "cyan", uppercase: false } },
  { key: "classic", label: "Классика", opts: { subFont: "ptsans", subSize: 122, subPos: "bottom", subOffset: 0, accent: "yellow", uppercase: true } },
  { key: "sport", label: "Спорт", opts: { subFont: "oswald", subSize: 132, subPos: "bottom", subOffset: 10, accent: "green", uppercase: true } },
  { key: "bold", label: "Дерзкий", opts: { subFont: "unbounded", subSize: 112, subPos: "middle", subOffset: 0, accent: "pink", uppercase: true } },
  { key: "hand", label: "Рукописный", opts: { subFont: "caveat", subSize: 152, subPos: "bottom", subOffset: 0, accent: "yellow", uppercase: false } },
  { key: "capcut", label: "CapCut", opts: { subFont: "golos", subSize: 126, subPos: "bottom", subOffset: 10, accent: "lime", uppercase: true } },
  { key: "meme", label: "Мем", opts: { subFont: "stalinist", subSize: 112, subPos: "middle", subOffset: 0, accent: "red", uppercase: true } },
  { key: "neon", label: "Неон", opts: { subFont: "onest", subSize: 124, subPos: "bottom", subOffset: 0, accent: "cyan", uppercase: true } },
  { key: "beauty", label: "Бьюти", opts: { subFont: "marmelad", subSize: 124, subPos: "bottom", subOffset: 0, accent: "pink", uppercase: false } },
  { key: "brush", label: "Кисть", opts: { subFont: "underdog", subSize: 128, subPos: "bottom", subOffset: 0, accent: "orange", uppercase: false } },
  { key: "script", label: "Скрипт", opts: { subFont: "marckscript", subSize: 142, subPos: "bottom", subOffset: 0, accent: "lavender", uppercase: false } }
];

const UNIQ_PRESETS = [
  { key: "off", label: "Без", opts: { hflip: false, tilt: 0, speed: 1, pitch: 1, jumpCuts: false, cutZoom: false } },
  { key: "mirror", label: "Зеркало", opts: { hflip: true, tilt: 0, speed: 1, pitch: 1, jumpCuts: false, cutZoom: false } },
  { key: "mirror_tilt", label: "Зеркало + наклон 0.5°", opts: { hflip: true, tilt: 0.5, speed: 1, pitch: 1, jumpCuts: false, cutZoom: false } },
  { key: "light", label: "Лёгкий динамичный", opts: { hflip: true, tilt: 0.5, speed: 1.03, pitch: 1, jumpCuts: true, cutZoom: true } },
  { key: "strong", label: "Сильный динамичный", opts: { hflip: true, tilt: 1.0, speed: 1.06, pitch: 1.01, jumpCuts: true, cutZoom: true } }
];

const AUDIO_LANG_LABELS = {
  rus: "Русский", russian: "Русский",
  jpn: "Японский", japanese: "Японский",
  eng: "Английский", english: "Английский",
  ukr: "Украинский", ukrainian: "Украинский",
  deu: "Немецкий", ger: "Немецкий",
  fra: "Французский", fre: "Французский",
  spa: "Испанский", ita: "Итальянский",
  kor: "Корейский", zho: "Китайский", chi: "Китайский"
};

function audioTrackLabel(track) {
  const lang = AUDIO_LANG_LABELS[(track.language || "").toLowerCase()] ||
    (track.language ? String(track.language).toUpperCase() : "Без языка");
  const codec = String(track.codec || "").toUpperCase();
  const channels = track.channels ? `, ${track.channels}` : "";
  return `${lang}${codec ? ` · ${codec}${channels}` : ""}${track.default ? " · по умолчанию" : ""}`;
}

const DUR_PRESETS = {
  "15-30": { min: 15, max: 30, target: 22, label: "15–30 сек" },
  "20-45": { min: 20, max: 45, target: 32, label: "20–45 сек" },
  "30-60": { min: 30, max: 60, target: 42, label: "30–60 сек" },
  "30-90": { min: 30, max: 90, target: 55, label: "30–90 сек" },
  "60-120": { min: 60, max: 120, target: 90, label: "1–2 мин" },
  "120-180": { min: 120, max: 180, target: 150, label: "2–3 мин" },
  "61-90": { min: 61, max: 90, target: 75, label: "61–90 сек" }
};

const PLATFORM_ZONES = {
  universal: { top: 200, bottom: 484 },
  shorts: { top: 140, bottom: 360 },
  tiktok: { top: 130, bottom: 484 },
  reels: { top: 200, bottom: 420 },
  none: { top: 0, bottom: 320 }
};

const ASPECT_META = {
  "9:16": { short: "Вертикально", hint: "Shorts, Reels, TikTok", w: 9, h: 16 },
  "1:1": { short: "Квадрат", hint: "лента Instagram, VK", w: 1, h: 1 },
  "16:9": { short: "Горизонтально", hint: "обычное видео, YouTube", w: 16, h: 9 }
};

const aspectIcon = (a) => {
  const m = ASPECT_META[a];
  if (!m) return "";
  const box = 20;
  const k = box / Math.max(m.w, m.h);
  const w = Math.round(m.w * k);
  const h = Math.round(m.h * k);
  return `<span class="aspect-ico" style="width:${w}px;height:${h}px"></span>`;
};

const PLATFORM_OPTIONS = [
  ["universal", "Универсально"],
  ["shorts", "Shorts"],
  ["tiktok", "TikTok"],
  ["reels", "Reels"],
  ["none", "Без зон"]
];

const EXAMPLE_ASPECTS = ["9:16", "1:1", "16:9"];

function examplesHTML(o) {
  const aspect = (key) => {
    const m = ASPECT_META[key];
    const box = 30;
    const k = box / Math.max(m.w, m.h);
    const w = Math.round(m.w * k * 1.7);
    const h = Math.round(m.h * k * 1.7);
    return `<button type="button" class="ex-opt ${o.aspect === key ? "active" : ""}" data-group="aspect" data-val="${key}" title="${m.hint}">
      <span class="ex-frame" style="width:${w}px;height:${h}px"><i class="ex-face"></i></span>
      <span class="ex-cap">${m.short}</span>
    </button>`;
  };
  const zone = (key, label) => {
    const z = PLATFORM_ZONES[key] || PLATFORM_ZONES.universal;
    const top = Math.round((z.top / 1920) * 100);
    const bottom = Math.round((z.bottom / 1920) * 100);
    const bands = key === "none" ? "" :
      `<i class="ex-zone top" style="height:${top}%"></i><i class="ex-zone bottom" style="height:${bottom}%"></i>`;
    return `<button type="button" class="ex-opt ${o.platform === key ? "active" : ""}" data-group="platform" data-val="${key}" title="${label}">
      <span class="ex-frame zone">${bands}<i class="ex-caption"></i></span>
      <span class="ex-cap">${label}</span>
    </button>`;
  };
  const frames = [
    ["auto", "Умный кроп"],
    ["blur", "Размытый фон"],
    ["crop", "По центру"]
  ];
  const frame = ([key, label]) => `<button type="button" class="ex-opt ${o.mode === key ? "active" : ""}" data-group="mode" data-val="${key}" title="${label}">
      <span class="ex-frame zone mode-${key}">
        ${key === "auto" ? `<i class="ex-crop"></i><i class="ex-face"></i>` : ""}
        ${key === "blur" ? `<i class="ex-blur"></i>` : ""}
        ${key === "crop" ? `<i class="ex-crop center"></i>` : ""}
      </span>
      <span class="ex-cap">${label}</span>
    </button>`;
  return `
    <div class="ex-card">
      <div class="ex-head"><b>Формат</b><span>как будет выглядеть кадр</span></div>
      <div class="ex-row">${EXAMPLE_ASPECTS.map(aspect).join("")}</div>
    </div>
    <div class="ex-card">
      <div class="ex-head"><b>Зоны площадки</b><span>место под интерфейс приложения</span></div>
      <div class="ex-row">${PLATFORM_OPTIONS.map(([k, v]) => zone(k, v)).join("")}</div>
    </div>
    <div class="ex-card">
      <div class="ex-head"><b>Кадр</b><span>как заполняется вертикаль</span></div>
      <div class="ex-row">${frames.map(frame).join("")}</div>
    </div>
    <div class="ex-note">Нажмите на пример, чтобы выбрать вариант.</div>`;
}

function syncExamples() {
  const o = state.opts;
  $$("#examples .ex-opt").forEach((b) => {
    b.classList.toggle("active", String(o[b.dataset.group]) === b.dataset.val);
  });
  const input = $("#countInput");
  if (input) input.value = o.count > 0 ? String(o.count) : "";
}

// Общие настройки кадра для новых видео: мастер и старый экран берут их при запуске.
const DEFAULTS_KEY = "vertcut.defaults";
const FRAME_DEFAULTS = ["aspect", "mode", "platform", "layout"];

function loadFrameDefaults() {
  try {
    const stored = JSON.parse(localStorage.getItem(DEFAULTS_KEY) || "{}");
    const out = {};
    for (const key of FRAME_DEFAULTS) {
      if (stored[key] != null && stored[key] !== "") out[key] = stored[key];
    }
    return out;
  } catch (_) {
    return {};
  }
}

function saveFrameDefaults(patch) {
  const current = { ...loadFrameDefaults(), ...patch };
  localStorage.setItem(DEFAULTS_KEY, JSON.stringify(current));
  Object.assign(state.opts, current);
  return current;
}

const THEME_KEY = "vertcut.theme";

const MOTION_KEY = "vertcut.motion";

function currentMotion() {
  return localStorage.getItem(MOTION_KEY) || document.documentElement.dataset.motion || "on";
}

function applyMotion(on) {
  const value = on ? "on" : "off";
  localStorage.setItem(MOTION_KEY, value);
  document.documentElement.dataset.motion = value;
  const box = document.getElementById("setMotion");
  if (box) box.checked = value === "on";
}

function currentTheme() {
  return localStorage.getItem(THEME_KEY) || document.documentElement.dataset.theme || "dark";
}

function applyTheme(mode) {
  const theme = mode === "light" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, theme);
  document.documentElement.dataset.theme = theme;
  const link = document.getElementById("themeCss");
  if (link) link.href = theme === "light" ? "/static/styles-light.css?v=3" : "/static/styles.css?v=24";
  const label = document.getElementById("themeLabel");
  if (label) label.textContent = theme === "light" ? "Тёмная тема" : "Светлая тема";
  $$('input[name="wzTheme"]').forEach((el) => { el.checked = el.value === theme; });
}

function syncThemeButton() {
  const label = document.getElementById("themeLabel");
  if (label) label.textContent = currentTheme() === "light" ? "Тёмная тема" : "Светлая тема";
}

function syncHeroFrameOptions() {
  for (const key of FRAME_DEFAULTS) {
    $$(`.seg[data-group="${key}"] button`).forEach((b) => {
      b.classList.toggle("active", String(b.dataset.val) === String(state.opts[key]));
    });
  }
}

function adhdLimits() {
  const split = state.health && state.health.adhd_split;
  return { min: Number(split && split.min) || 40, max: Number(split && split.max) || 85 };
}

const state = {
  projects: [],
  current: null,
  detail: null,
  pollTimer: null,
  mainKey: "",
  health: null,
  system: null,
  probeOpen: false,
  probeUrl: "",
  probeData: null,
  segmentsChoice: false,
  tmplPid: null,
  tmplTimer: null,
  tmplAnim: null,
  tmplDetail: null,
  tmplUniq: null,
  pendingFile: null,
  pendingSubs: null,
  subsToTemplate: false,
  clipView: { mood: "any", type: "any", sort: "chrono" },
  opts: {
    count: 10,
    dur: "20-45",
    aspect: "9:16",
    mode: "auto",
    select: "smart",
    picker: "local",
    moods: "any",
    minScore: 0,
    subtitles: true,
    accent: "yellow",
    subFont: "montserrat",
    subSize: 118,
    subPos: "bottom",
    subOffset: 0,
    subSpeed: "calm",
    lineGap: 0,
    keepFps: true,
    exportSubs: false,
    look: "none",
    vignette: false,
    grain: false,
    zoom: 100,
    bitrate: 0,
    musicVolume: 8,
    hflip: false,
    tilt: 0,
    speed: 1,
    pitch: 1,
    jumpCuts: false,
    cutZoom: false,
    bgVideo: "random",
    splitRatio: 0.5,
    adhdBg: "",
    adhdTopFill: "cover",
    adhdBottomFill: "cover",
    adhdTopScale: 1,
    adhdTopX: 0,
    adhdTopY: 0,
    adhdBottomScale: 1,
    adhdBottomX: 0,
    adhdBottomY: 0,
    adhdBottomSpeed: 1,
    adhdBottomStart: -1,
    adhdBottomVolume: 0,
    platform: "universal",
    layout: "",
    cookies: "",
    fontTarget: "#fontSelect"
  }
};

// Значения по умолчанию из настроек: новые проекты сразу с нужным форматом.
Object.assign(state.opts, loadFrameDefaults());

/* ---------------- API ---------------- */

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      msg = data.detail || msg;
    } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

function toast(text, kind) {
  const node = document.createElement("div");
  node.className = "toast" + (kind === "err" ? " err" : "");
  node.textContent = text;
  $("#toasts").appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

/* ---------------- Sidebar ---------------- */

function updateActiveBar() {
  const bar = $("#activeBar");
  if (!bar) return;
  const active = state.projects.find((p) =>
    ["queued", "preparing", "running", "processing"].includes(p.status));
  if (!active) {
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }
  bar.classList.remove("hidden");
  bar.dataset.project = active.id;
  bar.innerHTML = `<span class="spinner"></span>
    <span class="ab-text">${esc(active.title || "Проект")} · ${esc(active.stage || "обработка")} · ${Math.round(active.progress || 0)}%</span>
    <span class="ab-open">открыть</span>`;
}

function renderSidebar() {
  const list = $("#projectList");
  if (!state.projects.length) {
    list.innerHTML = '<div class="hint" style="padding:8px 10px">Пока пусто. Добавьте первую ссылку.</div>';
    return;
  }
  list.innerHTML = state.projects.map((p) => {
    const when = new Date((p.created_at || 0) * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
    const active = ["queued", "preparing", "running", "processing"].includes(p.status);
    const pct = Math.max(0, Math.min(100, Math.round(p.progress || 0)));
    const sub = p.status === "done" ? `${p.meta?.clips || ""} клипов · ${when}`
      : p.status === "error" ? "ошибка"
      : p.status === "cancelled" ? "отменено"
      : p.status === "draft" ? "черновик · не запущен"
      : active ? `${p.stage || "обработка"}${pct ? ` · ${pct}%` : ""}`
      : when;
    const bar = active ? `<span class="p-bar"><i style="width:${Math.max(2, pct)}%"></i></span>` : "";
    return `<button class="project-item ${state.current === p.id ? "active" : ""}" data-project="${p.id}">
      <span class="status-dot ${esc(p.status)}"></span>
      <span class="p-body">
        <span class="p-title">${esc(p.title || p.url)}</span>
        <span class="p-meta">${esc(sub)}</span>
        ${bar}
      </span>
    </button>`;
  }).join("");
  updateActiveBar();
}

async function loadProjects() {
  try {
    state.projects = await api("/api/projects");
    renderSidebar();
  } catch (e) {
    console.error(e);
  }
}

/* ---------------- Hero ---------------- */

function heroHTML() {
  if (state.homeView === "streams") return streamHomeHTML();
  const o = state.opts;
  const counts = [5, 10, 20, 30, 50, 0];
  const wizard = wizardInterface();
  return `
  <section class="hero ${wizard ? "wz-simple" : ""}">
    <div class="eyebrow">${ICONS.spark} Автонарезка для Shorts · Reels · TikTok</div>
    <h1 class="hero-title">Одно видео —<br><span class="grad">десятки вирусных клипов</span></h1>
    <p class="hero-sub">Вставьте ссылку на YouTube, Twitch, TikTok, Instagram, VK или файл. Приложение найдёт самые цепляющие моменты, обрежет их в вертикаль с умным кадрированием по лицу, наложит субтитры с подсветкой слов и отрендерит готовые ролики.</p>

    <div class="url-box">
      <input id="urlInput" type="text" placeholder="https://youtube.com/watch?v=… или https://twitch.tv/videos/…" autocomplete="off" spellcheck="false" />
      <button class="btn-primary" id="startBtn">${wizard ? "Далее" : "Сделать нарезки"}</button>
    </div>
    <div class="upload-row">
      <span>или</span>
      <button class="link-btn" id="uploadBtn">загрузите видеофайлом</button>
      <span>· mp4, mov, webm · длинные подкасты и интервью</span>
      <span id="pendingFile" class="pending-file hidden"></span>
      <span>·</span>
      <button class="link-btn" id="subsBtn">приложите субтитры</button>
      <span id="pendingSubs" class="pending-file hidden"></span>
    </div>
    <div class="hero-note">Twitch: VOD или клип. Прямой эфир — на вкладке «Прямой эфир» слева.</div>
    ${wizard ? `<div class="wz-start">
      <label class="mini-field"><span>Доступ к источнику</span>
        <select id="startCookies">
          <option value="">Без cookies</option>
          <option value="chrome">Cookies из Chrome</option>
          <option value="safari">Cookies из Safari</option>
          <option value="firefox">Cookies из Firefox</option>
          <option value="edge">Cookies из Edge</option>
        </select>
      </label>
      <div class="wz-start-note">Дальше по шагам: кадр → субтитры → количество. Длительность, стиль и всё остальное тоже можно поменять.</div>
    </div>` : ""}

    <div class="group-title"><span>Параметры нарезки</span><span class="group-hint">всё можно поменять позже</span></div>
    <div class="options-layout">
    <div class="options">
      <div class="opt">
        ${optIcon("count", "ico-cyan")}
        <div>
          <span class="opt-label">Что делать</span>
          <span class="opt-hint">Умные моменты — ищет лучшие куски по речи. Просто порезать — равные части без анализа, быстрее.</span>
        </div>
        <div class="seg" data-group="select">
          <button data-val="smart" class="${o.select === "smart" ? "active" : ""}">Умные моменты</button>
          <button data-val="even" class="${o.select === "even" ? "active" : ""}">Просто порезать</button>
        </div>
      </div>
      <div class="opt">
        ${optIcon("count", "ico-purple")}
        <div>
          <span class="opt-label">Кто выбирает моменты</span>
          <span class="opt-hint">Локально — эвристики по речи, офлайн и бесплатно. Нейросеть читает весь текст выпуска и ищет моменты по смыслу. Ключи — в «Настройки → Нейросеть».</span>
        </div>
        <div class="opt-control">
          <select id="aiPicker">
            <option value="local" ${o.picker === "local" ? "selected" : ""}>Локально</option>
            <option value="auto" ${o.picker === "auto" ? "selected" : ""}>Авто: DeepSeek → Gemini</option>
            <option value="deepseek" ${o.picker === "deepseek" ? "selected" : ""}>DeepSeek</option>
            <option value="gemini" ${o.picker === "gemini" ? "selected" : ""}>Gemini</option>
          </select>
          <select id="aiMoods">
            <option value="any" ${o.moods === "any" ? "selected" : ""}>Любые настроения</option>
            <option value="funny" ${o.moods === "funny" ? "selected" : ""}>Только весёлое</option>
            <option value="sad" ${o.moods === "sad" ? "selected" : ""}>Только грустное</option>
            <option value="drama" ${o.moods === "drama" ? "selected" : ""}>Только драма</option>
            <option value="shock" ${o.moods === "shock" ? "selected" : ""}>Только шок</option>
            <option value="insight" ${o.moods === "insight" ? "selected" : ""}>Только мысль</option>
          </select>
          <select id="aiMinScore">
            <option value="0" ${Number(o.minScore) === 0 ? "selected" : ""}>Оценка любая</option>
            <option value="0.5" ${Number(o.minScore) === 0.5 ? "selected" : ""}>Оценка ≥ 50</option>
            <option value="0.6" ${Number(o.minScore) === 0.6 ? "selected" : ""}>Оценка ≥ 60</option>
            <option value="0.7" ${Number(o.minScore) === 0.7 ? "selected" : ""}>Оценка ≥ 70</option>
            <option value="0.8" ${Number(o.minScore) === 0.8 ? "selected" : ""}>Оценка ≥ 80</option>
          </select>
        </div>
      </div>
      <div class="opt">
        ${optIcon("count", "ico-purple")}
        <div>
          <span class="opt-label">Сколько нарезок</span>
          <span class="opt-hint">Любое число вручную, хоть 1 — чтобы посмотреть формат. «Все» — без ограничения.</span>
        </div>
        <div class="count-pick">
          <div class="seg" data-group="count">
            ${counts.map((c) => `<button data-val="${c}" class="${o.count === c ? "active" : ""}">${c === 0 ? "Все" : c}</button>`).join("")}
          </div>
          <label class="count-manual" title="Своё количество нарезок: от 1 до 200">
            <input type="number" id="countInput" min="1" max="200" step="1" value="${o.count > 0 ? o.count : ""}" placeholder="своё" />
            <span>шт.</span>
          </label>
        </div>
      </div>
      <div class="opt">
        ${optIcon("duration", "ico-blue")}
        <div>
          <span class="opt-label">Длительность клипа</span>
          <span class="opt-hint">Сколько секунд в одном ролике. Для «просто порезать» это длина равного куска.</span>
        </div>
        <div class="seg" data-group="dur">
          ${Object.entries(DUR_PRESETS).map(([k, v]) => `<button data-val="${k}" class="${o.dur === k ? "active" : ""}">${v.label}</button>`).join("")}
        </div>
      </div>
      <div class="opt">
        ${optIcon("aspect", "ico-cyan")}
        <div>
          <span class="opt-label">Формат</span>
          <span class="opt-hint">Вертикально — Shorts, Reels, TikTok. Квадрат — лента. Горизонтально — обычное видео.</span>
        </div>
        <div class="seg" data-group="aspect">
          ${Object.entries(ASPECT_META).map(([a, m]) => `<button data-val="${a}" class="${o.aspect === a ? "active" : ""}" title="${m.hint}">${aspectIcon(a)}${m.short}</button>`).join("")}
        </div>
      </div>
      <div class="opt">
        ${optIcon("aspect", "ico-cyan")}
        <span class="opt-label">Площадка</span>
        <div class="seg" data-group="platform">
          ${PLATFORM_OPTIONS.map(([k, v]) => `<button data-val="${k}" class="${o.platform === k ? "active" : ""}">${v}</button>`).join("")}
        </div>
      </div>
      <div class="opt">
        ${optIcon("frame", "ico-green")}
        <div>
          <span class="opt-label">Кадр</span>
          <span class="opt-hint">Умный кроп — следит за лицом и держит его в кадре. Размытый фон — весь кадр, поля размыты. По центру — просто центр.</span>
        </div>
        <div class="seg" data-group="mode">
          <button data-val="auto" class="${o.mode === "auto" ? "active" : ""}">Умный кроп</button>
          <button data-val="blur" class="${o.mode === "blur" ? "active" : ""}">Размытый фон</button>
          <button data-val="crop" class="${o.mode === "crop" ? "active" : ""}">По центру</button>
        </div>
      </div>
      <div class="opt">
        ${optIcon("frame", "ico-purple")}
        <div>
          <span class="opt-label">Пресет стрима</span>
          <span class="opt-hint">Для видео с маленькой врезкой лица (стримы, реакции). «Сплит-скрин» делит кадр: сверху видео, снизу фоновый ролик.</span>
        </div>
        <div class="seg" data-group="layout">
          <button data-val="" class="${!o.layout ? "active" : ""}">Выкл</button>
          <button data-val="band" class="${o.layout === "band" ? "active" : ""}">Лицо снизу</button>
          <button data-val="band_top" class="${o.layout === "band_top" ? "active" : ""}">Лицо сверху</button>
          <button data-val="adhd" class="${o.layout === "adhd" ? "active" : ""}">Сплит-скрин</button>
        </div>
      </div>
      <div class="opt wide adhd-block ${o.layout === "adhd" ? "" : "hidden"}" id="adhdBlock">
        <span class="opt-head">${optIcon("frame", "ico-cyan")}<span class="opt-label">СДВГ-композиция</span></span>
        <div class="substyle">
          <label class="mini-field grow"><span>Основное видео <b id="splitVal">${Math.round(o.splitRatio * 100)}</b>%</span>
            <input type="range" id="splitRange" min="${Math.min(adhdLimits().min, Math.round(o.splitRatio * 100))}" max="${adhdLimits().max}" step="1" value="${Math.round(o.splitRatio * 100)}" />
          </label>
          <label class="mini-field"><span>Верх: заполнение</span>
            <select id="adhdTopFill">
              <option value="cover" ${o.adhdTopFill !== "contain" ? "selected" : ""}>Заполнить</option>
              <option value="contain" ${o.adhdTopFill === "contain" ? "selected" : ""}>Вписать целиком</option>
            </select>
          </label>
          <label class="mini-field"><span>Низ: заполнение</span>
            <select id="adhdBottomFill">
              <option value="cover" ${o.adhdBottomFill !== "contain" ? "selected" : ""}>Заполнить</option>
              <option value="contain" ${o.adhdBottomFill === "contain" ? "selected" : ""}>Вписать целиком</option>
            </select>
          </label>
          <label class="mini-field"><span>Верх: масштаб <b id="adhdTopScaleVal">${Math.round(o.adhdTopScale * 100)}</b>%</span>
            <input type="range" id="adhdTopScale" min="50" max="200" step="5" value="${Math.round(o.adhdTopScale * 100)}" />
          </label>
          <label class="mini-field"><span>Низ: масштаб <b id="adhdBottomScaleVal">${Math.round(o.adhdBottomScale * 100)}</b>%</span>
            <input type="range" id="adhdBottomScale" min="50" max="200" step="5" value="${Math.round(o.adhdBottomScale * 100)}" />
          </label>
          <label class="mini-field"><span>Верх: смещение X <b id="adhdTopXVal">${Math.round(o.adhdTopX * 100)}</b>%</span>
            <input type="range" id="adhdTopX" min="-50" max="50" step="1" value="${Math.round(o.adhdTopX * 100)}" />
          </label>
          <label class="mini-field"><span>Верх: смещение Y <b id="adhdTopYVal">${Math.round(o.adhdTopY * 100)}</b>%</span>
            <input type="range" id="adhdTopY" min="-50" max="50" step="1" value="${Math.round(o.adhdTopY * 100)}" />
          </label>
          <label class="mini-field"><span>Низ: смещение X <b id="adhdBottomXVal">${Math.round(o.adhdBottomX * 100)}</b>%</span>
            <input type="range" id="adhdBottomX" min="-50" max="50" step="1" value="${Math.round(o.adhdBottomX * 100)}" />
          </label>
          <label class="mini-field"><span>Низ: смещение Y <b id="adhdBottomYVal">${Math.round(o.adhdBottomY * 100)}</b>%</span>
            <input type="range" id="adhdBottomY" min="-50" max="50" step="1" value="${Math.round(o.adhdBottomY * 100)}" />
          </label>
          <label class="mini-field"><span>Низ: скорость <b id="adhdBottomSpeedVal">${Number(o.adhdBottomSpeed).toFixed(2)}</b>×</span>
            <input type="range" id="adhdBottomSpeed" min="25" max="400" step="5" value="${Math.round(o.adhdBottomSpeed * 100)}" />
          </label>
          <label class="mini-field"><span>Низ: звук <b id="adhdBottomVolumeVal">${Math.round(o.adhdBottomVolume)}</b>%</span>
            <input type="range" id="adhdBottomVolume" min="0" max="50" step="1" value="${Math.round(o.adhdBottomVolume)}" />
          </label>
          <label class="mini-field"><span>Низ: старт, с <span class="muted">−1 = случайно</span></span>
            <input type="number" id="adhdBottomStart" min="-1" max="7200" step="0.1" value="${Number(o.adhdBottomStart)}" />
          </label>
          <label class="mini-field"><span>Низ: ролик</span>
            <select id="bgSelect"><option value="random">Случайный</option></select>
          </label>
          <button type="button" class="link-btn" id="bgUploadBtn">добавить фон</button>
        </div>
        <span class="opt-hint">Верх — основное видео, низ — зацикленный фон. Ползунок делит кадр 9:16 (рекомендуется 40–85% под основное). Смещения и масштаб двигают картинку внутри своей области; звук нижнего ролика по умолчанию выключен.</span>
      </div>
      <div class="opt">
        ${optIcon("subs", "ico-yellow")}
        <span class="opt-label">Субтитры</span>
        <div class="opt-control">
          <label class="toggle"><input type="checkbox" id="subsToggle" ${o.subtitles ? "checked" : ""}/><span class="track"></span><span>Включены</span></label>
          <label class="toggle" title="Ролик без вшитых субтитров, но с файлами ASS и SRT"><input type="checkbox" id="exportSubsToggle" ${o.exportSubs ? "checked" : ""}/><span class="track"></span><span>Файлы отдельно</span></label>
          <div class="swatches" id="accents">
            ${swatchesHTML(o.accent)}
          </div>
        </div>
      </div>
      <div class="opt wide">
        <span class="opt-head">${optIcon("style", "ico-pink")}<span class="opt-label">Стиль субтитров</span></span>
        <div class="substyle">
          <label class="mini-field">
            <span>Шрифт</span>
            <div class="font-pick">
              <select id="fontSelect">
                ${fontOptionsHTML(o.subFont)}
              </select>
              <button type="button" class="font-add" id="uploadFontBtn" title="Загрузить свой шрифт">＋</button>
            </div>
          </label>
          <label class="mini-field grow">
            <span>Размер <b id="sizeVal">${o.subSize}</b></span>
            <input type="range" id="sizeRange" min="70" max="180" step="2" value="${o.subSize}" />
          </label>
          <label class="mini-field">
            <span>Положение</span>
            <select id="posSelect">
              ${SUB_POSITIONS.map(([k, label]) => `<option value="${k}" ${o.subPos === k ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          <label class="mini-field grow">
            <span>Сдвиг <b id="offsetVal">${o.subOffset}</b></span>
            <input type="range" id="offsetRange" min="${SUB_OFFSET_MIN}" max="${SUB_OFFSET_MAX}" step="10" value="${o.subOffset}" />
          </label>
          <label class="mini-field">
            <span>Кадры в секунду</span>
            <select id="fpsSelect">
              <option value="source" ${o.keepFps ? "selected" : ""}>Как в исходнике</option>
              <option value="30" ${!o.keepFps ? "selected" : ""}>Всегда 30</option>
            </select>
          </label>
          <label class="mini-field grow">
            <span>Межстрочный интервал <b id="lineGapVal">${o.lineGap}</b></span>
            <input type="range" id="lineGapRange" min="0" max="80" step="2" value="${o.lineGap}" />
          </label>
          <label class="mini-field">
            <span>Темп</span>
            <div class="seg" data-group="subSpeed">
              ${SUB_SPEEDS.map(([k, label]) => `<button data-val="${k}" class="${o.subSpeed === k ? "active" : ""}">${label}</button>`).join("")}
            </div>
          </label>
          <div class="font-sample" id="fontSample" style="font-family:${FONT_CSS[o.subFont] || "VCMontserrat"}">ПРИМЕР СУБТИТРОВ</div>
        </div>
      </div>
      <div class="opt wide">
        <span class="opt-head">${optIcon("style", "ico-pink")}<span class="opt-label">Стиль и звук</span></span>
        <div class="substyle">
          <label class="mini-field">
            <span>Цвет</span>
            <select id="lookSelect">
              <option value="none">Без обработки</option>
              <option value="warm">Тёплый</option>
              <option value="cool">Холодный</option>
              <option value="contrast">Контрастный</option>
              <option value="cinematic">Кинематографичный</option>
              <option value="soft">Мягкий</option>
            </select>
          </label>
          <label class="mini-field grow">
            <span>Зум <b id="zoomVal">100</b>%</span>
            <input type="range" id="zoomRange" min="100" max="115" step="1" value="100" />
          </label>
          <label class="mini-field">
            <span>Битрейт</span>
            <select id="bitrateSelect">
              <option value="0">Авто</option>
              <option value="8">8 Мбит/с</option>
              <option value="12">12 Мбит/с</option>
              <option value="16">16 Мбит/с</option>
            </select>
          </label>
          <label class="toggle"><input type="checkbox" id="vignetteToggle" /><span class="track"></span><span>Виньетка</span></label>
          <label class="toggle"><input type="checkbox" id="grainToggle" /><span class="track"></span><span>Зерно</span></label>
          <label class="mini-field grow">
            <span>Музыка <b id="musicVal">8</b>%</span>
            <input type="range" id="musicRange" min="0" max="30" step="1" value="8" />
          </label>
          <button type="button" class="link-btn" id="musicBtn">приложить музыку</button>
          <span id="pendingMusic" class="pending-file hidden"></span>
        </div>
      </div>
      <div class="opt wide">
        <span class="opt-head">${optIcon("style", "ico-pink")}<span class="opt-label">Уникализация</span></span>
        <div class="substyle">
          <div class="preset-row" id="uniqPresets" style="flex-basis:100%">
            ${UNIQ_PRESETS.map((p) => `<button type="button" class="preset-chip" data-uniq="${p.key}">${p.label}</button>`).join("")}
          </div>
          <label class="toggle"><input type="checkbox" id="hflipToggle" /><span class="track"></span><span>Зеркало</span></label>
          <label class="toggle"><input type="checkbox" id="jumpCutsToggle" /><span class="track"></span><span>Склейки пауз</span></label>
          <label class="toggle"><input type="checkbox" id="cutZoomToggle" /><span class="track"></span><span>Зум на склейках</span></label>
          <label class="mini-field"><span>Наклон <b id="tiltVal">0</b>°</span>
            <input type="range" id="tiltRange" min="0" max="3" step="0.5" value="0" />
          </label>
          <label class="mini-field"><span>Скорость <b id="speedVal">1.00</b>×</span>
            <input type="range" id="speedRange" min="1" max="1.1" step="0.01" value="1" />
          </label>
          <label class="mini-field"><span>Питч <b id="pitchVal">1.00</b>×</span>
            <input type="range" id="pitchRange" min="0.95" max="1.05" step="0.01" value="1" />
          </label>
          <span class="opt-hint">Склейки вырезают паузы длиннее 0.5 с и пересчитывают субтитры. Скорость и питч меняют темп; наклон 0–3° без чёрных углов. Всё по умолчанию выключено.</span>
        </div>
      </div>
      <div class="opt">
        ${optIcon("access", "ico-gray")}
        <span class="opt-label">Доступ к источнику</span>
        <select id="cookiesSelect">
          <option value="">Без cookies</option>
          <option value="chrome">Cookies из Chrome</option>
          <option value="safari">Cookies из Safari</option>
          <option value="firefox">Cookies из Firefox</option>
          <option value="edge">Cookies из Edge</option>
        </select>
      </div>
    </div>
    <aside class="examples" id="examples">${examplesHTML(o)}</aside>
    </div>
  </section>`;
}

function updateAdhdVisibility() {
  const block = $("#adhdBlock");
  if (block) block.classList.toggle("hidden", state.opts.layout !== "adhd");
}

async function loadAdhdBgs() {
  const select = $("#bgSelect");
  if (!select) return;
  try {
    const data = await api("/api/adhd-bg");
    const files = data.files || [];
    const current = state.opts.adhdBg || state.opts.bgVideo || "random";
    select.innerHTML = '<option value="random">Случайный</option>' +
      files.map((f) => `<option value="${esc(f.name)}">${esc(f.name)}</option>`).join("");
    select.value = files.some((f) => f.name === current) ? current : "random";
    state.opts.adhdBg = select.value === "random" ? "" : select.value;
    state.opts.bgVideo = select.value;
  } catch (_) {}
}

function bindHero() {
  const main = $("#main");
  $$(".seg", main).forEach((seg) => {
    const group = seg.dataset.group;
    seg.addEventListener("click", (ev) => {
      const btn = ev.target.closest("button[data-val]");
      if (!btn) return;
      const raw = btn.dataset.val;
      state.opts[group] = group === "count" ? Number(raw) : raw;
      $$("button", seg).forEach((b) => b.classList.toggle("active", b === btn));
      syncExamples();
      if (group === "layout") updateAdhdVisibility();
    });
  });

  const aiPicker = $("#aiPicker");
  if (aiPicker) aiPicker.addEventListener("change", () => { state.opts.picker = aiPicker.value; });
  const aiMoods = $("#aiMoods");
  if (aiMoods) aiMoods.addEventListener("change", () => { state.opts.moods = aiMoods.value; });
  const aiMinScore = $("#aiMinScore");
  if (aiMinScore) aiMinScore.addEventListener("change", () => { state.opts.minScore = Number(aiMinScore.value); });

  const examples = $("#examples");
  if (examples) examples.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".ex-opt");
    if (!btn) return;
    const group = btn.dataset.group;
    state.opts[group] = btn.dataset.val;
    $$(`.seg[data-group="${group}"] button`, main).forEach((b) =>
      b.classList.toggle("active", b.dataset.val === btn.dataset.val));
    syncExamples();
  });

  const countInput = $("#countInput");
  if (countInput) countInput.addEventListener("input", () => {
    if (countInput.value === "") {
      state.opts.count = 0;
    } else {
      const clamped = pxClamp(Math.round(Number(countInput.value) || 1), 1, 200);
      state.opts.count = clamped;
      if (countInput.value !== String(clamped)) countInput.value = String(clamped);
    }
    $$('.seg[data-group="count"] button', main).forEach((b) =>
      b.classList.toggle("active", Number(b.dataset.val) === state.opts.count));
  });
  syncExamples();
  const accents = $("#accents");
  if (accents) {
    accents.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".swatch");
      if (!btn) return;
      state.opts.accent = btn.dataset.val;
      $$(".swatch", accents).forEach((b) => b.classList.toggle("active", b === btn));
    });
  }
  const subs = $("#subsToggle");
  if (subs) subs.addEventListener("change", () => { state.opts.subtitles = subs.checked; });
  const exportSubs = $("#exportSubsToggle");
  if (exportSubs) exportSubs.addEventListener("change", () => {
    state.opts.exportSubs = exportSubs.checked;
  });

  const cookies = $("#cookiesSelect");
  if (cookies) cookies.addEventListener("change", () => { state.opts.cookies = cookies.value; });
  const startCookies = $("#startCookies");
  if (startCookies) startCookies.addEventListener("change", () => {
    state.opts.cookies = startCookies.value;
  });

  const addFont = $("#uploadFontBtn");
  if (addFont) addFont.addEventListener("click", () => {
    state.fontTarget = "#fontSelect";
    $("#fontInput").click();
  });

  const fontSelect = $("#fontSelect");
  if (fontSelect) fontSelect.addEventListener("change", () => {
    state.opts.subFont = fontSelect.value;
    const sample = $("#fontSample");
    if (sample) sample.style.fontFamily = FONT_CSS[fontSelect.value] || "VCMontserrat";
  });

  const sizeRange = $("#sizeRange");
  if (sizeRange) sizeRange.addEventListener("input", () => {
    state.opts.subSize = Number(sizeRange.value);
    const label = $("#sizeVal");
    if (label) label.textContent = sizeRange.value;
  });

  const posSelect = $("#posSelect");
  if (posSelect) posSelect.addEventListener("change", () => { state.opts.subPos = posSelect.value; });

  const lookSelect = $("#lookSelect");
  if (lookSelect) lookSelect.addEventListener("change", () => { state.opts.look = lookSelect.value; });
  const zoomRange = $("#zoomRange");
  if (zoomRange) zoomRange.addEventListener("input", () => {
    state.opts.zoom = Number(zoomRange.value);
    const label = $("#zoomVal");
    if (label) label.textContent = zoomRange.value;
  });
  const bitrateSelect = $("#bitrateSelect");
  if (bitrateSelect) bitrateSelect.addEventListener("change", () => {
    state.opts.bitrate = Number(bitrateSelect.value);
  });
  const vignetteToggle = $("#vignetteToggle");
  if (vignetteToggle) vignetteToggle.addEventListener("change", () => {
    state.opts.vignette = vignetteToggle.checked;
  });
  const grainToggle = $("#grainToggle");
  if (grainToggle) grainToggle.addEventListener("change", () => {
    state.opts.grain = grainToggle.checked;
  });
  const musicRange = $("#musicRange");
  if (musicRange) musicRange.addEventListener("input", () => {
    state.opts.musicVolume = Number(musicRange.value);
    const label = $("#musicVal");
    if (label) label.textContent = musicRange.value;
  });
  const musicBtn = $("#musicBtn");
  if (musicBtn) musicBtn.addEventListener("click", () => $("#musicInput").click());

  const hflipToggle = $("#hflipToggle");
  if (hflipToggle) hflipToggle.addEventListener("change", () => { state.opts.hflip = hflipToggle.checked; });
  const jumpCutsToggle = $("#jumpCutsToggle");
  if (jumpCutsToggle) jumpCutsToggle.addEventListener("change", () => {
    state.opts.jumpCuts = jumpCutsToggle.checked;
  });
  const cutZoomToggle = $("#cutZoomToggle");
  if (cutZoomToggle) cutZoomToggle.addEventListener("change", () => {
    state.opts.cutZoom = cutZoomToggle.checked;
  });
  const tiltRange = $("#tiltRange");
  if (tiltRange) tiltRange.addEventListener("input", () => {
    state.opts.tilt = Number(tiltRange.value);
    const label = $("#tiltVal");
    if (label) label.textContent = tiltRange.value;
  });
  const speedRange = $("#speedRange");
  if (speedRange) speedRange.addEventListener("input", () => {
    state.opts.speed = Number(speedRange.value);
    const label = $("#speedVal");
    if (label) label.textContent = Number(speedRange.value).toFixed(2);
  });
  const pitchRange = $("#pitchRange");
  if (pitchRange) pitchRange.addEventListener("input", () => {
    state.opts.pitch = Number(pitchRange.value);
    const label = $("#pitchVal");
    if (label) label.textContent = Number(pitchRange.value).toFixed(2);
  });
  const splitRange = $("#splitRange");
  if (splitRange) splitRange.addEventListener("input", () => {
    state.opts.splitRatio = Number(splitRange.value) / 100;
    const label = $("#splitVal");
    if (label) label.textContent = splitRange.value;
  });
  const bindAdhdRange = (id, key, scale, fmt) => {
    const el = $("#" + id);
    if (!el) return;
    const label = $("#" + id + "Val");
    const apply = () => {
      state.opts[key] = Number(el.value) * scale;
      if (label) label.textContent = fmt ? fmt(state.opts[key]) : el.value;
    };
    el.addEventListener("input", apply);
    apply();
  };
  bindAdhdRange("adhdTopScale", "adhdTopScale", 0.01);
  bindAdhdRange("adhdBottomScale", "adhdBottomScale", 0.01);
  bindAdhdRange("adhdTopX", "adhdTopX", 0.01);
  bindAdhdRange("adhdTopY", "adhdTopY", 0.01);
  bindAdhdRange("adhdBottomX", "adhdBottomX", 0.01);
  bindAdhdRange("adhdBottomY", "adhdBottomY", 0.01);
  bindAdhdRange("adhdBottomSpeed", "adhdBottomSpeed", 0.01, (v) => Number(v).toFixed(2));
  bindAdhdRange("adhdBottomVolume", "adhdBottomVolume", 1);
  const adhdTopFill = $("#adhdTopFill");
  if (adhdTopFill) adhdTopFill.addEventListener("change", () => { state.opts.adhdTopFill = adhdTopFill.value; });
  const adhdBottomFill = $("#adhdBottomFill");
  if (adhdBottomFill) adhdBottomFill.addEventListener("change", () => { state.opts.adhdBottomFill = adhdBottomFill.value; });
  const adhdBottomStart = $("#adhdBottomStart");
  if (adhdBottomStart) adhdBottomStart.addEventListener("change", () => {
    state.opts.adhdBottomStart = Number(adhdBottomStart.value);
  });
  const bgSelect = $("#bgSelect");
  if (bgSelect) bgSelect.addEventListener("change", () => {
    state.opts.adhdBg = bgSelect.value === "random" ? "" : bgSelect.value;
    state.opts.bgVideo = bgSelect.value;
  });
  updateAdhdVisibility();
  const bgUploadBtn = $("#bgUploadBtn");
  if (bgUploadBtn) bgUploadBtn.addEventListener("click", () => $("#adhdBgInput").click());
  const uniqPresets = $("#uniqPresets");
  if (uniqPresets) uniqPresets.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-uniq]");
    if (!btn) return;
    applyUniqPreset(btn.dataset.uniq);
  });
  loadAdhdBgs();

  const fpsSelect = $("#fpsSelect");
  if (fpsSelect) fpsSelect.addEventListener("change", () => {
    state.opts.keepFps = fpsSelect.value === "source";
  });

  const lineGapRange = $("#lineGapRange");
  if (lineGapRange) lineGapRange.addEventListener("input", () => {
    state.opts.lineGap = Number(lineGapRange.value);
    const label = $("#lineGapVal");
    if (label) label.textContent = lineGapRange.value;
  });

  const offsetRange = $("#offsetRange");
  if (offsetRange) offsetRange.addEventListener("input", () => {
    state.opts.subOffset = Number(offsetRange.value);
    const label = $("#offsetVal");
    if (label) label.textContent = offsetRange.value;
  });

  const startBtn = $("#startBtn");
  if (startBtn) startBtn.addEventListener("click", submitLink);
  const urlInput = $("#urlInput");
  if (urlInput) urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") submitLink(); });
  if (urlInput) urlInput.addEventListener("input", () => {
    if (!urlInput.value.trim()) return;
    state.pendingFile = null;
    updatePendingChip();
    const btn = $("#startBtn");
    if (btn) btn.textContent = "Сделать нарезки";
  });
  const chip = $("#pendingFile");
  if (chip) chip.addEventListener("click", () => {
    state.pendingFile = null;
    updatePendingChip();
    const btn = $("#startBtn");
    if (btn) btn.textContent = "Сделать нарезки";
  });
  const uploadBtn = $("#uploadBtn");
  if (uploadBtn) uploadBtn.addEventListener("click", () => $("#fileInput").click());
  const subsBtn = $("#subsBtn");
  if (subsBtn) subsBtn.addEventListener("click", () => {
    state.subsToTemplate = false;
    $("#subsInput").click();
  });
  const subsChip = $("#pendingSubs");
  if (subsChip) subsChip.addEventListener("click", () => {
    state.pendingSubs = null;
    subsChip.classList.add("hidden");
  });
}

function applyUniqPreset(key) {
  const preset = UNIQ_PRESETS.find((p) => p.key === key);
  if (!preset) return;
  const o = preset.opts;
  state.opts.hflip = o.hflip;
  state.opts.tilt = o.tilt;
  state.opts.speed = o.speed;
  state.opts.pitch = o.pitch;
  state.opts.jumpCuts = o.jumpCuts;
  state.opts.cutZoom = o.cutZoom;
  const setCheck = (id, val) => { const el = $("#" + id); if (el) el.checked = val; };
  const setRange = (id, val, labelId, digits) => {
    const el = $("#" + id);
    if (el) el.value = val;
    const label = $("#" + labelId);
    if (label) label.textContent = digits ? Number(val).toFixed(digits) : val;
  };
  setCheck("hflipToggle", o.hflip);
  setCheck("jumpCutsToggle", o.jumpCuts);
  setCheck("cutZoomToggle", o.cutZoom);
  setRange("tiltRange", o.tilt, "tiltVal", 0);
  setRange("speedRange", o.speed, "speedVal", 2);
  setRange("pitchRange", o.pitch, "pitchVal", 2);
  $$("#uniqPresets button").forEach((b) => b.classList.toggle("active", b.dataset.uniq === key));
  toast(`Пресет уникализации: ${preset.label}`);
}

function heroOptions() {
  const d = DUR_PRESETS[state.opts.dur] || DUR_PRESETS["20-45"];
  return {
    count: state.opts.count,
    min_dur: d.min,
    max_dur: d.max,
    target_dur: d.target,
    aspect: state.opts.aspect,
    mode: state.opts.mode,
    select: state.opts.select,
    picker: state.opts.picker,
    mood_filter: state.opts.moods && state.opts.moods !== "any" ? [state.opts.moods] : [],
    min_score: Number(state.opts.minScore || 0),
    subtitles: state.opts.subtitles,
    accent: state.opts.accent,
    sub_font: state.opts.subFont,
    sub_size: state.opts.subSize,
    sub_position: state.opts.subPos,
    sub_offset: state.opts.subOffset,
    sub_speed: state.opts.subSpeed,
    line_gap: state.opts.lineGap,
    keep_fps: state.opts.keepFps,
    export_subs: state.opts.exportSubs,
    look: state.opts.look,
    vignette: state.opts.vignette,
    grain: state.opts.grain,
    zoom: state.opts.zoom,
    bitrate: state.opts.bitrate,
    music_volume: state.opts.musicVolume,
    hflip: state.opts.hflip,
    tilt: state.opts.tilt,
    speed: state.opts.speed,
    pitch: state.opts.pitch,
    jump_cuts: state.opts.jumpCuts,
    cut_zoom: state.opts.cutZoom,
    bg_video: state.opts.bgVideo,
    split_ratio: state.opts.splitRatio,
    adhd_bg: state.opts.adhdBg || "",
    adhd_top_fill: state.opts.adhdTopFill,
    adhd_bottom_fill: state.opts.adhdBottomFill,
    adhd_top_scale: state.opts.adhdTopScale,
    adhd_top_offset_x: state.opts.adhdTopX,
    adhd_top_offset_y: state.opts.adhdTopY,
    adhd_bottom_scale: state.opts.adhdBottomScale,
    adhd_bottom_offset_x: state.opts.adhdBottomX,
    adhd_bottom_offset_y: state.opts.adhdBottomY,
    adhd_bottom_speed: state.opts.adhdBottomSpeed,
    adhd_bottom_start: state.opts.adhdBottomStart,
    adhd_bottom_volume: state.opts.adhdBottomVolume,
    platform: state.opts.platform,
    layout: state.opts.layout,
    cookies_browser: state.opts.cookies,
    language: "auto",
    audio_track: -1,
    export_order: "chrono"
  };
}

async function submitLink() {
  if (state.pendingFile) { startLocalFile(); return; }
  const input = $("#urlInput");
  const url = (input.value || "").trim();
  if (!url) { input.focus(); toast("Вставьте ссылку на видео", "err"); return; }
  askQuality(url);
}

function formatSize(mb) {
  if (!mb) return "размер неизвестен";
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} ГБ` : `${mb} МБ`;
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} ГБ`;
  return `${Math.max(1, Math.round(value / 1024 ** 2))} МБ`;
}

function closeProbe() {
  state.probeOpen = false;
  state.probeUrl = "";
  state.probeData = null;
  $("#modal").classList.add("hidden");
  $("#modal").innerHTML = "";
  const btn = $("#startBtn");
  if (btn) { btn.disabled = false; btn.textContent = "Сделать нарезки"; }
}

function askQuality(url) {
  state.probeOpen = true;
  state.probeUrl = url;
  state.probeData = null;
  $("#modal").innerHTML = `
    <div class="modal-backdrop" data-close="probe"></div>
    <div class="modal-panel quality-panel">
      <div class="modal-head">
        <h3>Проверка видео</h3>
        <button class="icon-btn" data-close="probe">${ICONS.close}</button>
      </div>
      <div id="qualityBody" class="quality-body">
        <span class="spinner"></span>
        <div>Смотрю длительность и доступные качества…</div>
      </div>
    </div>`;
  $("#modal").classList.remove("hidden");

  api("/api/probe", {
    method: "POST",
    body: JSON.stringify({ url, cookies_browser: state.opts.cookies })
  }).then((data) => {
    if (!state.probeOpen) return;
    state.probeData = data;
    renderQuality(data);
  }).catch((err) => {
    const body = $("#qualityBody");
    if (!body) return;
    body.innerHTML = `<div class="tmpl-error">${esc(err.message)}</div>
      <button class="btn-ghost" id="qualitySkip">Продолжить без рекомендации (1080p)</button>`;
    $("#qualitySkip").addEventListener("click", () => createFromProbe(1080));
  });
}

function renderQuality(data) {
  const body = $("#qualityBody");
  if (!body) return;
  const rec = data.recommended;
  const cards = data.options.map((o) => `
    <button class="quality-card ${o.height === rec ? "recommended" : ""}" data-quality="${o.height}">
      <span class="q-height">${o.height >= 2160 ? "4K" : o.height >= 1440 ? "2K" : o.height + "p"}</span>
      <span class="q-size">${formatSize(o.size_mb)}</span>
      ${o.height === rec ? '<span class="q-badge">рекомендуем</span>' : ""}
    </button>`).join("");
  body.innerHTML = `
    <div class="quality-title">${esc(data.title)}</div>
    <div class="quality-meta">${fmtDur(data.duration)} · ${esc(data.uploader || "")}</div>
    <div class="quality-cards">${cards}</div>
    <label class="toggle eco-row"><input type="checkbox" id="qualityEco"/><span class="track"></span><span>Экономно: сначала анализ, потом только выбранные моменты</span></label>
    <div class="quality-note" id="qualityNote"></div>
    <div class="modal-foot" style="padding:16px 0 0;border:0">
      <button class="btn-ghost" data-close="probe">Отмена</button>
      <button class="btn-primary" id="qualityStart">Скачать и настроить</button>
    </div>`;
  let chosen = rec;
  state.segmentsChoice = false;
  const note = $("#qualityNote");
  const updateNote = () => {
    const opt = data.options.find((o) => o.height === chosen);
    if (!opt) return;
    const eco = $("#qualityEco")?.checked;
    state.segmentsChoice = !!eco;
    if (eco) {
      const audioMb = data.audio_size_mb || Math.max(1, Math.round(data.duration * 0.012));
      note.textContent = `Сначала только аудио (~${formatSize(audioMb)}), анализ, затем видео скачается лишь для выбранных моментов — обычно в 5–20 раз меньше полного файла.`;
      return;
    }
    let text = `Будет скачано ${formatSize(opt.size_mb)}`;
    if (chosen === 360 && data.duration > 5400) text += " · для длинного видео это в разы быстрее, чем 1080p";
    if (chosen === 1080 && data.duration > 5400) text += " · на медленной связи займёт очень долго";
    note.textContent = text;
  };
  $("#qualityEco")?.addEventListener("change", updateNote);
  body.querySelectorAll(".quality-card").forEach((card) => card.addEventListener("click", () => {
    chosen = Number(card.dataset.quality);
    body.querySelectorAll(".quality-card").forEach((c) => c.classList.toggle("active", c === card));
    updateNote();
  }));
  body.querySelector(`.quality-card[data-quality="${chosen}"]`)?.classList.add("active");
  updateNote();
  $("#qualityStart").addEventListener("click", () => createFromProbe(chosen));
}

async function createFromProbe(height) {
  const url = state.probeUrl;
  if (!url) return;
  const btn = $("#qualityStart") || $("#qualitySkip");
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Запуск'; }
  try {
    const options = { ...heroOptions(), max_height: height, segments: state.segmentsChoice };
    const project = await api("/api/projects/draft", {
      method: "POST",
      body: JSON.stringify({ url, title: "", options })
    });
    state.probeOpen = false;
    $("#modal").classList.add("hidden");
    $("#modal").innerHTML = "";
    await loadProjects();
    openProject(project.id);
    openTemplate(project.id);
  } catch (err) {
    toast(err.message, "err");
    if (btn) { btn.disabled = false; btn.textContent = "Скачать и настроить"; }
  }
}

function updatePendingChip() {
  const chip = $("#pendingFile");
  if (!chip) return;
  if (!state.pendingFile) {
    chip.classList.add("hidden");
    chip.textContent = "";
    return;
  }
  const mb = state.pendingFile.size / (1024 * 1024);
  chip.textContent = `${state.pendingFile.name} · ${formatSize(Math.round(mb))} · убрать`;
  chip.classList.remove("hidden");
}

function uploadFile(file) {
  if (!file) return;
  const limit = Number(state.health && state.health.max_upload_bytes) || 0;
  if (limit > 0 && file.size > limit) {
    toast(`Файл больше ${formatBytes(limit)}`, "err");
    return;
  }
  state.pendingFile = file;
  const input = $("#urlInput");
  if (input) input.value = "";
  updatePendingChip();
  const hint = $("#startBtn");
  if (hint) hint.textContent = "Запустить нарезку";
  toast("Файл выбран — настройте параметры и нажмите «Запустить нарезку»");
}

async function startLocalFile() {
  const file = state.pendingFile;
  if (!file) return;
  const btn = $("#startBtn");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Загружаю'; }
  try {
    const project = await api("/api/projects/draft", {
      method: "POST",
      body: JSON.stringify({ title: file.name, options: heroOptions() })
    });
    if (state.pendingMusic) {
      const musicForm = new FormData();
      musicForm.append("file", state.pendingMusic);
      try {
        await api(`/api/projects/${project.id}/music`, { method: "POST", body: musicForm });
      } catch (err) {
        toast("Музыка не принята: " + err.message, "err");
      }
      state.pendingMusic = null;
      const mchip = $("#pendingMusic");
      if (mchip) mchip.classList.add("hidden");
    }
    if (state.pendingSubs) {
      const subsForm = new FormData();
      subsForm.append("file", state.pendingSubs);
      try {
        await api(`/api/projects/${project.id}/subtitles`, { method: "POST", body: subsForm });
      } catch (err) {
        toast("Субтитры не приняты: " + err.message, "err");
      }
      state.pendingSubs = null;
      const chip = $("#pendingSubs");
      if (chip) chip.classList.add("hidden");
    }
    const form = new FormData();
    form.append("file", file);
    await api(`/api/projects/${project.id}/upload`, { method: "POST", body: form });
    state.pendingFile = null;
    updatePendingChip();
    await loadProjects();
    openProject(project.id);
    openTemplate(project.id);
    toast("Файл загружен — выберите дорожку и запустите нарезку");
  } catch (e) {
    toast(e.message || "Ошибка загрузки", "err");
    if (btn) { btn.disabled = false; btn.textContent = label || "Запустить нарезку"; }
  }
}

/* ---------------- Project view ---------------- */

function openProject(id) {
  if (state.current !== id) {
    state.current = id;
    state.detail = null;
    state.mainKey = "";
    state.clipView = { mood: "any", type: "any", sort: "chrono" };
    history.replaceState(null, "", "#" + id);
  }
  renderSidebar();
  loadDetail(true);
  schedulePoll(80);
}

function schedulePoll(delay) {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(poll, delay);
}

function isBusy(detail) {
  if (!detail) return false;
  const st = detail.project.status;
  return ["queued", "running", "preparing", "processing"].includes(st)
    || detail.clips.some((c) => c.status === "rendering");
}

async function loadDetail(force) {
  if (!state.current) return;
  try {
    const detail = await api(`/api/projects/${state.current}`);
    state.detail = detail;
    const item = state.projects.find((p) => p.id === detail.project.id);
    if (item) {
      item.status = detail.project.status;
      item.title = detail.project.title;
      item.stage = detail.project.stage;
      item.progress = detail.project.progress;
      item.meta = detail.project.meta;
    } else {
      state.projects.unshift({
        id: detail.project.id, title: detail.project.title, status: detail.project.status,
        stage: detail.project.stage, created_at: detail.project.created_at,
        meta: detail.project.meta
      });
    }
    renderSidebar();
    renderMain(force);
    return detail;
  } catch (e) {
    if (String(e.message).includes("не найден")) {
      state.current = null;
      history.replaceState(null, "", location.pathname);
      renderMain(true);
    }
  }
}

async function poll() {
  if (!state.current) return;
  const detail = await loadDetail(false);
  if (isBusy(detail)) schedulePoll(1300);
  else if (detail) {
    loadProjects();
  }
}

function stepsHTML(project) {
  const p = project.progress || 0;
  const steps = [
    { t: "Загрузка", at: 14 },
    { t: "Распознавание речи", at: 58 },
    { t: "Поиск моментов", at: 62 },
    { t: "Рендер клипов", at: 100 }
  ];
  return steps.map((s, i) => {
    const done = p >= s.at;
    const active = !done && (i === 0 || p >= steps[i - 1].at);
    return `<div class="step ${done ? "done" : active ? "active" : ""}">
      <span class="n">${done ? "✓" : i + 1}</span>${s.t}</div>`;
  }).join("");
}

function runningHTML(project) {
  return `
  <div class="project-head">
    <div>
      <h2>${esc(project.title || project.url)}</h2>
      <div class="project-meta">
        <span>${esc(project.url.startsWith("local:") ? "загруженный файл" : project.url)}</span>
        ${project.duration ? `<span>${fmtDur(project.duration)} исходник</span>` : ""}
      </div>
    </div>
    <div class="project-actions">
      <button class="btn-ghost danger" data-action="cancel">Отменить</button>
    </div>
  </div>
  <div class="progress-card">
    <div class="progress-top">
      <div class="progress-stage" id="stageText">${esc(project.stage || "Готовим…")}</div>
      <div class="progress-pct" id="pctText">${Math.round(project.progress || 0)}%</div>
    </div>
    <div class="bar"><i id="barFill" style="width:${Math.max(2, project.progress || 0)}%"></i></div>
    <div class="steps" id="stepsRow">${stepsHTML(project)}</div>
  </div>
  <div class="section-title"><h3>Клипы</h3></div>
  <div id="clipsArea">${clipsGridHTML()}</div>`;
}

function updateLiveMeta(project) {
  const stage = $("#liveStage");
  if (!stage) return;
  const m = project.meta || {};
  stage.textContent = project.stage || "Запись";
  const dur = $("#liveDur");
  if (dur) dur.textContent = `${Math.round((m.live_duration || 0) / 60)} мин записи`;
  const bytes = $("#liveBytes");
  if (bytes) bytes.textContent = `${Math.round((m.live_bytes || 0) / 1048576)} МБ`;
  const clips = $("#liveClips");
  if (clips) clips.textContent = `клипов: ${m.live_clips || 0}`;
  const notice = $("#liveNotice");
  if (notice) {
    const html = liveNoticeHTML(project);
    if (notice.innerHTML !== html) notice.innerHTML = html;
  }
}

function updateProgress(project) {
  updateLiveMeta(project);
  const stage = $("#stageText");
  if (!stage) return;
  stage.textContent = project.stage || "Обработка…";
  $("#pctText").textContent = Math.round(project.progress || 0) + "%";
  $("#barFill").style.width = Math.max(2, project.progress || 0) + "%";
  const row = $("#stepsRow");
  if (row) {
    const html = stepsHTML(project);
    if (row.dataset.sig !== html) { row.innerHTML = html; row.dataset.sig = html; }
  }
  const clipsArea = $("#clipsArea");
  if (clipsArea) {
    const html = clipsGridHTML();
    if (clipsArea.dataset.sig !== String(state.detail.clips.length)) {
      clipsArea.dataset.sig = String(state.detail.clips.length);
      clipsArea.innerHTML = html;
      bindClips();
    }
  }
}

function cancelledHTML(project) {
  return `
  <div class="project-head">
    <div>
      <h2>${esc(project.title || project.url)}</h2>
      <div class="project-meta"><span>Загрузка отменена</span></div>
    </div>
    <div class="project-actions">
      <button class="btn-primary" data-action="retry-cancelled">Скачать заново</button>
      <button class="btn-ghost" data-action="home">${ICONS.back} Новый</button>
      <button class="btn-ghost danger" data-action="delete">${ICONS.trash} Удалить</button>
    </div>
  </div>
  <div class="error-box">Загрузка остановлена. Можно попробовать снова и выбрать качество поменьше — для длинного видео это в разы быстрее.</div>`;
}

function errorHTML(project) {
  return `
  <div class="project-head">
    <div>
      <h2>${esc(project.title || project.url)}</h2>
      <div class="project-meta"><span>${esc(project.url)}</span></div>
    </div>
    <div class="project-actions">
      <button class="btn-primary" data-action="retry">Повторить обработку</button>
      <button class="btn-ghost" data-action="home">${ICONS.back} К новому проекту</button>
      <button class="btn-ghost danger" data-action="delete">${ICONS.trash} Удалить</button>
    </div>
  </div>
  <div class="error-box"><strong>Не получилось обработать видео.</strong><br>${esc(project.error || "Неизвестная ошибка")}</div>`;
}

const MOOD_LABELS = {
  funny: "весёлое", sad: "грустное", drama: "драма", shock: "шок",
  insight: "мысль", wholesome: "тёплое", intense: "жёсткое"
};

const TYPE_LABELS = {
  story: "история", humor: "юмор", conflict: "конфликт", insight: "инсайт",
  education: "обучение", reaction: "реакция", motivation: "мотивация",
  provocation: "провокация", emotion: "эмоция", fact: "факт"
};

function filteredClips() {
  const view = state.clipView || {};
  let clips = ((state.detail && state.detail.clips) || []).slice();
  if (view.mood && view.mood !== "any") {
    clips = clips.filter((c) => (c.settings?.mood || "") === view.mood);
  }
  if (view.type && view.type !== "any") {
    clips = clips.filter((c) => (c.settings?.content_types || []).includes(view.type));
  }
  if (view.sort === "score") clips.sort((a, b) => (b.score || 0) - (a.score || 0));
  return clips;
}

function clipFilterHTML() {
  const all = (state.detail && state.detail.clips) || [];
  if (!all.length) return "";
  const view = state.clipView || {};
  return `<div class="clip-filters">
    <label class="mini-field"><span>Настроение</span>
      <select id="clipMoodFilter"><option value="any">Любое</option>${Object.entries(MOOD_LABELS)
        .map(([k, v]) => `<option value="${k}" ${view.mood === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    </label>
    <label class="mini-field"><span>Тип</span>
      <select id="clipTypeFilter"><option value="any">Любой</option>${Object.entries(TYPE_LABELS)
        .map(([k, v]) => `<option value="${k}" ${view.type === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    </label>
    <label class="mini-field"><span>Сортировка</span>
      <select id="clipSort"><option value="chrono" ${view.sort === "chrono" ? "selected" : ""}>Как нашлось</option>
        <option value="score" ${view.sort === "score" ? "selected" : ""}>По оценке</option></select>
    </label>
  </div>`;
}

function audioPickHTML(project) {
  const pick = (project.meta && project.meta.audio_pick) || null;
  if (!pick || !pick.requested || pick.requested === "auto") return "";
  if (pick.reason === "fallback") {
    return `<div class="warn-box"><strong>Русская дорожка не найдена.</strong> Взята ${esc(pick.label || "другая дорожка")}. Распознавание и звук используют её — проверьте язык в настройках звука.</div>`;
  }
  if (pick.reason === "language") {
    return `<div class="opt-hint">Звук: ${esc(pick.label || "русская дорожка")}.</div>`;
  }
  return "";
}

function asrWarningHTML(project) {
  const warning = (project.meta && project.meta.asr_warning) || "";
  if (!warning) return "";
  return `<div class="warn-box"><strong>Проверьте язык распознавания.</strong> ${esc(warning)}</div>`;
}

function clipsGridHTML() {
  const clips = filteredClips();
  const all = (state.detail && state.detail.clips) || [];
  const project = state.detail && state.detail.project;
  if (!clips.length) {
    if (all.length) {
      return `<div class="empty-clips">Под выбранные фильтры ничего не подошло. Сбросьте настроение или тип.</div>`;
    }
    return `<div class="empty-clips">Клипы появятся здесь, как только будет найден первый момент…</div>`;
  }
  const cards = clips.map((c) => {
    const dur = Math.max(0, (c.end || 0) - (c.start || 0));
    const score = Math.round((c.score || 0) * 100);
    const p = project.id;
    const url = `/media/${p}/clips/clip_${String(c.idx + 1).padStart(2, "0")}.mp4?v=${Math.round(c.updated_at || 0)}`;
    const preview = c.has_preview ? `/media/${p}/previews/${c.id}.mp4?v=${Math.round(c.updated_at || 0)}` : url;
    const thumb = c.thumb ? `/media/${p}/thumbs/${c.id}.jpg` : "";
    const wide = (c.settings?.aspect || "9:16") === "16:9" ? " wide" : (c.settings?.aspect || "") === "1:1" ? " square" : "";
    const sp = c.settings?.score_parts || null;
    const partsLine = sp ? [
      ["хук", sp.hook], ["подача", sp.retention], ["эмоции", sp.emotion],
      ["конкретика", sp.specificity], ["завершённость", sp.completeness],
    ].filter(([, v]) => typeof v === "number")
      .map(([k, v]) => `<span>${k} ${Math.round(v * 100)}</span>`).join("") : "";
    const moodLabel = MOOD_LABELS[c.settings?.mood] || "";
    const moodLine = moodLabel
      ? `<span class="mood-tag" title="Настроение момента">${moodLabel}</span>` : "";
    const typeTags = (c.settings?.content_types || [])
      .map((k) => TYPE_LABELS[k]).filter(Boolean)
      .map((label) => `<span class="type-tag">${label}</span>`).join("");
    const whyLine = c.settings?.why ? `<div class="clip-why">${esc(c.settings.why)}</div>` : "";
    const approxLine = c.settings?.timing === "approx"
      ? `<div class="clip-warn" title="Слова взяты из готовых субтитров: время внутри реплики распределено ровно, точность ниже Whisper">тайминги субтитров приблизительные</div>` : "";
    if (c.status === "error") {
      return `<div class="clip-card${wide}">
        <div class="clip-media" style="display:grid;place-items:center;padding:16px;text-align:center">
          <div style="font-size:12px;color:#fca5a5;line-height:1.45">Не удалось отрендерить<br>${esc((c.error || "").slice(0, 90))}</div>
        </div>
        <div class="clip-body"><div class="clip-title">${esc(c.title || "Клип")}</div></div>
      </div>`;
    }
    if (c.status !== "ready") {
      return `<div class="clip-card${wide} rendering">
        <div class="clip-media"></div>
        <div class="clip-body"><div class="clip-title">${esc(c.title || "Клип")}</div></div>
      </div>`;
    }
    return `<div class="clip-card${wide}" data-clip="${c.id}">
      <div class="clip-media" data-action="edit">
        <video src="${preview}#t=0.1" ${thumb ? `poster="${thumb}"` : ""} muted loop playsinline preload="metadata"></video>
        <div class="play-hint">${ICONS.play}</div>
        <div class="score-badge ${score >= 70 ? "hot" : ""}" title="Оценка момента по структуре речи, а не прогноз просмотров">⚡ ${score}</div>
        <div class="dur-badge">${fmtDur(dur)}</div>
        <div class="clip-quick">
          <button class="glass-btn" data-action="copy" title="Копировать подпись">${ICONS.copy}</button>
          ${c.settings && c.settings.segments ? "" : `<button class="glass-btn" data-action="edit" title="Редактировать">${ICONS.edit}</button>`}
        </div>
      </div>
      <div class="clip-body">
        <div class="clip-title">${esc(c.title || "Без названия")}</div>
        ${(partsLine || moodLine || typeTags) ? `<div class="clip-parts">${moodLine}${typeTags}${partsLine}</div>` : ""}
        ${whyLine}${approxLine}
        <div class="clip-tools">
          <a class="download-btn" href="/api/clips/${c.id}/download" download data-download-clip="${c.id}" title="Скачать MP4">
            ${ICONS.download}<span>Скачать MP4</span>
          </a>
          <a class="srt-btn" href="/api/clips/${c.id}/subtitles.ass" download title="Скачать субтитры (ASS для монтажа)">ASS</a>
                <a class="srt-btn" href="/api/clips/${c.id}/subtitles.srt" download title="Скачать субтитры (SRT)">SRT</a>
        </div>
      </div>
    </div>`;
  });
  return `<div class="grid" id="clipsGrid">${cards.join("")}</div>`;
}

function resLabel(m) {
  const h = m.source_height || 0;
  if (!h) return "";
  const w = m.width || 0;
  return w && h > w ? `${w}×${h}` : `${h}p`;
}

function qualityText(project) {
  const m = project.meta || {};
  const parts = [];
  if (m.source_height) parts.push(resLabel(m));
  if (m.vcodec && m.vcodec !== "none") {
    const v = String(m.vcodec);
    parts.push(v.startsWith("avc") || v.startsWith("h264") ? "H.264" : v.startsWith("vp9") ? "VP9" : v.startsWith("av01") ? "AV1" : v);
  }
  if (m.download_seconds) parts.push(`${Math.round(m.download_seconds)} с`);
  if (m.avg_speed_mbps) parts.push(`${m.avg_speed_mbps} МБ/с`);
  if (m.max_height && m.source_height && m.max_height <= 720) parts.push(`максимум ${m.max_height}p`);
  return parts.join(" · ");
}

function fallbackHTML(project) {
  const m = project.meta || {};
  if (!m.fallback) return "";
  const reason = m.fallback_reason ? esc(String(m.fallback_reason)) : "источник отклонил загрузку";
  return `<div class="warn-box"><strong>1080p не удалось.</strong> ${reason}. Сейчас используется ${m.source_height || "?"}p.
    <button class="link-btn" data-action="retry-hd">Повторить в 1080p</button></div>`;
}

function streamHomeHTML() {
  const streams = state.projects.filter((p) => p.meta && p.meta.live);
  return `
  <section class="hero">
    <div class="eyebrow">${ICONS.spark} Прямой эфир</div>
    <h1 class="hero-title">Нарезки <span class="grad">по ходу стрима</span></h1>
    <p class="hero-sub">Вставьте ссылку на идущий эфир (Twitch, Kick). Приложение запишет его локально и будет находить моменты каждые несколько минут — клипы появятся до конца трансляции.</p>
    <div class="url-box">
      <input id="streamInput" type="text" placeholder="https://www.twitch.tv/канал или https://kick.com/канал" autocomplete="off" spellcheck="false" />
      <button class="btn-primary" id="streamStartBtn">Записать и нарезать</button>
    </div>
  </section>
  <div class="section-title"><h3>Активные записи</h3></div>
  <div class="project-list" id="streamList">${
    streams.length ? streams.map((p) => `
      <button class="project-item" data-project="${p.id}">
        <span class="status-dot live"></span>
        <span class="pi-title">${esc(p.title || p.url)}</span>
        <span class="pi-sub">${esc(p.stage || "")} · ${Math.round((p.meta.live_duration || 0) / 60)} мин${
          streamHint(p.meta) ? ` · ${streamHint(p.meta)}` : ""}</span>
      </button>`).join("") : `<div class="empty-clips">Записей пока нет — вставьте ссылку на эфир.</div>`
  }</div>`;
}

function streamHint(meta) {
  const m = meta || {};
  if (m.live_status === "offline") return "ждём эфир";
  if (m.live_status === "reconnecting") return "нет связи";
  return "";
}

function liveNoticeHTML(project) {
  const m = project.meta || {};
  const warnings = [];
  if (m.live_status === "offline") {
    warnings.push(`<div class="warn-box"><strong>Эфир ещё не идёт.</strong>
      Запись начнётся автоматически, как только канал выйдет в эфир. Можно оставить окно
      открытым или остановить запись.</div>`);
  }
  if (m.live_error && m.live_status !== "live" && m.live_status !== "offline") {
    warnings.push(`<div class="warn-box"><strong>Подключение:</strong> ${esc(String(m.live_error))}</div>`);
  }
  if (project.error) {
    warnings.push(`<div class="warn-box"><strong>Ошибка:</strong> ${esc(String(project.error))}</div>`);
  }
  return warnings.join("");
}

function streamHTML(project) {
  const m = project.meta || {};
  const mb = Math.round((m.live_bytes || 0) / 1048576);
  return `
  <div class="project-head">
    <div>
      <h2>${esc(project.title || project.url)}</h2>
      <div class="project-meta"><span class="status-dot live"></span><span id="liveStage">${esc(project.stage || "Запись")}</span><span id="liveDur">${Math.round((m.live_duration || 0) / 60)} мин записи</span><span id="liveBytes">${mb} МБ</span><span id="liveClips">клипов: ${m.live_clips || 0}</span></div>
    </div>
    <div class="project-actions">
      <button class="btn-ghost danger" data-action="stop-live">Остановить</button>
      <button class="btn-ghost danger" data-action="delete">${ICONS.trash} Удалить</button>
    </div>
  </div>
  <div id="liveNotice">${liveNoticeHTML(project)}</div>
  <div class="section-title"><h3>Клипы по ходу эфира</h3></div>
  <div id="clipsArea">${clipsGridHTML()}</div>`;
}

function reviewHTML(project) {
  const m = project.meta || {};
  const meta = [
    m.segments_mode ? "экономный режим" : resLabel(m),
    project.duration ? fmtDur(project.duration) : "",
    m.pending ? `найдено ${m.pending} моментов` : "",
    m.download_seconds ? `скачано за ${Math.round(m.download_seconds)} с` : ""
  ].filter(Boolean).join(" · ");
  return `
  <div class="project-head">
    <div>
      <h2>${esc(project.title || project.url)}</h2>
      <div class="project-meta"><span>${m.segments_mode ? "Моменты найдены" : "Видео готово"}</span><span>${esc(meta)}</span></div>
    </div>
    <div class="project-actions">
      <button class="btn-primary" data-action="setup">Настроить субтитры</button>
      <button class="btn-ghost" data-action="home">${ICONS.back} Новый</button>
      <button class="btn-ghost danger" data-action="delete">${ICONS.trash} Удалить</button>
    </div>
  </div>
  ${asrWarningHTML(project)}
  <div class="review-card">
    ${project.source_url ? `<video src="${project.source_url}" controls muted playsinline></video>` : ""}
    <div>
      <div class="review-title">Шаблон ещё не выбран</div>
      <p class="review-text">Откройте настройку, посмотрите пример субтитров на видео, выберите шрифт, размер, цвет и положение. Нарезка начнётся после подтверждения.</p>
      <button class="btn-primary" data-action="setup">Открыть настройку</button>
    </div>
  </div>`;
}

function resultsHTML() {
  const { project, clips } = state.detail;
  const ready = clips.filter((c) => c.status === "ready");
  return `
  <div class="project-head">
    <div>
      <h2>${esc(project.title || project.url)}</h2>
      <div class="project-meta">
        <span>${ready.length} ${plural(ready.length, "клип", "клипа", "клипов")}</span>
        ${project.duration ? `<span>${fmtDur(project.duration)} исходник</span>` : ""}
        ${qualityText(project) ? `<span>${esc(qualityText(project))}</span>` : ""}
        ${project.language ? `<span>язык: ${esc(project.language)}</span>` : ""}
        ${project.meta?.elapsed ? `<span>обработано за ${Math.round(project.meta.elapsed)} с</span>` : ""}
      </div>
    </div>
    <div class="project-actions">
      <label class="mini-field" style="min-width:160px">
        <span>Порядок экспорта</span>
        <select id="exportOrder">
          <option value="chrono" ${(project.options?.export_order || "chrono") === "chrono" ? "selected" : ""}>По хронологии</option>
          <option value="score" ${project.options?.export_order === "score" ? "selected" : ""}>Топ моменты</option>
        </select>
      </label>
      ${ready.length ? `<a class="btn-primary" href="/api/projects/${project.id}/zip" data-download-zip="${project.id}" style="display:inline-flex;align-items:center;gap:7px">${ICONS.zip} Скачать всё</a>` : ""}
      <button class="btn-ghost" data-action="folder" title="Открыть папку с готовыми MP4">${ICONS.folder} Открыть папку</button>
      ${ready.length ? `<button class="btn-ghost" data-action="smart-all">Пересобрать в умный кроп</button>` : ""}
      <button class="btn-ghost" data-action="home">${ICONS.back} Новый</button>
      <button class="btn-ghost danger" data-action="delete">${ICONS.trash} Удалить</button>
    </div>
  </div>
  ${fallbackHTML(project)}
  ${asrWarningHTML(project)}
  ${audioPickHTML(project)}
  ${project.error ? `<div class="error-box">${esc(project.error)}</div>` : ""}
  ${clipFilterHTML()}
  <div id="clipsArea">${clipsGridHTML()}</div>`;
}

function renderMain(force) {
  const main = $("#main");
  if (!state.current || !state.detail) {
    if (!state.current) {
      main.innerHTML = heroHTML();
      bindHero();
      state.mainKey = "hero";
    }
    return;
  }
  const project = state.detail.project;
  const clips = state.detail.clips;
  const running = ["queued", "running", "preparing", "processing"].includes(project.status);
  const key = `${project.id}:${project.status}:${clips.length}:${clips.map((c) => c.status).join("")}`;
  if (!force && running && state.mainKey === key) {
    updateProgress(project);
    return;
  }
  state.mainKey = key;
  if (running) {
    main.innerHTML = (project.meta && project.meta.live) ? streamHTML(project) : runningHTML(project);
    bindClips();
    updateProgress(project);
  } else if (project.status === "review") {
    main.innerHTML = reviewHTML(project);
  } else if (project.status === "cancelled") {
    main.innerHTML = cancelledHTML(project);
  } else if (project.status === "error") {
    main.innerHTML = errorHTML(project);
  } else {
    main.innerHTML = resultsHTML();
    bindClips();
  }
}

function bindClips() {
  const orderSelect = $("#exportOrder");
  if (orderSelect) {
    orderSelect.addEventListener("change", async () => {
      if (!state.detail) return;
      try {
        await api(`/api/projects/${state.detail.project.id}/options`, {
          method: "POST",
          body: JSON.stringify({ options: { export_order: orderSelect.value } })
        });
        state.detail.project.options = {
          ...(state.detail.project.options || {}),
          export_order: orderSelect.value
        };
        toast(orderSelect.value === "score" ? "Экспорт: топ моменты" : "Экспорт: по хронологии");
      } catch (err) {
        toast(err.message, "err");
      }
    });
  }
  const applyView = () => {
    const area = $("#clipsArea");
    if (area) {
      area.innerHTML = clipsGridHTML();
      bindClipGrid();
    }
  };
  const viewFields = [["clipMoodFilter", "mood"], ["clipTypeFilter", "type"], ["clipSort", "sort"]];
  viewFields.forEach(([id, key]) => {
    const el = $("#" + id);
    if (!el || el.dataset.bound === "1") return;
    el.dataset.bound = "1";
    el.addEventListener("change", () => {
      state.clipView = { ...(state.clipView || {}), [key]: el.value };
      applyView();
    });
  });
  bindClipGrid();
}

function bindClipGrid() {
  const grid = $("#clipsGrid");
  if (grid && grid.dataset.bound !== "1") {
    grid.dataset.bound = "1";
    grid.addEventListener("pointerover", (e) => {
      const media = e.target.closest(".clip-media");
      if (!media) return;
      const v = media.querySelector("video");
      if (v) v.play().catch(() => {});
    });
    grid.addEventListener("pointerout", (e) => {
      const media = e.target.closest(".clip-media");
      if (!media) return;
      if (media.contains(e.relatedTarget)) return;
      const v = media.querySelector("video");
      if (v) { v.pause(); try { v.currentTime = 0.1; } catch (_) {} }
    });
  }
}

/* ---------------- Sidebar ---------------- */

$("#projectList").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-project]");
  if (btn) openProject(btn.dataset.project);
});

/* ---------------- Main delegated actions ---------------- */

$("#main").addEventListener("click", async (e) => {
  const projBtn = e.target.closest("[data-project]");
  if (projBtn) { openProject(projBtn.dataset.project); return; }

  const dlClip = e.target.closest("[data-download-clip]");
  if (dlClip) {
    const native = window.pywebview && window.pywebview.api && window.pywebview.api.save_clip;
    if (native) {
      e.preventDefault();
      try {
        const res = await window.pywebview.api.save_clip(dlClip.dataset.downloadClip);
        if (res && res.ok) toast(`Сохранено: ${res.path || res.folder || "файл"}`);
        else if (res && res.cancelled) { /* диалог закрыт — ничего не говорим */ }
        else toast((res && res.error) || "Не удалось сохранить", "err");
      } catch (err) { toast(err.message || "Не удалось сохранить", "err"); }
    }
    return;
  }

  const dlZip = e.target.closest("[data-download-zip]");
  if (dlZip) {
    const native = window.pywebview && window.pywebview.api && window.pywebview.api.save_zip;
    if (native) {
      e.preventDefault();
      try {
        const res = await window.pywebview.api.save_zip(dlZip.dataset.downloadZip);
        if (res && res.ok) toast(`Архив сохранён: ${res.path || res.folder || "файл"}`);
        else if (res && res.cancelled) { /* диалог закрыт */ }
        else toast((res && res.error) || "Не удалось сохранить архив", "err");
      } catch (err) { toast(err.message || "Не удалось сохранить архив", "err"); }
    }
    return;
  }

  const actionEl = e.target.closest("[data-action]");
  if (!actionEl) return;
  const action = actionEl.dataset.action;

  if (action === "home") {
    state.current = null;
    state.detail = null;
    state.mainKey = "";
    history.replaceState(null, "", location.pathname);
    clearTimeout(state.pollTimer);
    renderMain(true);
    renderSidebar();
    return;
  }

  if (action === "smart-all") {
    if (!state.detail) return;
    const ready = state.detail.clips.filter((c) => c.status === "ready" || c.status === "error");
    if (!ready.length) return;
    toast(`Пересобираю ${ready.length} клипов с умным кропом…`);
    for (const clip of ready) {
      api(`/api/clips/${clip.id}/rerender`, {
        method: "POST",
        body: JSON.stringify({ mode: "auto" })
      }).catch(() => {});
    }
    setTimeout(() => { loadDetail(true); schedulePoll(800); }, 700);
    return;
  }

  if (action === "stop-live") {
    if (!state.detail) return;
    try {
      await api(`/api/streams/${state.detail.project.id}/stop`, { method: "POST" });
      toast("Запись остановлена");
      schedulePoll(800);
    } catch (err) { toast(err.message, "err"); }
    return;
  }

  if (action === "cancel") {
    if (!state.detail) return;
    const pid = state.detail.project.id;
    try {
      await api(`/api/projects/${pid}/cancel`, { method: "POST" });
      if (state.tmplPid === pid) closeTemplate(true);
      toast("Загрузка отменена");
      await loadDetail(true);
      schedulePoll(600);
    } catch (err) { toast(err.message, "err"); }
    return;
  }

  if (action === "retry-cancelled") {
    if (!state.detail) return;
    const pid = state.detail.project.id;
    try {
      await api(`/api/projects/${pid}/retry`, { method: "POST", body: JSON.stringify({ prepare_only: true }) });
      await loadDetail(true);
      openTemplate(pid);
      schedulePoll(600);
    } catch (err) { toast(err.message, "err"); }
    return;
  }

  if (action === "folder") {
    if (!state.detail) return;
    const native = window.pywebview && window.pywebview.api && window.pywebview.api.open_project_folder;
    if (native) {
      try { await window.pywebview.api.open_project_folder(state.detail.project.id); }
      catch (err) { toast(err.message, "err"); }
    } else {
      toast("Папка с клипами доступна в настольной версии приложения");
    }
    return;
  }

  if (action === "setup") {
    if (!state.detail) return;
    openTemplate(state.detail.project.id);
    return;
  }

  if (action === "retry-hd") {
    if (!state.detail) return;
    try {
      toast("Повторяю загрузку в 1080p…");
      await api(`/api/projects/${state.detail.project.id}/retry`, {
        method: "POST",
        body: JSON.stringify({ force_hd: true })
      });
      await loadDetail(true);
      schedulePoll(600);
    } catch (err) { toast(err.message, "err"); }
    return;
  }

  if (action === "retry") {
    if (!state.detail) return;
    try {
      await api(`/api/projects/${state.detail.project.id}/retry`, { method: "POST" });
      toast("Запускаю обработку заново");
      await loadDetail(true);
      schedulePoll(600);
    } catch (err) { toast(err.message, "err"); }
    return;
  }

  if (action === "delete") {
    if (!state.detail) return;
    if (!confirm("Удалить проект и все клипы? Файлы будут стёрты с диска.")) return;
    try {
      await api(`/api/projects/${state.detail.project.id}`, { method: "DELETE" });
      state.projects = state.projects.filter((p) => p.id !== state.detail.project.id);
      state.current = null;
      state.detail = null;
      state.mainKey = "";
      clearTimeout(state.pollTimer);
      history.replaceState(null, "", location.pathname);
      renderSidebar();
      renderMain(true);
      toast("Проект удалён");
    } catch (err) { toast(err.message, "err"); }
    return;
  }

  const card = actionEl.closest("[data-clip]");
  const clipId = card && card.dataset.clip;

  if (action === "copy" && clipId) {
    const clip = state.detail.clips.find((c) => c.id === clipId);
    try {
      await navigator.clipboard.writeText(clip.caption || clip.title || "");
      toast("Подпись с хештегами скопирована");
    } catch (_) { toast("Не удалось скопировать", "err"); }
    return;
  }

  if (action === "edit" && clipId) {
    openEditor(clipId);
  }
});

/* ---------------- Template preview ---------------- */

function templateDefaults(project) {
  const o = project.options || {};
  return {
    font: o.sub_font || "montserrat",
    size: Number(o.sub_size || 118),
    pos: o.sub_position || "bottom",
    offset: Number(o.sub_offset || 0),
    speed: o.sub_speed || "calm",
    accent: o.accent || "yellow",
    uppercase: o.uppercase !== false,
    showHook: o.show_hook !== false,
    subtitles: o.subtitles !== false,
    audio: Number(o.audio_track == null ? -1 : o.audio_track),
    audioLang: o.audio_lang || "auto",
    externalAudio: !!o.external_audio,
    externalTrack: Number(o.external_audio_track == null ? -1 : o.external_audio_track),
    audioOffset: Number(o.audio_offset || 0),
    exportOrder: o.export_order || "chrono"
  };
}

function templateOptions() {
  const base = (state.tmplDetail && state.tmplDetail.project.options) || {};
  const audioEl = $("#tpAudio");
  const dubUse = $("#tpDubUse");
  const dubTrack = $("#tpDubTrack");
  const dubOffset = $("#tpDubOffset");
  return {
    ...base,
    ...(state.tmplUniq || {}),
    sub_font: $("#tpFont").value,
    sub_size: Number($("#tpSize").value),
    sub_position: $("#tpPos").value,
    sub_offset: Number($("#tpOffset").value),
    sub_speed: ($("#tpSpeed .active") || {}).dataset?.val || "calm",
    subtitles: $("#tpSubs").checked,
    accent: state.tmplAccent,
    uppercase: $("#tpUpper").checked,
    show_hook: $("#tpHook").checked,
    audio_track: audioEl && audioEl.value !== "" ? Number(audioEl.value) : -1,
    audio_lang: $("#tpAudioLang") ? $("#tpAudioLang").value : (base.audio_lang || "auto"),
    external_audio: dubUse ? !!dubUse.checked : !!base.external_audio,
    external_audio_track: dubTrack && dubTrack.value !== "" ? Number(dubTrack.value) : -1,
    audio_offset: dubOffset && dubOffset.value !== "" ? Number(dubOffset.value) : 0,
    export_order: $("#tpExportOrder") ? $("#tpExportOrder").value : "chrono"
  };
}

function renderDub(project) {
  const name = $("#tpDubName");
  const use = $("#tpDubUse");
  const del = $("#tpDubDel");
  const btn = $("#tpDubBtn");
  const field = $("#tpDubField");
  const trackField = $("#tpDubTrackField");
  const track = $("#tpDubTrack");
  const offset = $("#tpDubOffset");
  const hint = $("#tpDubHint");
  if (!name || !use || !btn) return;
  if (field) {
    // Экономный режим качает только выбранные куски: общей дорожки там нет.
    field.style.display = (project && project.meta && project.meta.segments_mode) ? "none" : "";
  }
  const dub = project && project.dub;
  const o = (project && project.options) || {};
  if (!dub) {
    name.textContent = "не подключена";
    name.classList.add("muted");
    use.checked = false;
    use.disabled = true;
    if (del) del.classList.add("hidden");
    btn.textContent = "подключить";
    if (trackField) trackField.style.display = "none";
    if (offset) { offset.value = "0"; offset.disabled = true; }
    if (hint) hint.textContent = "Подключите отдельный аудиофайл или контейнер с русской дорожкой — он заменит звук оригинала. Положительный сдвиг задерживает звук, если голос опережает картинку.";
    const noDubSubs = $("#tpDubSubs");
    if (noDubSubs) {
      const attached = Number(((project && project.meta) || {}).subtitles_attached || 0);
      noDubSubs.textContent = attached ? `свои субтитры: ${attached} реплик` : "субтитры не приложены";
      noDubSubs.classList.toggle("muted", !attached);
    }
    return;
  }
  name.textContent = `${dub.name || "файл"} · ${fmtDur(dub.duration || 0)}`;
  name.classList.remove("muted");
  use.disabled = false;
  use.checked = !!o.external_audio;
  if (del) del.classList.remove("hidden");
  btn.textContent = "заменить";
  const tracks = Array.isArray(dub.audio_tracks) ? dub.audio_tracks : [];
  const selected = Number(o.external_audio_track == null ? -1 : o.external_audio_track);
  if (trackField && track) {
    if (tracks.length > 1) {
      track.innerHTML = `<option value="-1">По умолчанию</option>` + tracks.map((t) =>
        `<option value="${t.index}">${esc(audioTrackLabel(t))}</option>`).join("");
      track.value = tracks.some((t) => Number(t.index) === selected) ? String(selected) : "-1";
      trackField.style.display = "";
    } else {
      trackField.style.display = "none";
    }
  }
  if (offset) {
    offset.disabled = false;
    offset.value = String(Number(o.audio_offset || 0));
  }
  if (hint) {
    const known = Number((project && project.duration) || 0);
    const gap = known > 0 ? Math.abs(Number(dub.duration || 0) - known) : 0;
    hint.textContent = gap > 2
      ? `Длительности отличаются на ${gap.toFixed(1)} с — если голос разъехался с картинкой, поправьте сдвиг.`
      : "Дубляж заменит звук оригинала. Если голос отстаёт — увеличьте сдвиг, если спешит — уменьшите.";
  }
  const subsChip = $("#tpDubSubs");
  if (subsChip) {
    const attached = Number(((project && project.meta) || {}).subtitles_attached || 0);
    subsChip.textContent = attached ? `свои субтитры: ${attached} реплик` : "субтитры не приложены";
    subsChip.classList.toggle("muted", !attached);
  }
}

async function uploadDub(file) {
  if (!state.tmplPid || !file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await api(`/api/projects/${state.tmplPid}/dub`, { method: "POST", body: form });
    if (state.tmplDetail && state.tmplDetail.project) {
      state.tmplDetail.project.dub = res.dub;
      state.tmplDetail.project.options = {
        ...(state.tmplDetail.project.options || {}),
        external_audio: true
      };
      renderDub(state.tmplDetail.project);
      const use = $("#tpDubUse");
      if (use) use.checked = true;
    }
    toast("Дубляж подключён — звук клипов заменится");
  } catch (err) {
    toast("Дубляж не принят: " + err.message, "err");
  }
}

async function deleteDub() {
  if (!state.tmplPid) return;
  try {
    await api(`/api/projects/${state.tmplPid}/dub`, { method: "DELETE" });
    if (state.tmplDetail && state.tmplDetail.project) {
      state.tmplDetail.project.dub = null;
      state.tmplDetail.project.options = {
        ...(state.tmplDetail.project.options || {}),
        external_audio: false
      };
      renderDub(state.tmplDetail.project);
    }
    toast("Дубляж убран — звук снова из оригинала");
  } catch (err) { toast(err.message, "err"); }
}

function renderAudioTracks(project, selected) {
  const field = $("#tpAudioField");
  const select = $("#tpAudio");
  if (!field || !select) return;
  const tracks = project.audio_tracks || (project.meta && project.meta.audio_tracks) || [];
  if ((project.meta && project.meta.segments_mode) || !Array.isArray(tracks) || tracks.length < 2) {
    field.style.display = "none";
    select.innerHTML = "";
    return;
  }
  const current = Number(selected);
  const fallback = tracks.find((t) => t.default) || tracks[0];
  const value = tracks.some((t) => Number(t.index) === current) ? current : Number(fallback.index);
  select.innerHTML = tracks.map((t) =>
    `<option value="${t.index}">${esc(audioTrackLabel(t))}</option>`
  ).join("");
  select.value = String(value);
  field.style.display = "";
}

function applyTemplateUniq(key) {
  const preset = UNIQ_PRESETS.find((p) => p.key === key);
  if (!preset) return;
  const o = preset.opts;
  state.tmplUniq = {
    hflip: o.hflip,
    tilt: o.tilt,
    speed: o.speed,
    pitch: o.pitch,
    jump_cuts: o.jumpCuts,
    cut_zoom: o.cutZoom
  };
  $$("#tpUniqPresets .preset-chip").forEach((b) => b.classList.toggle("active", b.dataset.uniq === key));
}

function markTemplateUniq() {
  const current = state.tmplUniq || {};
  const match = UNIQ_PRESETS.find((p) => {
    const o = p.opts;
    return !!current.hflip === o.hflip &&
      Number(current.tilt || 0) === o.tilt &&
      Number(current.speed || 1) === o.speed &&
      Number(current.pitch || 1) === o.pitch &&
      !!current.jump_cuts === o.jumpCuts &&
      !!current.cut_zoom === o.cutZoom;
  });
  $$("#tpUniqPresets .preset-chip").forEach((b) =>
    b.classList.toggle("active", !!match && b.dataset.uniq === match.key)
  );
}

function updateTemplatePreview() {
  const stage = $("#tmplStage");
  const cap = $("#tmplCaption");
  if (!stage || !cap) return;
  const font = $("#tpFont").value;
  const size = Number($("#tpSize").value);
  const pos = $("#tpPos").value;
  const offset = Number($("#tpOffset").value);
  const upper = $("#tpUpper").checked;
  const accent = state.tmplAccent || "yellow";
  const width = stage.clientWidth || 340;
  const px = Math.max(10, Math.round(size * 0.45 * (width / 1080)));
  cap.style.fontFamily = FONT_CSS[font] || "VCMontserrat";
  cap.style.fontSize = px + "px";
  cap.style.textTransform = upper ? "uppercase" : "none";
  cap.style.setProperty("--hl", ACCENT_HEX[accent] || ACCENT_HEX.yellow);
  const offsetPct = (offset / 1920) * 100;
  cap.style.transform = "";
  if (pos === "top") {
    cap.style.top = `${pxClamp(13.5 - offsetPct, 1, 90)}%`;
    cap.style.bottom = "auto";
    cap.style.transform = "translateY(0)";
  } else if (pos === "middle") {
    cap.style.top = `${pxClamp(50 - offsetPct, 2, 96)}%`;
    cap.style.bottom = "auto";
    cap.style.transform = "translateY(-50%)";
  } else {
    cap.style.top = "auto";
    cap.style.bottom = `${pxClamp(17.7 + offsetPct, 1, 90)}%`;
    cap.style.transform = "";
  }
  $("#tpSizeVal").textContent = size;
  $("#tpOffsetVal").textContent = offset;
  startCaptionPreview();
}

function startCaptionPreview() {
  clearInterval(state.tmplAnim);
  const cap = $("#tmplCaption");
  if (!cap) return;
  const words = $$(".w", cap);
  if (!words.length) return;
  const speed = (($("#tpSpeed .active") || {}).dataset || {}).val || "calm";
  let index = 0;
  const tick = () => {
    words.forEach((w, i) => w.classList.toggle("hl", i === index));
    index = (index + 1) % words.length;
  };
  tick();
  state.tmplAnim = setInterval(tick, SPEED_MS[speed] || SPEED_MS.calm);
}

function applyPreset(key) {
  const preset = STYLE_PRESETS.find((p) => p.key === key);
  if (!preset || !state.tmplDetail) return;
  const t = preset.opts;
  $("#tpFont").value = t.subFont;
  $("#tpSize").value = t.subSize;
  $("#tpPos").value = t.subPos;
  $("#tpOffset").value = t.subOffset;
  state.tmplAccent = t.accent;
  $("#tpUpper").checked = t.uppercase;
  $$("#tpAccents .swatch").forEach((b) => b.classList.toggle("active", b.dataset.val === t.accent));
  updateTemplatePreview();
}

function closeTemplate(keepProject) {
  const pid = state.tmplPid;
  clearTimeout(state.tmplTimer);
  clearInterval(state.tmplAnim);
  state.tmplTimer = null;
  state.tmplAnim = null;
  state.tmplPid = null;
  state.tmplDetail = null;
  state.subsToTemplate = false;
  $("#modal").classList.add("hidden");
  $("#modal").innerHTML = "";
  if (!keepProject) {
    // после закрытия окна возвращаем к проекту: там есть кнопка настроек
    if (pid) openProject(pid);
    else renderSidebar();
  }
}

function openTemplate(pid) {
  if (state.tmplPid === pid) return;
  clearTimeout(state.tmplTimer);
  state.tmplPid = pid;
  state.tmplDetail = null;
  clearInterval(state.tmplAnim);
  state.tmplAccent = "yellow";
  state.tmplUniq = null;
  state.tmplReady = false;

  $("#modal").innerHTML = `
    <div class="modal-backdrop" data-close="tmpl"></div>
    <div class="modal-panel tmpl-panel">
      <div class="modal-head">
        <h3>Настройка субтитров</h3>
        <button class="icon-btn" data-close="tmpl">${ICONS.close}</button>
      </div>
      <div class="tmpl-body">
        <div class="tmpl-left">
          <div class="tmpl-stage" id="tmplStage">
            <video id="tmplVideo" muted loop playsinline></video>
            <div class="tmpl-caption" id="tmplCaption"><span class="w hl">ПРИМЕР</span> <span class="w">СУБТИТРОВ</span></div>
            <div class="tmpl-veil" id="tmplVeil">
              <span class="spinner"></span>
              <div id="tmplStageText">Загрузка видео…</div>
              <div class="tmpl-bar"><i id="tmplBar" style="width:2%"></i></div>
            </div>
          </div>
          <div class="tmpl-hint">Так будет выглядеть вертикальный кадр. Видео можно поставить на паузу.</div>
        </div>
        <div class="tmpl-right">
          <div class="field">
            <label>Шаблоны</label>
            <div class="preset-row">
              ${STYLE_PRESETS.map((p) => `<button class="preset-chip" data-preset="${p.key}">${p.label}</button>`).join("")}
            </div>
          </div>
          <div class="field" id="tpAudioField" style="display:none">
            <label>Дорожка звука</label>
            <select id="tpAudio"></select>
          </div>
          <div class="field">
            <label>Язык звука</label>
            <select id="tpAudioLang">
              <option value="auto">Как в источнике</option>
              <option value="ru">Русский</option>
              <option value="uk">Украинский</option>
              <option value="en">Английский</option>
              <option value="de">Немецкий</option>
              <option value="es">Испанский</option>
            </select>
            <span class="opt-hint">Для нового скачивания: если у источника несколько дорожек, возьмём дорожку этого языка. Ручной выбор ниже сильнее. Старые проекты не меняются.</span>
          </div>
          <div class="field" id="tpDubField">
            <label>Внешняя дорожка (дубляж)</label>
            <div class="dub-row">
              <span id="tpDubName" class="pending-file">не подключена</span>
              <button type="button" class="link-btn" id="tpDubBtn">подключить</button>
              <button type="button" class="link-btn hidden" id="tpDubDel">убрать</button>
            </div>
            <label class="toggle"><input type="checkbox" id="tpDubUse" disabled/><span class="track"></span><span>Заменить звук дубляжом</span></label>
            <div class="row2">
              <div class="field" id="tpDubTrackField" style="display:none">
                <label>Дорожка в файле</label>
                <select id="tpDubTrack"></select>
              </div>
              <div class="field">
                <label>Сдвиг звука, с</label>
                <input type="number" id="tpDubOffset" min="-300" max="300" step="0.1" value="0" />
              </div>
            </div>
            <span class="opt-hint" id="tpDubHint">Подключите отдельный аудиофайл или контейнер с русской дорожкой — он заменит звук оригинала. Положительный сдвиг задерживает звук, если голос опережает картинку.</span>
            <div class="dub-row">
              <span id="tpDubSubs" class="pending-file muted">субтитры не приложены</span>
              <button type="button" class="link-btn" id="tpSubsBtn">приложить субтитры</button>
            </div>
          </div>
          <div class="field">
            <label>Порядок экспорта</label>
            <select id="tpExportOrder">
              <option value="chrono">По хронологии</option>
              <option value="score">Топ моменты</option>
            </select>
          </div>
          <div class="field">
            <label>Уникализация</label>
            <div class="preset-row" id="tpUniqPresets">
              ${UNIQ_PRESETS.map((p) => `<button class="preset-chip" data-uniq="${p.key}">${p.label}</button>`).join("")}
            </div>
          </div>
          <div class="row2">
            <div class="field">
              <label>Шрифт</label>
              <div class="font-pick">
                <select id="tpFont">
                  ${fontOptionsHTML("")}
                </select>
                <button type="button" class="font-add" id="tpFontAdd" title="Загрузить свой шрифт">＋</button>
              </div>
            </div>
            <div class="field">
              <label>Положение</label>
              <select id="tpPos">
                ${SUB_POSITIONS.map(([k, label]) => `<option value="${k}">${label}</option>`).join("")}
              </select>
            </div>
          </div>
          <div class="row2">
            <div class="field">
              <label>Размер <b id="tpSizeVal">118</b></label>
              <input type="range" id="tpSize" min="70" max="180" step="2" value="118" />
            </div>
            <div class="field">
              <label title="Двигает субтитры по всей высоте кадра: от низа до верха">Сдвиг по вертикали <b id="tpOffsetVal">0</b></label>
              <input type="range" id="tpOffset" min="${SUB_OFFSET_MIN}" max="${SUB_OFFSET_MAX}" step="10" value="0" />
            </div>
          </div>
          <div class="field">
            <label>Темп субтитров</label>
            <div class="seg" id="tpSpeed">
              ${SUB_SPEEDS.map(([k, label]) => `<button data-val="${k}" class="active">${label}</button>`).join("")}
            </div>
          </div>
          <div class="field">
            <label>Цвет подсветки</label>
            <div class="swatches" id="tpAccents">
              ${swatchesHTML(state.tmplAccent || "yellow")}
            </div>
          </div>
          <div class="field">
            <label>Оформление</label>
            <div style="display:flex;gap:14px;flex-wrap:wrap">
              <label class="toggle"><input type="checkbox" id="tpSubs" checked/><span class="track"></span><span>Субтитры</span></label>
              <label class="toggle"><input type="checkbox" id="tpUpper" checked/><span class="track"></span><span>КАПСОМ</span></label>
              <label class="toggle"><input type="checkbox" id="tpHook" checked/><span class="track"></span><span>Хук сверху</span></label>
            </div>
          </div>
          <div class="tmpl-meta" id="tmplMeta"></div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn-ghost" data-close="tmpl">Отмена</button>
        <button class="btn-primary" id="tmplStart" disabled>Сделать нарезки</button>
      </div>
    </div>`;

  $("#modal").classList.remove("hidden");
  updateTemplatePreview();

  $("#tpFont").addEventListener("change", updateTemplatePreview);
  const tpFontAdd = $("#tpFontAdd");
  if (tpFontAdd) tpFontAdd.addEventListener("click", () => {
    state.fontTarget = "#tpFont";
    $("#fontInput").click();
  });
  $("#tpSpeed").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-val]");
    if (!btn) return;
    $$("#tpSpeed button").forEach((b) => b.classList.toggle("active", b === btn));
    startCaptionPreview();
  });
  $("#tpSize").addEventListener("input", updateTemplatePreview);
  $("#tpPos").addEventListener("change", updateTemplatePreview);
  $("#tpOffset").addEventListener("input", updateTemplatePreview);
  $("#tpUpper").addEventListener("change", updateTemplatePreview);
  const tpSubs = $("#tpSubs");
  if (tpSubs) tpSubs.addEventListener("change", () => {
    document.querySelectorAll(".tmpl-sub-control").forEach((el) => {
      el.style.opacity = tpSubs.checked ? "1" : "0.45";
    });
    updateTemplatePreview();
  });
  $("#tpAccents").addEventListener("click", (e) => {
    const b = e.target.closest(".swatch");
    if (!b) return;
    state.tmplAccent = b.dataset.val;
    $$("#tpAccents .swatch").forEach((x) => x.classList.toggle("active", x === b));
    updateTemplatePreview();
  });
  $$(".preset-chip[data-preset]", $("#modal")).forEach((btn) => btn.addEventListener("click", () => {
    $$(".preset-chip[data-preset]", $("#modal")).forEach((b) => b.classList.toggle("active", b === btn));
    applyPreset(btn.dataset.preset);
  }));
  $$("#tpUniqPresets .preset-chip").forEach((btn) => btn.addEventListener("click", () => {
    applyTemplateUniq(btn.dataset.uniq);
    updateTemplatePreview();
  }));
  $("#tmplStart").addEventListener("click", startFromTemplate);

  $("#tpDubBtn").addEventListener("click", () => $("#dubInput").click());
  const tpDubDel = $("#tpDubDel");
  if (tpDubDel) tpDubDel.addEventListener("click", deleteDub);
  const tpSubsBtn = $("#tpSubsBtn");
  if (tpSubsBtn) tpSubsBtn.addEventListener("click", () => {
    state.subsToTemplate = true;
    $("#subsInput").click();
  });

  tmplPoll();
}

async function tmplPoll() {
  if (!state.tmplPid) return;
  try {
    const detail = await api(`/api/projects/${state.tmplPid}`);
    state.tmplDetail = detail;
    const project = detail.project;
    const veil = $("#tmplVeil");
    const text = $("#tmplStageText");
    if (!veil) return;

    if (["preparing", "queued", "running", "processing"].includes(project.status)) {
      veil.classList.remove("hidden");
      text.textContent = project.stage || "Загрузка видео…";
      $("#tmplBar").style.width = Math.max(2, project.progress || 0) + "%";
      state.tmplTimer = setTimeout(tmplPoll, 1200);
      return;
    }
    if (project.status === "cancelled") {
      veil.classList.remove("hidden");
      veil.innerHTML = `<div class="tmpl-error">Обработка отменена</div>
        <button class="btn-ghost" id="tmplRetry">Начать заново</button>`;
      $("#tmplRetry").addEventListener("click", async () => {
        await api(`/api/projects/${project.id}/retry`, {
          method: "POST",
          body: JSON.stringify({ force_hd: false, prepare_only: true })
        });
        openTemplate(project.id);
      });
      return;
    }
    if (project.status === "error") {
      veil.classList.remove("hidden");
      veil.innerHTML = `<div class="tmpl-error">${esc(project.error || "Не удалось загрузить видео")}</div>
        <button class="btn-ghost" id="tmplRetry">Повторить загрузку</button>`;
      $("#tmplRetry").addEventListener("click", async () => {
        await api(`/api/projects/${project.id}/retry`, { method: "POST", body: JSON.stringify({ force_hd: false, prepare_only: true }) });
        openTemplate(project.id);
      });
      return;
    }
    if (project.status === "draft" || project.status === "review") {
      const defaults = templateDefaults(project);
      $("#tpFont").value = defaults.font;
      $("#tpSize").value = defaults.size;
      $("#tpPos").value = defaults.pos;
      $("#tpOffset").value = defaults.offset;
      $("#tpSubs").checked = defaults.subtitles !== false;
  $("#tpUpper").checked = defaults.uppercase;
      $("#tpHook").checked = defaults.showHook;
      const tpExportOrder = $("#tpExportOrder");
      if (tpExportOrder) tpExportOrder.value = defaults.exportOrder;
      $$("#tpSpeed button").forEach((b) => b.classList.toggle("active", b.dataset.val === defaults.speed));
      state.tmplAccent = defaults.accent;
      $$("#tpAccents .swatch").forEach((b) => b.classList.toggle("active", b.dataset.val === defaults.accent));
      renderAudioTracks(project, defaults.audio);
      const tpAudioLang = $("#tpAudioLang");
      if (tpAudioLang) tpAudioLang.value = defaults.audioLang;
      renderDub(project);
      if (state.tmplUniq === null) {
        const o = project.options || {};
        state.tmplUniq = {
          hflip: !!o.hflip,
          tilt: Number(o.tilt || 0),
          speed: Number(o.speed || 1),
          pitch: Number(o.pitch || 1),
          jump_cuts: !!o.jump_cuts,
          cut_zoom: !!o.cut_zoom
        };
      }
      markTemplateUniq();
      updateTemplatePreview();

      const video = $("#tmplVideo");
      if (project.source_url && video.getAttribute("src") !== project.source_url) {
        video.setAttribute("src", project.source_url);
        video.play().catch(() => {});
      }
      veil.classList.add("hidden");
      const startBtn = $("#tmplStart");
      if (project.status === "draft") {
        startBtn.disabled = false;
        startBtn.textContent = state.pendingFile ? "Загрузить и нарезать" : "Выбрать файл";
        const pendingName = state.pendingFile ? state.pendingFile.name : "файл не выбран";
        $("#tmplMeta").textContent = `Файл ещё не загружен · ${pendingName}`;
        return;
      }
      startBtn.disabled = false;
      startBtn.textContent = "Сделать нарезки";
      const m = project.meta || {};
      $("#tmplMeta").textContent = [
        m.segments_mode ? "Экономный режим: видео качается только для выбранных моментов" : "",
        m.pending ? `Найдено моментов: ${m.pending}` : "",
        !m.segments_mode && m.source_height ? `Источник: ${resLabel(m)}` : "",
        project.duration ? `Длительность: ${fmtDur(project.duration)}` : ""
      ].filter(Boolean).join(" · ");
      return;
    }
    if (project.status === "done") {
      closeTemplate(true);
      openProject(project.id);
    }
  } catch (err) {
    state.tmplTimer = setTimeout(tmplPoll, 1500);
  }
}

async function startFromTemplate() {
  if (!state.tmplPid || !state.tmplDetail) return;
  const btn = $("#tmplStart");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Запуск';
  try {
    const project = state.tmplDetail.project;
    if (!["draft", "review"].includes(project.status)) {
      toast("Это видео уже обработано или ещё не готово к запуску", "err");
      btn.disabled = false;
      return;
    }
    if (project.status === "draft" && project.url === "local:source") {
      if (!state.pendingFile) {
        btn.disabled = false;
        btn.textContent = "Выбрать файл";
        $("#fileInput").click();
        return;
      }
      btn.innerHTML = '<span class="spinner"></span> Загружаю файл';
      const form = new FormData();
      form.append("file", state.pendingFile);
      await api(`/api/projects/${project.id}/upload`, { method: "POST", body: form });
      state.pendingFile = null;
      state.tmplDetail = await api(`/api/projects/${project.id}`);
    } else if (project.status === "draft") {
      btn.innerHTML = '<span class="spinner"></span> Запускаю';
      await api(`/api/projects/${project.id}/retry`, {
        method: "POST",
        body: JSON.stringify({ force_hd: false, prepare_only: false, options: templateOptions() })
      });
      tmplPoll();
      return;
    }
    await api(`/api/projects/${project.id}/start`, {
      method: "POST",
      body: JSON.stringify({ options: templateOptions() })
    });
    const pid = project.id;
    closeTemplate(true);
    toast("Шаблон применён — нарезаю видео");
    await loadProjects();
    openProject(pid);
    schedulePoll(500);
  } catch (err) {
    toast(err.message, "err");
    btn.disabled = false;
    btn.textContent = "Сделать нарезки";
  }
}

/* ---------------- Editor ---------------- *//* ---------------- Editor ---------------- */

function clipUrl(clip) {
  const p = state.detail.project.id;
  return `/media/${p}/clips/clip_${String(clip.idx + 1).padStart(2, "0")}.mp4?v=${Math.round(clip.updated_at || 0)}`;
}

function openEditor(clipId) {
  const clip = state.detail.clips.find((c) => c.id === clipId);
  if (!clip) return;
  const project = state.detail.project;
  const liveDur = (project.meta && project.meta.live_duration) || 0;
  const maxT = Math.max(1, (project.duration || liveDur || clip.end) - 0.2);
  const s = clip.settings || {};
  const accent = s.accent || "yellow";
  const fontKey = s.sub_font || "montserrat";
  const fontSize = Number(s.sub_size || 118);
  const fontPos = s.sub_position || "bottom";
  const fontOffset = Number(s.sub_offset || 0);
  const subSpeed = s.sub_speed || "calm";
  let editorSplit = Number(s.split_ratio || 0.5);
  let editorAdhdBg = String(s.adhd_bg || "");
  const adhdSplitMin = Math.min(adhdLimits().min, Math.round(editorSplit * 100));
  const adhdSplitMax = adhdLimits().max;

  $("#modal").innerHTML = `
    <div class="modal-backdrop" data-close></div>
    <div class="modal-panel">
      <div class="modal-head">
        <h3>Редактировать клип</h3>
        <button class="icon-btn" data-close>${ICONS.close}</button>
      </div>
      <div class="modal-body">
        <div class="editor-preview">
          <div class="ed-stage" id="edStage">
            <canvas id="edCanvas"></canvas>
            <div class="ed-hook" id="edHookView"></div>
            <div class="ed-sub" id="edSubView"></div>
            <div class="ed-stage-hint" id="edStageHint">Беру кадр из видео…</div>
          </div>
          <video id="edVideo" class="ed-video-small" src="${clipUrl(clip)}" controls playsinline></video>
          <video id="edSrc" class="hidden" muted playsinline preload="auto" src="${project.source_url || ""}"></video>
        </div>
        <div class="editor-fields">
          <div class="field">
            <label>Заголовок на видео (хук)</label>
            <input type="text" id="edHook" maxlength="90" value="${esc(clip.hook || clip.title || "")}" />
          </div>
          <div class="field">
            <label>Текст субтитров <span style="color:var(--muted-2);font-weight:400">— правьте имена и термины, тайминги сохранятся</span></label>
            <textarea id="edText" rows="3" style="width:100%;resize:vertical">${esc((clip.words || []).map((w) => w.word).join(" "))}</textarea>
          </div>
          <div class="row2">
            <div class="field">
              <label>Начало</label>
              <div class="range-row">
                <input type="range" id="edStart" min="0" max="${maxT}" step="0.1" value="${clip.start}" />
                <input type="number" id="edStartNum" min="0" max="${maxT}" step="0.1" value="${clip.start.toFixed(1)}" />
              </div>
              <div class="nudge-row">
                <button type="button" class="mini-btn" data-nudge="start:-1">−1 с</button>
                <button type="button" class="mini-btn" data-nudge="start:-0.2">−0.2</button>
                <button type="button" class="mini-btn" data-nudge="start:0.2">+0.2</button>
                <button type="button" class="mini-btn" data-nudge="start:1">+1 с</button>
                <button type="button" class="mini-btn" data-nudge="start:word">к слову</button>
              </div>
            </div>
            <div class="field">
              <label>Конец</label>
              <div class="range-row">
                <input type="range" id="edEnd" min="0" max="${maxT}" step="0.1" value="${clip.end}" />
                <input type="number" id="edEndNum" min="0" max="${maxT}" step="0.1" value="${clip.end.toFixed(1)}" />
              </div>
              <div class="nudge-row">
                <button type="button" class="mini-btn" data-nudge="end:-1">−1 с</button>
                <button type="button" class="mini-btn" data-nudge="end:-0.2">−0.2</button>
                <button type="button" class="mini-btn" data-nudge="end:0.2">+0.2</button>
                <button type="button" class="mini-btn" data-nudge="end:1">+1 с</button>
                <button type="button" class="mini-btn" data-nudge="end:word">к слову</button>
              </div>
              <div class="ed-dur" id="edDur"></div>
            </div>
          </div>
          <div class="row2">
            <div class="field">
              <label>Площадка</label>
              <select id="edPlatform">
                ${PLATFORM_OPTIONS.map(([k, v]) => `<option value="${k}" ${(s.platform || "universal") === k ? "selected" : ""}>${v}</option>`).join("")}
              </select>
            </div>
            <div class="field">
              <label>Пресет стрима</label>
              <select id="edLayout">
                <option value="" ${!s.layout ? "selected" : ""}>Выключен</option>
                <option value="band" ${s.layout === "band" ? "selected" : ""}>Лицо крупно снизу</option>
                <option value="band_top" ${s.layout === "band_top" ? "selected" : ""}>Лицо крупно сверху</option>
                <option value="adhd" ${s.layout === "adhd" ? "selected" : ""}>Сплит-скрин (СДВГ)</option>
              </select>
            </div>
            <div class="field">
              <label>Формат</label>
              <select id="edAspect">
                ${Object.entries(ASPECT_META).map(([a, m]) => `<option value="${a}" ${(s.aspect || "9:16") === a ? "selected" : ""}>${a} — ${m.short}</option>`).join("")}
              </select>
            </div>
            <div class="field">
              <label>Кадрирование</label>
              <select id="edMode">
                <option value="auto" ${s.mode === "auto" ? "selected" : ""}>Умный кроп (по лицу)</option>
                <option value="blur" ${s.mode === "blur" || !s.mode ? "selected" : ""}>Размытый фон</option>
                <option value="crop" ${s.mode === "crop" ? "selected" : ""}>По центру</option>
              </select>
            </div>
          </div>
          <div class="row2 ed-adhd ${s.layout === "adhd" ? "" : "hidden"}" id="edAdhd">
            <div class="field">
              <label>Основное видео <b id="edSplitVal">${Math.round(editorSplit * 100)}</b>%</label>
              <input type="range" id="edSplit" min="${adhdSplitMin}" max="${adhdSplitMax}" step="1" value="${Math.round(editorSplit * 100)}" />
              <span class="opt-hint">Границу можно тянуть прямо в превью. Рекомендуется 40–85%.</span>
            </div>
            <div class="field">
              <label>Нижний ролик</label>
              <select id="edAdhdBg"><option value="">Случайный</option></select>
              <button type="button" class="link-btn" id="edAdhdUploadBtn">загрузить своё видео</button>
              <input type="file" id="edAdhdInput" class="hidden" accept="video/*" />
            </div>
            <div class="field"><label>Верх: заполнение</label>
              <select id="edTopFill"><option value="cover" ${s.adhd_top_fill !== "contain" ? "selected" : ""}>Заполнить</option><option value="contain" ${s.adhd_top_fill === "contain" ? "selected" : ""}>Вписать целиком</option></select>
            </div>
            <div class="field"><label>Низ: заполнение</label>
              <select id="edBottomFill"><option value="cover" ${s.adhd_bottom_fill !== "contain" ? "selected" : ""}>Заполнить</option><option value="contain" ${s.adhd_bottom_fill === "contain" ? "selected" : ""}>Вписать целиком</option></select>
            </div>
            <div class="field"><label>Верх: масштаб <b id="edTopScaleVal">${Math.round(Number(s.adhd_top_scale || 1) * 100)}</b>%</label>
              <input type="range" id="edTopScale" min="50" max="200" step="5" value="${Math.round(Number(s.adhd_top_scale || 1) * 100)}" />
            </div>
            <div class="field"><label>Низ: масштаб <b id="edBottomScaleVal">${Math.round(Number(s.adhd_bottom_scale || 1) * 100)}</b>%</label>
              <input type="range" id="edBottomScale" min="50" max="200" step="5" value="${Math.round(Number(s.adhd_bottom_scale || 1) * 100)}" />
            </div>
            <div class="field"><label>Низ: скорость <b id="edBottomSpeedVal">${Number(s.adhd_bottom_speed || 1).toFixed(2)}</b>×</label>
              <input type="range" id="edBottomSpeed" min="25" max="400" step="5" value="${Math.round(Number(s.adhd_bottom_speed || 1) * 100)}" />
            </div>
            <div class="field"><label>Низ: звук <b id="edBottomVolumeVal">${Math.round(Number(s.adhd_bottom_volume || 0))}</b>%</label>
              <input type="range" id="edBottomVolume" min="0" max="50" step="1" value="${Math.round(Number(s.adhd_bottom_volume || 0))}" />
            </div>
          </div>
          <div class="field">
            <label>Субтитры</label>
            <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
              <label class="toggle"><input type="checkbox" id="edSubs" ${s.subtitles !== false ? "checked" : ""}/><span class="track"></span><span>Показывать</span></label>
              <label class="toggle"><input type="checkbox" id="edUpper" ${s.uppercase !== false ? "checked" : ""}/><span class="track"></span><span>КАПСОМ</span></label>
              <label class="toggle"><input type="checkbox" id="edShowHook" ${s.show_hook !== false ? "checked" : ""}/><span class="track"></span><span>Хук сверху</span></label>
            </div>
          </div>
          <div class="row2">
            <div class="field">
              <label>Звук</label>
              <label class="toggle"><input type="checkbox" id="edDub" ${s.external_audio ? "checked" : ""} ${project.dub ? "" : "disabled"}/><span class="track"></span><span>Дубляж вместо оригинала</span></label>
              ${project.dub ? "" : `<span class="opt-hint">Дубляж не подключён — добавьте его в окне настройки проекта.</span>`}
            </div>
            <div class="field">
              <label>Сдвиг дубляжа, с</label>
              <input type="number" id="edDubOffset" min="-300" max="300" step="0.1" value="${Number(s.audio_offset || 0)}" ${project.dub ? "" : "disabled"} />
            </div>
          </div>
          <div class="row2">
            <div class="field">
              <label>Шрифт субтитров</label>
              <div class="font-pick">
                <select id="edFont">
                  ${fontOptionsHTML(fontKey)}
                </select>
                <button type="button" class="font-add" id="edFontAdd" title="Загрузить свой шрифт">＋</button>
              </div>
              <div class="font-sample ed-sample" id="edFontSample" style="font-family:${FONT_CSS[fontKey] || "VCMontserrat"}">ПРИМЕР СУБТИТРОВ</div>
            </div>
            <div class="field">
              <label>Положение</label>
              <select id="edPos">
                ${SUB_POSITIONS.map(([k, label]) => `<option value="${k}" ${fontPos === k ? "selected" : ""}>${label}</option>`).join("")}
              </select>
            </div>
          </div>
          <div class="row2">
            <div class="field">
              <label>Размер <b id="edSizeVal">${fontSize}</b></label>
              <input type="range" id="edSize" min="70" max="180" step="2" value="${fontSize}" />
            </div>
            <div class="field">
              <label title="Двигает субтитры по всей высоте кадра: от низа до верха">Сдвиг по вертикали <b id="edOffVal">${fontOffset}</b></label>
              <input type="range" id="edOffset" min="${SUB_OFFSET_MIN}" max="${SUB_OFFSET_MAX}" step="10" value="${fontOffset}" />
            </div>
            <div class="field">
              <label>Межстрочный интервал <b id="edLineGapVal">${Number(s.line_gap || 0)}</b></label>
              <input type="range" id="edLineGap" min="0" max="80" step="2" value="${Number(s.line_gap || 0)}" />
            </div>
          </div>
          <div class="field">
            <label>Темп субтитров</label>
            <div class="seg" id="edSpeed">
              ${SUB_SPEEDS.map(([k, label]) => `<button data-val="${k}" class="${subSpeed === k ? "active" : ""}">${label}</button>`).join("")}
            </div>
          </div>
          <div class="field">
            <label>Цвет подсветки</label>
            <div class="swatches" id="edAccents">
              ${swatchesHTML(accent)}
            </div>
          </div>
          <div class="field">
            <label>Уникализация</label>
            <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
              <label class="toggle"><input type="checkbox" id="edHflip" ${s.hflip ? "checked" : ""}/><span class="track"></span><span>Зеркало</span></label>
              <label class="toggle"><input type="checkbox" id="edJumpCuts" ${s.jump_cuts ? "checked" : ""}/><span class="track"></span><span>Склейки пауз</span></label>
              <label class="toggle"><input type="checkbox" id="edCutZoom" ${s.cut_zoom ? "checked" : ""}/><span class="track"></span><span>Зум на склейках</span></label>
            </div>
          </div>
          <div class="row2">
            <div class="field">
              <label>Наклон <b id="edTiltVal">${Number(s.tilt || 0)}</b>°</label>
              <input type="range" id="edTilt" min="0" max="3" step="0.5" value="${Number(s.tilt || 0)}" />
            </div>
            <div class="field">
              <label>Скорость <b id="edSpeedRVal">${Number(s.speed || 1).toFixed(2)}</b>×</label>
              <input type="range" id="edSpeedR" min="1" max="1.1" step="0.01" value="${Number(s.speed || 1)}" />
            </div>
            <div class="field">
              <label>Питч <b id="edPitchVal">${Number(s.pitch || 1).toFixed(2)}</b>×</label>
              <input type="range" id="edPitch" min="0.95" max="1.05" step="0.01" value="${Number(s.pitch || 1)}" />
            </div>
          </div>
          <div class="field">
            <label>Подпись для публикации</label>
            <textarea id="edCaption">${esc(clip.caption || "")}</textarea>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn-ghost" data-close>Отмена</button>
        <button class="btn-primary" id="edSave">Перерендерить</button>
      </div>
    </div>`;

  $("#modal").classList.remove("hidden");

  let chosenAccent = accent;
  $("#edAccents").addEventListener("click", (e) => {
    const b = e.target.closest(".swatch");
    if (!b) return;
    chosenAccent = b.dataset.val;
    $$(".swatch", $("#edAccents")).forEach((x) => x.classList.toggle("active", x === b));
    updateEditorPreview();
  });

  /* --- Живой предпросмотр: кадр из источника + текст субтитров --- */
  const stage = $("#edStage");
  const canvas = $("#edCanvas");
  const srcVideo = $("#edSrc");
  const subView = $("#edSubView");
  const hookView = $("#edHookView");
  const stageHint = $("#edStageHint");

  const drawCover = (ctx, video, dx, dy, dw, dh) => {
    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh) return;
    const scale = Math.max(dw / vw, dh / vh);
    const sw = dw / scale, sh = dh / scale;
    const sx = (vw - sw) / 2, sy = (vh - sh) / 2;
    ctx.drawImage(video, sx, sy, sw, sh, dx, dy, dw, dh);
  };

  const drawFacecam = (ctx, fc, dx, dy, dw, dh, rounded) => {
    if (!fc) return;
    ctx.save();
    if (rounded) {
      const r = Math.min(dw, dh) * 0.08;
      ctx.beginPath();
      ctx.moveTo(dx + r, dy);
      ctx.arcTo(dx + dw, dy, dx + dw, dy + dh, r);
      ctx.arcTo(dx + dw, dy + dh, dx, dy + dh, r);
      ctx.arcTo(dx, dy + dh, dx, dy, r);
      ctx.arcTo(dx, dy, dx + dw, dy, r);
      ctx.closePath();
      ctx.clip();
    }
    const vw = srcVideo.videoWidth, vh = srcVideo.videoHeight;
    const fx = Math.max(0, fc.x), fy = Math.max(0, fc.y);
    const fw = Math.min(fc.w, vw - fx), fh = Math.min(fc.h, vh - fy);
    const scale = Math.max(dw / fw, dh / fh);
    const sw = dw / scale, sh = dh / scale;
    ctx.drawImage(srcVideo, fx + (fw - sw) / 2, fy + (fh - sh) / 2, sw, sh, dx, dy, dw, dh);
    ctx.restore();
  };

  const drawFrame = () => {
    if (!stage || !canvas || !srcVideo || !srcVideo.videoWidth) return;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(stage.clientWidth * dpr));
    const h = Math.max(1, Math.round(stage.clientHeight * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    const mirror = $("#edHflip") ? $("#edHflip").checked : false;
    const tiltDeg = $("#edTilt") ? Number($("#edTilt").value) : 0;
    const parts = [];
    if (tiltDeg > 0) parts.push("scale(1.06)", `rotate(${tiltDeg}deg)`);
    if (mirror) parts.push("scaleX(-1)");
    canvas.style.transform = parts.join(" ");
    const ctx = canvas.getContext("2d");
    const layout = $("#edLayout") ? $("#edLayout").value : "";
    const fc = (s && s.facecam) || null;
    const k = w / 1080;

    if (layout === "band" && fc) {
      const topH = Math.round(h * 1280 / 1920);
      drawCover(ctx, srcVideo, 0, 0, w, topH);
      ctx.fillStyle = "#000";
      ctx.fillRect(0, topH, w, h - topH);
      drawFacecam(ctx, fc, 0, topH, w, h - topH, false);
    } else if (layout === "band_top" && fc) {
      const bandH = Math.round(h * 640 / 1920);
      drawFacecam(ctx, fc, 0, 0, w, bandH, false);
      drawCover(ctx, srcVideo, 0, bandH, w, h - bandH);
    } else if (layout === "adhd") {
      const geometry = window.VCGeometry
        ? VCGeometry.splitGeometry(w, h, editorSplit)
        : { top_h: Math.round(h * editorSplit), bottom_h: h - Math.round(h * editorSplit) };
      const topH = geometry.top_h;
      drawCover(ctx, srcVideo, 0, 0, w, topH);
      ctx.fillStyle = "#101116";
      ctx.fillRect(0, topH, w, h - topH);
      ctx.fillStyle = "rgba(255,255,255,0.38)";
      ctx.textAlign = "center";
      ctx.font = `${Math.max(9, Math.round(22 * k))}px VCMontserrat, sans-serif`;
      ctx.fillText("нижний ролик", w / 2, topH + (h - topH) / 2);
      ctx.textAlign = "start";
      stage.style.cursor = "ns-resize";
      ctx.strokeStyle = "rgba(255,255,255,0.18)";
      ctx.lineWidth = Math.max(1, Math.round(2 * k));
      ctx.beginPath();
      ctx.moveTo(0, topH);
      ctx.lineTo(w, topH);
      ctx.stroke();
    } else {
      drawCover(ctx, srcVideo, 0, 0, w, h);
    }
    if (stageHint) stageHint.classList.add("hidden");
  };

  const seekSource = () => {
    if (!srcVideo || !srcVideo.src) return;
    const target = Math.max(0, Number(start.value) + 0.3);
    try {
      if (Math.abs(srcVideo.currentTime - target) > 0.4) srcVideo.currentTime = target;
      else drawFrame();
    } catch (_) {}
  };

  if (srcVideo) {
    srcVideo.addEventListener("loadeddata", seekSource);
    srcVideo.addEventListener("seeked", drawFrame);
    if (srcVideo.readyState >= 2) seekSource();
  }

  const updateEditorPreview = () => {
    if (!stage || !subView) return;
    const W = stage.clientWidth || 1;
    const k = W / 1080;
    const zone = PLATFORM_ZONES[$("#edPlatform") ? $("#edPlatform").value : "universal"] || PLATFORM_ZONES.universal;
    const size = Number($("#edSize") ? $("#edSize").value : 118) * 0.45 * k;
    const position = $("#edPos") ? $("#edPos").value : "bottom";
    const offset = Number($("#edOffset") ? $("#edOffset").value : 0);
  const lineGap = Number($("#edLineGap") ? $("#edLineGap").value : 0);
    const upper = $("#edUpper") ? $("#edUpper").checked : true;
    const showSubs = $("#edSubs") ? $("#edSubs").checked : true;
    const showHook = $("#edShowHook") ? $("#edShowHook").checked : true;
    const fontKey = $("#edFont") ? $("#edFont").value : "montserrat";

    const words = (($("#edText") ? $("#edText").value : "") || "").trim().split(/\s+/).filter(Boolean).slice(0, 8);
    const line = words.map((w, i) => `<span class="w ${i === 0 ? "hl" : ""}">${esc(upper ? w.toUpperCase() : w)}</span>`).join(" ");

    subView.style.fontFamily = FONT_CSS[fontKey] || "VCMontserrat";
    subView.style.fontSize = size + "px";
    subView.innerHTML = line;
    subView.style.display = showSubs && words.length ? "block" : "none";
    subView.style.lineHeight = (1.15 + lineGap / 90).toFixed(2);
    subView.style.top = "";
    subView.style.bottom = "";
    subView.style.transform = "";
    const stageH = Math.max(1, stage.clientHeight);
    if (position === "top") {
      const y = (zone.top + 120) * k - offset * k;
      subView.style.top = pxClamp(y, 8, stageH - 8) + "px";
    } else if (position === "middle") {
      const y = stageH / 2 - offset * k;
      subView.style.top = pxClamp(y, 8, stageH - 8) + "px";
      subView.style.transform = "translateY(-50%)";
    } else {
      const bandLift = (($("#edLayout") ? $("#edLayout").value : "") === "band") ? 640 * k : 0;
      const fromBottom = Math.max(320, zone.bottom + 60) * k + offset * k + bandLift;
      subView.style.bottom = pxClamp(fromBottom, 8, stageH - 8) + "px";
    }
    subView.style.setProperty("--hl", ACCENT_HEX[chosenAccent] || ACCENT_HEX.yellow);

    const hookText = ($("#edHook") ? $("#edHook").value : "").trim();
    if (hookView) {
      hookView.textContent = upper ? hookText.toUpperCase() : hookText;
      hookView.style.fontFamily = FONT_CSS[fontKey] || "VCMontserrat";
      hookView.style.fontSize = Math.max(9, size * 0.8) + "px";
      const layoutNow = $("#edLayout") ? $("#edLayout").value : "";
      const hookLift = layoutNow === "band_top" ? 640 * k : 0;
      hookView.style.top = Math.max(6, (zone.top + 40) * k + hookLift) + "px";
      hookView.style.display = showHook && showSubs && hookText ? "block" : "none";
      hookView.style.lineHeight = (1.1 + lineGap / 110).toFixed(2);
    }
  };

  ["edText", "edHook", "edFont", "edSize", "edPos", "edOffset", "edLineGap", "edUpper", "edSubs", "edShowHook", "edPlatform", "edLayout", "edHflip", "edTilt"]
    .forEach((id) => {
      const el = $("#" + id);
      if (!el) return;
      el.addEventListener("input", updateEditorPreview);
      el.addEventListener("change", () => { updateEditorPreview(); drawFrame(); });
    });
  const edSplit = $("#edSplit");
  const setEditorSplit = (value) => {
    const min = edSplit ? Number(edSplit.min) / 100 : 0.25;
    editorSplit = Math.min(adhdLimits().max / 100, Math.max(min, Math.round(value * 100) / 100));
    if (edSplit) edSplit.value = String(Math.round(editorSplit * 100));
    const label = $("#edSplitVal");
    if (label) label.textContent = String(Math.round(editorSplit * 100));
  };
  if (edSplit) edSplit.addEventListener("input", () => {
    setEditorSplit(Number(edSplit.value) / 100);
    drawFrame();
  });
  let draggingSplit = false;
  const splitFromEvent = (ev) => {
    if (!$("#edAdhd") || $("#edAdhd").classList.contains("hidden")) return;
    const rect = stage.getBoundingClientRect();
    if (!rect.height) return;
    setEditorSplit((ev.clientY - rect.top) / rect.height);
    drawFrame();
  };
  stage.addEventListener("pointerdown", (ev) => {
    if (!$("#edAdhd") || $("#edAdhd").classList.contains("hidden")) return;
    draggingSplit = true;
    try { stage.setPointerCapture(ev.pointerId); } catch (_) {}
    splitFromEvent(ev);
  });
  stage.addEventListener("pointermove", (ev) => { if (draggingSplit) splitFromEvent(ev); });
  const stopSplitDrag = () => { draggingSplit = false; };
  stage.addEventListener("pointerup", stopSplitDrag);
  stage.addEventListener("pointercancel", stopSplitDrag);
  const edLayoutNow = $("#edLayout");
  if (edLayoutNow) edLayoutNow.addEventListener("change", () => {
    const block = $("#edAdhd");
    if (block) block.classList.toggle("hidden", edLayoutNow.value !== "adhd");
    stage.style.cursor = edLayoutNow.value === "adhd" ? "ns-resize" : "";
    drawFrame();
  });
  ["edTopScale", "edBottomScale", "edBottomSpeed", "edBottomVolume"].forEach((id) => {
    const el = $("#" + id);
    if (!el) return;
    const label = $("#" + id + "Val");
    el.addEventListener("input", () => {
      if (label) label.textContent = id === "edBottomSpeed"
        ? Number(el.value / 100).toFixed(2) : el.value;
    });
  });
  if (stage) {
    stage.style.cursor = ($("#edLayout") && $("#edLayout").value === "adhd") ? "ns-resize" : "";
  }
  api("/api/adhd-bg").then((data) => {
    const select = $("#edAdhdBg");
    if (!select) return;
    const files = (data && data.files) || [];
    const local = editorAdhdBg.startsWith("local:") ? editorAdhdBg : "";
    select.innerHTML = `<option value="">Случайный</option>`
      + (local && project.adhd_bg_url ? `<option value="${local}">Своё видео проекта</option>` : "")
      + files.map((f) => `<option value="${esc(f.name)}">${esc(f.name)}</option>`).join("");
    select.value = files.some((f) => f.name === editorAdhdBg) || local ? editorAdhdBg : "";
    select.addEventListener("change", () => { editorAdhdBg = select.value; });
  }).catch(() => {});
  const adhdUpload = $("#edAdhdUploadBtn");
  if (adhdUpload) adhdUpload.addEventListener("click", () => $("#edAdhdInput").click());
  const adhdInput = $("#edAdhdInput");
  if (adhdInput) adhdInput.addEventListener("change", async (ev) => {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await api(`/api/projects/${project.id}/adhd-bg`, { method: "POST", body: form });
      editorAdhdBg = `local:${res.name}`;
      const select = $("#edAdhdBg");
      if (select) {
        select.insertAdjacentHTML("afterbegin", `<option value="${editorAdhdBg}">Своё видео проекта</option>`);
        select.value = editorAdhdBg;
      }
      toast("Нижнее видео загружено");
    } catch (err) { toast(err.message, "err"); }
  });
  window.addEventListener("resize", () => { drawFrame(); updateEditorPreview(); });
  setTimeout(() => { updateEditorPreview(); seekSource(); }, 60);

  $("#edSize").addEventListener("input", (e) => { $("#edSizeVal").textContent = e.target.value; });
  $("#edFont").addEventListener("change", () => {
    const sample = $("#edFontSample");
    if (sample) sample.style.fontFamily = FONT_CSS[$("#edFont").value] || "VCMontserrat";
  });
  const edFontAdd = $("#edFontAdd");
  if (edFontAdd) edFontAdd.addEventListener("click", () => {
    state.fontTarget = "#edFont";
    $("#fontInput").click();
  });
  $("#edSpeed").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-val]");
    if (!btn) return;
    $$("#edSpeed button").forEach((b) => b.classList.toggle("active", b === btn));
  });
  $("#edOffset").addEventListener("input", (e) => { $("#edOffVal").textContent = e.target.value; });
  $("#edTilt").addEventListener("input", (e) => { $("#edTiltVal").textContent = e.target.value; });
  $("#edSpeedR").addEventListener("input", (e) => {
    $("#edSpeedRVal").textContent = Number(e.target.value).toFixed(2);
  });
  $("#edPitch").addEventListener("input", (e) => {
    $("#edPitchVal").textContent = Number(e.target.value).toFixed(2);
  });
  $("#edLineGap").addEventListener("input", (e) => { $("#edLineGapVal").textContent = e.target.value; });

  const start = $("#edStart"), end = $("#edEnd");
  const startNum = $("#edStartNum"), endNum = $("#edEndNum");
  const video = $("#edVideo");
  if (video) {
    video.volume = 0.5;
    video.addEventListener("loadedmetadata", () => { video.volume = 0.5; });
  }

  const durLabel = $("#edDur");
  const syncNumbers = () => {
    startNum.value = Number(start.value).toFixed(1);
    endNum.value = Number(end.value).toFixed(1);
    if (durLabel) {
      const dur = Math.max(0, Number(end.value) - Number(start.value));
      durLabel.textContent = `Длительность: ${dur.toFixed(1)} с`;
    }
  };

  const words = clip.words || [];
  const snapToWord = (value, edge) => {
    let best = value, bestDist = Infinity;
    for (const w of words) {
      const candidate = edge === "start" ? Number(w.start) : Number(w.end);
      const dist = Math.abs(candidate - value);
      if (dist < bestDist) { bestDist = dist; best = candidate; }
    }
    return bestDist < 2.0 ? best : value;
  };

  $$("#modal .nudge-row button").forEach((btn) => btn.addEventListener("click", () => {
    const [field, kind] = btn.dataset.nudge.split(":");
    const el = field === "start" ? start : end;
    let value = Number(el.value);
    value = kind === "word" ? snapToWord(value, field) : value + Number(kind);
    value = Math.max(0, Math.min(maxT, value));
    el.value = value;
    el.dispatchEvent(new Event("input"));
  }));
  start.addEventListener("input", () => {
    if (Number(start.value) > Number(end.value) - 3) start.value = Math.max(0, Number(end.value) - 3);
    syncNumbers();
    try { video.currentTime = Number(start.value); } catch (_) {}
  });
  end.addEventListener("input", () => {
    if (Number(end.value) < Number(start.value) + 3) end.value = Math.min(maxT, Number(start.value) + 3);
    syncNumbers();
  });
  startNum.addEventListener("change", () => { start.value = startNum.value; start.dispatchEvent(new Event("input")); });
  endNum.addEventListener("change", () => { end.value = endNum.value; end.dispatchEvent(new Event("input")); });

  $("#edSave").addEventListener("click", async () => {
    const btn = $("#edSave");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Рендер…';
    const payload = {
      start: Number(start.value),
      end: Number(end.value),
      hook: $("#edHook").value,
      caption: $("#edCaption").value,
      text: (() => {
        const box = $("#edText");
        const before = (clip.words || []).map((w) => w.word).join(" ");
        return box && box.value.trim() !== before.trim() ? box.value.trim() : undefined;
      })(),
      aspect: $("#edAspect").value,
      mode: $("#edMode").value,
      platform: $("#edPlatform").value,
      layout: $("#edLayout").value,
      split_ratio: editorSplit,
      adhd_bg: editorAdhdBg,
      adhd_top_fill: $("#edTopFill").value,
      adhd_bottom_fill: $("#edBottomFill").value,
      adhd_top_scale: Number($("#edTopScale").value) / 100,
      adhd_bottom_scale: Number($("#edBottomScale").value) / 100,
      adhd_bottom_speed: Number($("#edBottomSpeed").value) / 100,
      adhd_bottom_volume: Number($("#edBottomVolume").value),
      subtitles: $("#edSubs").checked,
      uppercase: $("#edUpper").checked,
      show_hook: $("#edShowHook").checked,
      accent: chosenAccent,
      sub_font: $("#edFont").value,
      sub_size: Number($("#edSize").value),
      sub_position: $("#edPos").value,
      sub_offset: Number($("#edOffset").value),
      line_gap: Number($("#edLineGap").value),
      sub_speed: ($("#edSpeed .active") || {}).dataset?.val || "calm",
      hflip: $("#edHflip").checked,
      jump_cuts: $("#edJumpCuts").checked,
      cut_zoom: $("#edCutZoom").checked,
      tilt: Number($("#edTilt").value),
      speed: Number($("#edSpeedR").value),
      pitch: Number($("#edPitch").value),
      external_audio: $("#edDub") ? $("#edDub").checked : undefined,
      audio_offset: $("#edDubOffset") ? Number($("#edDubOffset").value) : undefined
    };
    try {
      await api(`/api/clips/${clip.id}/rerender`, { method: "POST", body: JSON.stringify(payload) });
      closeModal();
      toast("Клип перерендеривается");
      await loadDetail(true);
      schedulePoll(900);
    } catch (e) {
      toast(e.message, "err");
      btn.disabled = false;
      btn.textContent = "Перерендерить";
    }
  });
}

function closeModal() {
  $("#modal").classList.add("hidden");
  $("#modal").innerHTML = "";
}

$("#modal").addEventListener("click", (e) => {
  if (!e.target.closest("[data-close]")) return;
  if (state.probeOpen) closeProbe();
  else if (state.tmplPid) closeTemplate();
  else closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || $("#modal").classList.contains("hidden")) return;
  if (state.probeOpen) closeProbe();
  else if (state.tmplPid) closeTemplate();
  else closeModal();
});

/* ---------------- Boot ---------------- */

$("#newBtn").addEventListener("click", () => {
  state.current = null;
  state.detail = null;
  state.mainKey = "";
  state.homeView = "";
  clearTimeout(state.pollTimer);
  history.replaceState(null, "", location.pathname);
  renderMain(true);
  renderSidebar();
  const input = $("#urlInput");
  if (input) input.focus();
});

$("#streamBtn")?.addEventListener("click", () => {
  state.current = null;
  state.detail = null;
  state.homeView = "streams";
  clearTimeout(state.pollTimer);
  history.replaceState(null, "", location.pathname);
  renderMain(true);
});

$("#main").addEventListener("click", async (e) => {
  if (e.target.closest("#streamStartBtn")) {
    const input = $("#streamInput");
    const url = (input && input.value || "").trim();
    if (!url) { toast("Вставьте ссылку на эфир", "err"); return; }
    try {
      const project = await api("/api/streams", { method: "POST", body: JSON.stringify({ url, options: heroOptions() }) });
      await loadProjects();
      openProject(project.id);
    } catch (err) { toast(err.message, "err"); }
    return;
  }
});

// Список проектов обновляем сам: видно стадию, процент и полоску прогресса,
// даже если проект запущен не из этого окна.
setInterval(() => {
  if (!state.current) loadProjects();
}, 2500);

$("#adhdBgInput").addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  if (!/\.(mp4|webm|mov|mkv|m4v)$/i.test(file.name)) {
    toast("Нужен видеофайл: mp4, webm, mov, mkv", "err");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await api("/api/adhd-bg", { method: "POST", body: form });
    state.opts.bgVideo = res.name;
    state.opts.adhdBg = res.name;
    await loadAdhdBgs();
    const select = $("#bgSelect");
    if (select) select.value = res.name;
    toast("Фон добавлен: " + res.name);
  } catch (err) {
    toast("Фон не принят: " + err.message, "err");
  }
});

$("#musicInput").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  if (!/\.(mp3|m4a|aac|wav|ogg|flac|opus)$/i.test(file.name)) {
    toast("Нужен аудиофайл: mp3, m4a, wav, ogg", "err");
    return;
  }
  state.pendingMusic = file;
  const chip = $("#pendingMusic");
  if (chip) {
    chip.textContent = `${file.name} · убрать`;
    chip.classList.remove("hidden");
    chip.onclick = () => { state.pendingMusic = null; chip.classList.add("hidden"); };
  }
  toast("Музыка приложена — подмешается тихо под голос");
});

$("#subsInput").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  if (!/\.(srt|ass|ssa|vtt)$/i.test(file.name)) {
    toast("Нужен файл .srt, .ass или .vtt", "err");
    return;
  }
  if (state.subsToTemplate && state.tmplPid) {
    // В окне настройки свои субтитры сразу уходят в проект: они важнее Whisper.
    state.subsToTemplate = false;
    const form = new FormData();
    form.append("file", file);
    api(`/api/projects/${state.tmplPid}/subtitles`, { method: "POST", body: form })
      .then((res) => {
        if (state.tmplDetail && state.tmplDetail.project) {
          state.tmplDetail.project.meta = {
            ...(state.tmplDetail.project.meta || {}),
            subtitles_attached: res.segments || 1
          };
          renderDub(state.tmplDetail.project);
        }
        toast(`Субтитры подключены: ${file.name}`);
      })
      .catch((err) => toast("Субтитры не приняты: " + err.message, "err"));
    return;
  }
  state.pendingSubs = file;
  const chip = $("#pendingSubs");
  if (chip) {
    chip.textContent = `${file.name} · убрать`;
    chip.classList.remove("hidden");
  }
  toast("Субтитры приложены — текст возьмётся из файла");
});

$("#dubInput").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  if (!/\.(mka|mkv|mp4|m4v|mov|webm|mp3|m4a|aac|wav|ogg|flac|opus|ac3|eac3|dts|ts)$/i.test(file.name)) {
    toast("Нужен аудиофайл или контейнер: mka, mkv, mp4, mp3, aac…", "err");
    return;
  }
  uploadDub(file);
});

$("#fileInput").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  uploadFile(file);
});

$("#fontInput").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  uploadFont(file);
});

document.addEventListener("click", (e) => {
  const link = e.target.closest("a[data-external]");
  if (!link) return;
  e.preventDefault();
  const url = link.getAttribute("data-external") || "";
  const api = window.pywebview && window.pywebview.api;
  if (api && api.open_url) {
    api.open_url(url).catch(() => { try { window.open(url, "_blank", "noopener"); } catch (_) {} });
  } else {
    try { window.open(url, "_blank", "noopener"); } catch (_) {}
  }
});

async function checkSystem() {
  try {
    const data = await api("/api/system");
    state.system = data;
    renderSystem(data);
  } catch (_) { /* панель датчиков не критична */ }
}

function setMetric(barId, valueId, value) {
  const bar = $(barId);
  const label = $(valueId);
  if (!bar || !label) return;
  const num = Number(value);
  if (value == null || !Number.isFinite(num)) {
    bar.style.width = "0%";
    label.textContent = "—";
    return;
  }
  const pct = Math.max(0, Math.min(100, num));
  bar.style.width = pct + "%";
  label.textContent = Math.round(pct) + "%";
}

function renderSystem(data) {
  const box = $("#sysmon");
  if (!box) return;
  box.hidden = false;
  setMetric("#cpuBar", "#cpuVal", data?.cpu?.percent);
  setMetric("#gpuBar", "#gpuVal", data?.gpu?.util);
  setMetric("#encBar", "#encVal", data?.gpu?.encoder);
  const cpuLabel = $("#cpuVal");
  if (cpuLabel) {
    cpuLabel.title = data?.memory ? `RAM ${Math.round(data.memory.percent)}% · ${data.memory.used_gb} из ${data.memory.total_gb} ГБ` : "";
  }
  const temp = data?.gpu?.temp;
  const tempEl = $("#gpuTemp");
  if (tempEl) {
    tempEl.textContent = temp == null ? "—" : `${Math.round(temp)}°C`;
    tempEl.classList.toggle("hot", temp != null && temp >= 80);
    tempEl.title = temp == null ? "Температура GPU недоступна" : "Температура GPU";
  }
  const nameEl = $("#gpuName");
  if (nameEl) {
    nameEl.textContent = data?.gpu?.name || "GPU не найден";
    nameEl.title = data?.gpu?.name || "";
  }
  const diskEl = $("#sysDisk");
  if (diskEl) {
    const disk = data?.disk;
    diskEl.textContent = disk ? `${Math.round(disk.free_gb)} ГБ свободно` : "—";
    diskEl.title = disk ? `Проекты: ${disk.path} · всего ${Math.round(disk.total_gb)} ГБ` : "";
  }
}

async function checkHealth() {
  try {
    const h = await api("/api/health");
    state.health = h;
    const el = $("#health");
    el.classList.toggle("ok", !!h.ok);
    el.classList.toggle("bad", !h.ok);
    $("#healthText").textContent = h.ok
      ? (h.model === false
          ? "Готов · модель скачается при первом видео"
          : `Движок готов · ffmpeg${h.whisper ? " · Whisper" : " · без Whisper"}`)
      : "ffmpeg не найден";
  } catch (_) {
    $("#health").classList.add("bad");
    $("#healthText").textContent = "Сервер недоступен";
  }
}

async function checkUpdates() {
  try {
    const res = await fetch("/api/update");
    if (!res.ok) return;
    renderUpdate(await res.json());
  } catch (_) { /* офлайн — просто не показываем */ }
}

function renderUpdate(data) {
  const card = $("#updateCard");
  if (!card) return;
  const dismissed = localStorage.getItem("vcUpdateDismissed");
  if (!data || !data.available || !data.latest || dismissed === data.latest) {
    card.hidden = true;
    return;
  }
  const url = data.url || "";
  if (!url) {
    card.hidden = true;
    return;
  }
  card.href = url;
  card.setAttribute("data-external", url);
  $("#updateTitle").textContent = `Доступна версия ${data.latest}`;
  const note = String(data.notes || "").split("\n").map((l) => l.replace(/^#+\s*/, "").trim()).find(Boolean);
  $("#updateSub").textContent = note ? note.slice(0, 70) : "Скачать с GitHub";
  card.hidden = false;
  if (localStorage.getItem("vcUpdateSeen") !== data.latest) {
    localStorage.setItem("vcUpdateSeen", data.latest);
    toast(`Вышла новая версия ${data.latest} — скачать на GitHub`);
  }
}

function bindUpdateCard() {
  const card = $("#updateCard");
  if (!card) return;
  const hide = $("#updateHide");
  if (hide) {
    hide.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const title = $("#updateTitle").textContent || "";
      const version = title.replace(/^[^\d]*/, "").trim();
      if (version) localStorage.setItem("vcUpdateDismissed", version);
      card.hidden = true;
    });
  }
}

window.addEventListener("hashchange", () => {
  const id = location.hash.replace("#", "");
  if (id && id !== state.current) {
    openProject(id);
  } else if (!id && state.current) {
    state.current = null;
    state.detail = null;
    state.mainKey = "";
    clearTimeout(state.pollTimer);
    renderMain(true);
    renderSidebar();
  }
});

(async function boot() {
  bindUpdateCard();
  checkUpdates();
  setInterval(checkUpdates, 30 * 60 * 1000);
  await checkHealth();
  checkSystem();
  await loadFontCatalog();
  await loadProjects();
  const hash = location.hash.replace("#", "");
  if (hash && state.projects.some((p) => p.id === hash)) {
    openProject(hash);
  } else {
    renderMain(true);
  }
  setInterval(checkHealth, 20000);
  setInterval(() => { if (!document.hidden) checkSystem(); }, 3000);
})();
