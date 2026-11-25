/* Мастер настройки: источник → кадр → субтитры → количество. */
(() => {
  const UI_KEY = "vertcut.interface";
  const MODE_WIZARD = "wizard";
  const MODE_CLASSIC = "classic";
  const wizard = {
    pid: null,
    step: 1,
    detail: null,
    timer: null,
    opts: {},
    frameT: -1,
    frameUrl: "",
    ready: false,
    picked: null
  };

  const MOODS = [
    ["funny", "весёлое"], ["sad", "грустное"], ["drama", "драма"],
    ["shock", "шок"], ["insight", "мысль"], ["wholesome", "тёплое"],
    ["intense", "жёсткое"]
  ];
  const PICKER_OPTIONS = [
    ["local", "Локально — быстро и бесплатно"],
    ["auto", "Авто: OpenRouter → DeepSeek → Gemini"],
    ["openrouter", "OpenRouter (DeepSeek)"],
    ["deepseek", "DeepSeek"],
    ["gemini", "Gemini"]
  ];

  const uiMode = () => (localStorage.getItem(UI_KEY) || MODE_WIZARD);
  const setUiMode = (mode) => localStorage.setItem(UI_KEY, mode);
  const usesWizard = () => uiMode() === MODE_WIZARD;

  const defaults = () => ({
    aspect: "9:16", mode: "auto", platform: "universal", layout: "",
    split_ratio: 0.5, bg_video: "random",
    subtitles: true, uppercase: true, show_hook: true,
    sub_font: "montserrat", sub_size: 118, sub_position: "bottom",
    sub_offset: 0, sub_speed: "calm", line_gap: 0, accent: "yellow",
    export_subs: false, keep_fps: true,
    look: "none", vignette: false, grain: false, zoom: 100, bitrate: 0,
    music_volume: 8, hflip: false, tilt: 0, speed: 1, pitch: 1,
    jump_cuts: false, cut_zoom: false,
    count: 10, min_dur: 15, max_dur: 60, target_dur: 32,
    select: "smart", export_order: "chrono",
    picker: "local", mood_filter: [], type_filter: [], min_score: 0,
    audio_track: -1, audio_lang: "auto", subtitle_track: -1, subtitle_source: "auto",
    asr_profile: "", whisper_model: "",
    external_audio: false, external_audio_track: -1, audio_offset: 0,
    cookies_browser: "", language: "auto", max_height: 1080, segments: false,
    force_hd: false
  });

  function mergeOptions(project) {
    const o = project.options || {};
    wizard.opts = {
      ...defaults(),
      ...o,
      count: o.count == null ? 10 : o.count,
      audio_track: o.audio_track == null ? -1 : o.audio_track,
      audio_lang: o.audio_lang || "auto",
      asr_profile: o.asr_profile || "",
      whisper_model: o.whisper_model || "",
      subtitle_track: o.subtitle_track == null ? -1 : o.subtitle_track
    };
  }

  function closeWizard() {
    clearTimeout(wizard.timer);
    wizard.pid = null;
    wizard.detail = null;
    wizard.ready = false;
    $("#modal").classList.add("hidden");
    $("#modal").innerHTML = "";
  }

  function stepper() {
    const names = ["Источник", "Кадр", "Субтитры", "Нарезка"];
    return `<div class="wz-steps">${names.map((name, i) =>
      `<span class="wz-step ${wizard.step === i + 1 ? "active" : ""} ${wizard.step > i + 1 ? "done" : ""}">${i + 1}. ${name}</span>`
    ).join("")}</div>`;
  }

  function openWizard(pid) {
    wizard.pid = pid;
    wizard.step = 1;
    wizard.frameT = -1;
    wizard.frameUrl = "";
    wizard.lastBox = null;
    wizard.picked = null;
    $("#modal").innerHTML = `
      <div class="modal-backdrop" data-wz-close></div>
      <div class="modal-panel wz-panel">
        <div class="modal-head">
          <h3>Настройка нарезки</h3>
          <button class="icon-btn" data-wz-close>${ICONS.close}</button>
        </div>
        <div id="wzSteps">${stepper()}</div>
        <div id="wzBody" class="wz-body"><span class="spinner"></span></div>
        <div class="modal-foot">
          <button class="btn-ghost" id="wzBack" disabled>Назад</button>
          <button class="btn-primary" id="wzNext">Далее</button>
        </div>
      </div>`;
    $("#modal").classList.remove("hidden");
    $$("[data-wz-close]").forEach((b) => b.addEventListener("click", closeWizard));
    $("#wzBack").addEventListener("click", () => { if (wizard.step > 1) { wizard.step -= 1; render(); } });
    $("#wzNext").addEventListener("click", next);
    poll();
  }

  function poll() {
    clearTimeout(wizard.timer);
    if (!wizard.pid) return;
    api(`/api/projects/${wizard.pid}`).then((detail) => {
      wizard.detail = detail;
      const project = detail.project;
      if (project.status === "draft") {
        if ((project.url || "").startsWith("http")) {
          api(`/api/projects/${project.id}/retry`, {
            method: "POST",
            body: JSON.stringify({ force_hd: false, prepare_only: true, options: wizard.opts })
          }).then(() => { wizard.timer = setTimeout(poll, 900); });
          render();
          return;
        }
        render();
        return;
      }
      if (["queued", "preparing", "running"].includes(project.status)) {
        render();
        wizard.timer = setTimeout(poll, 1200);
        return;
      }
      if (project.status === "review") {
        if (!wizard.ready) mergeOptions(project);
        else if (project.dub && project.options && project.options.external_audio) {
          // Дубляж подключили уже после открытия мастера — включаем замену звука.
          wizard.opts.external_audio = true;
        }
        wizard.ready = true;
        render();
        return;
      }
      render();
    }).catch((err) => {
      const body = $("#wzBody");
      if (body) body.innerHTML = `<div class="tmpl-error">${esc(err.message)}</div>`;
    });
  }

  function render() {
    const steps = $("#wzSteps");
    if (steps) steps.innerHTML = stepper();
    const body = $("#wzBody");
    if (!body) return;
    const project = wizard.detail && wizard.detail.project;
    const back = $("#wzBack");
    const next = $("#wzNext");
    if (back) back.disabled = wizard.step <= 1;
    if (next) {
      next.disabled = wizard.step === 1 && !(project && project.status === "review");
      next.textContent = wizard.step === 4 ? "Сделать нарезки" : "Далее";
    }
    if (!project) { body.innerHTML = `<span class="spinner"></span>`; return; }
    if (wizard.step === 1) body.innerHTML = stepSource(project);
    if (wizard.step === 2) { body.innerHTML = stepFrame(project); bindFrame(); loadFrame(); }
    if (wizard.step === 3) { body.innerHTML = stepSubs(project); bindSubs(); }
    if (wizard.step === 4) { body.innerHTML = stepCount(project); bindCount(); }
    bindSource(project);
  }

  const progress = (project) => `
    <div class="wz-progress">
      <div class="spinner"></div>
      <div><b>${esc(project.stage || "Подготовка")}</b><br><span>${Math.round(project.progress || 0)}%</span></div>
      <div class="bar"><i style="width:${Math.max(2, project.progress || 0)}%"></i></div>
    </div>`;

  function audioPickHint(meta) {
    const pick = meta && meta.audio_pick;
    if (!pick || !pick.requested || pick.requested === "auto") return "";
    if (pick.reason === "fallback") {
      return `<div class="warn-box"><strong>Русская дорожка не найдена.</strong> Взята ${esc(pick.label || "другая дорожка")} — распознавание и звук используют её.</div>`;
    }
    if (pick.reason === "language") {
      return `<div class="opt-hint">Выбрана ${esc(pick.label || "русская дорожка")}.</div>`;
    }
    return "";
  }

  function stepSource(project) {
    if (["queued", "preparing", "running"].includes(project.status)) return progress(project);
    const meta = project.meta || {};
    const audio = project.audio_tracks || meta.audio_tracks || [];
    const subs = project.subtitle_tracks || meta.subtitle_tracks || [];
    const audioRows = audio.length ? audio.map((t, i) => {
      const value = Number(t.index == null ? i : t.index);
      return `<label class="wz-row"><input type="radio" name="wzAudio" value="${value}" ${Number(wizard.opts.audio_track) === value || (Number(wizard.opts.audio_track) < 0 && t.default) ? "checked" : ""}/> <b>${esc(t.language || "дорожка " + (i + 1))}</b> <span>${esc(t.codec || "")}</span></label>`;
    }).join("") : `<div class="opt-hint">Дополнительных аудиодорожек нет.</div>`;
    const subRows = subs.length ? subs.map((t) => `
      <label class="wz-row"><input type="radio" name="wzSub" value="${Number(t.index)}" ${Number(wizard.opts.subtitle_track) === Number(t.index) ? "checked" : ""}/> <b>${esc(t.language || "без языка")}</b> <span>${esc(t.codec || "")}</span></label>`).join("") : `<div class="opt-hint">Вшитых субтитров нет.</div>`;
    const dub = project.dub ? `<span class="wz-ok">подключён: ${esc(project.dub.name || "файл")}</span>` : `<span class="muted">не подключён</span>`;
    const draftLocal = project.status === "draft" && (project.url || "").startsWith("local:");
    return `
      <div class="wz-source">
        <div class="wz-info"><b>${esc(project.title || project.url)}</b>
          <span>${project.duration ? fmtDur(project.duration) + " · " : ""}${esc(meta.vcodec || "")} ${meta.height ? meta.height + "p" : ""}</span>
        </div>
        ${meta.asr_warning ? `<div class="warn-box"><strong>Проверьте язык распознавания.</strong> ${esc(meta.asr_warning)}</div>` : ""}
        ${draftLocal ? `<div class="wz-block"><b>Файл ещё не выбран</b><div class="wz-actions">
          <button class="btn-ghost" id="wzUpload">Загрузить файлом</button>
          <button class="btn-ghost hidden" id="wzNative">Выбрать файл на диске</button></div>
          <div id="wzPicked"></div></div>` : ""}
        <div class="wz-block"><b>Аудиодорожки</b>${audioRows}<label class="mini-field"><span>Язык звука при скачивании</span><select id="wzAudioLang"><option value="auto" ${wizard.opts.audio_lang === "auto" ? "selected" : ""}>Как в источнике</option><option value="ru" ${wizard.opts.audio_lang === "ru" ? "selected" : ""}>Русский</option><option value="uk" ${wizard.opts.audio_lang === "uk" ? "selected" : ""}>Украинский</option><option value="en" ${wizard.opts.audio_lang === "en" ? "selected" : ""}>Английский</option><option value="de" ${wizard.opts.audio_lang === "de" ? "selected" : ""}>Немецкий</option><option value="es" ${wizard.opts.audio_lang === "es" ? "selected" : ""}>Испанский</option></select></label><div class="opt-hint">Если у источника несколько дорожек, возьмём дорожку этого языка. Ручной выбор выше сильнее. Уже скачанный файл не перекачивается.</div>${audioPickHint(meta)}</div>
        <div class="wz-block"><b>Субтитры внутри файла</b>${subRows}
          <label class="toggle"><input type="checkbox" id="wzForceAsr" ${wizard.opts.subtitle_source === "whisper" ? "checked" : ""}/><span class="track"></span><span>Распознать заново (Whisper)</span></label>
        </div>
        <div class="wz-block"><b>Дубляж</b> ${dub}
          <label class="toggle"><input type="checkbox" id="wzUseDub" ${wizard.opts.external_audio ? "checked" : ""} ${project.dub ? "" : "disabled"}/><span class="track"></span><span>Заменить звук дубляжом</span></label>
          <div class="wz-actions"><button class="link-btn" id="wzDub">подключить дубляж</button>
          <button class="link-btn" id="wzSubs">приложить субтитры</button>
          <button class="link-btn" id="wzMusic">добавить музыку</button></div>
        </div>
      </div>`;
  }

  function bindSource(project) {
    const audio = $("#wzBody");
    if (!audio) return;
    $$('input[name="wzAudio"]', audio).forEach((el) => el.addEventListener("change", () => {
      wizard.opts.audio_track = Number(el.value);
    }));
    $$('input[name="wzSub"]', audio).forEach((el) => el.addEventListener("change", () => {
      wizard.opts.subtitle_track = Number(el.value);
    }));
    const audioLang = $("#wzAudioLang");
    if (audioLang) audioLang.addEventListener("change", () => {
      wizard.opts.audio_lang = audioLang.value;
    });
    const asr = $("#wzForceAsr");
    if (asr) asr.addEventListener("change", () => {
      wizard.opts.subtitle_source = asr.checked ? "whisper" : "auto";
    });
    const upload = $("#wzUpload");
    if (upload) upload.addEventListener("click", () => $("#wzFileInput").click());
    const native = $("#wzNative");
    if (native) native.addEventListener("click", pickNative);
    const dub = $("#wzDub");
    if (dub) dub.addEventListener("click", () => $("#wzDubInput").click());
    const useDub = $("#wzUseDub");
    if (useDub) useDub.addEventListener("change", () => {
      wizard.opts.external_audio = useDub.checked;
    });
    const subs = $("#wzSubs");
    if (subs) subs.addEventListener("click", () => $("#wzSubsInput").click());
    const music = $("#wzMusic");
    if (music) music.addEventListener("click", () => $("#wzMusicInput").click());
    if (native && window.pywebview && window.pywebview.api && window.pywebview.api.pick_source) {
      native.classList.remove("hidden");
    }
  }

  async function pickNative() {
    try {
      const res = await window.pywebview.api.pick_source();
      if (!res || !res.ok) { if (res && !res.cancelled) toast(res.error || "Не удалось выбрать файл", "err"); return; }
      wizard.pickedFile = res;
      const group = res.group || [];
      const options = (kind, label) => {
        const items = group.filter((g) => g.kind === kind);
        if (!items.length) return `<div class="opt-hint">${label}: рядом ничего не найдено</div>`;
        return `<label class="mini-field"><span>${label}</span><select id="wzPick_${kind}">
          <option value="">не подключать</option>
          ${items.map((g) => `<option value="${esc(g.path)}">${esc(g.name)}</option>`).join("")}
        </select></label>`;
      };
      const box = $("#wzPicked");
      if (box) {
        box.innerHTML = `<div class="wz-block"><b>Найдено рядом с «${esc(res.name)}»</b>
          ${options("subtitles", "Субтитры")}${options("audio", "Звук/дубляж")}
          <div class="wz-actions"><button class="btn-primary" id="wzAttach">Подключить</button></div></div>`;
        $("#wzAttach").addEventListener("click", async () => {
          const subs = ($("#wzPick_subtitles") || {}).value || "";
          const dub = ($("#wzPick_audio") || {}).value || "";
          const attached = await window.pywebview.api.attach_source(wizard.pid, res.video, subs, dub, "");
          if (!attached || !attached.ok) { toast((attached && attached.error) || "Не удалось подключить", "err"); return; }
          toast("Файл и дорожки подключены");
          poll();
        });
      }
    } catch (err) { toast(err.message || "Не удалось выбрать файл", "err"); }
  }

  function frameCards() {
    const opt = (group, val, label, extra = "") =>
      `<button type="button" class="wz-card ${String(wizard.opts[group]) === String(val) ? "active" : ""}" data-wz-group="${group}" data-wz-val="${val}">${label}${extra}</button>`;
    return {
      aspect: ["9:16", "1:1", "16:9"].map((a) => opt("aspect", a, ASPECT_META[a].short)).join(""),
      platform: PLATFORM_OPTIONS.map(([k, v]) => opt("platform", k, v)).join(""),
      mode: [["auto", "Умный кроп"], ["blur", "Размытый фон"], ["crop", "По центру"]].map(([k, v]) => opt("mode", k, v)).join("")
    };
  }

  function stepFrame() {
    const c = frameCards();
    return `
      <div class="wz-frame-layout">
        <div class="wz-preview" id="wzPreview">
          <div class="wz-blur-bg" id="wzBlurBg"></div>
          <img id="wzFrame" alt="кадр из видео">
          <div class="wz-zones" id="wzZones"></div>
          <div class="wz-caption" id="wzCap">ПРИМЕР СУБТИТРОВ</div>
          <button type="button" class="wz-reroll" id="wzReroll">Другой кадр</button>
        </div>
        <div class="wz-controls">
          <div class="wz-block"><b>Формат</b><div class="wz-cards">${c.aspect}</div></div>
          <div class="wz-block"><b>Площадка</b><div class="wz-cards">${c.platform}</div></div>
          <div class="wz-block"><b>Кадр</b><div class="wz-cards">${c.mode}</div></div>
          <div class="wz-block"><b>Пресет стрима</b>
            <select id="wzLayout">
              <option value="">Выключен</option>
              <option value="band">Лицо крупно снизу</option>
              <option value="band_top">Лицо крупно сверху</option>
              <option value="adhd">Сплит-скрин</option>
            </select>
          </div>
          <div class="wz-block"><b>Индивидуализация</b>
            <label class="toggle"><input type="checkbox" id="wzHflip" ${wizard.opts.hflip ? "checked" : ""}/><span class="track"></span><span>Зеркало</span></label>
            <label class="toggle"><input type="checkbox" id="wzCuts" ${wizard.opts.jump_cuts ? "checked" : ""}/><span class="track"></span><span>Склейки пауз</span></label>
            <label class="toggle"><input type="checkbox" id="wzCutZoom" ${wizard.opts.cut_zoom ? "checked" : ""}/><span class="track"></span><span>Зум на склейках</span></label>
            <label class="mini-field"><span>Наклон <b id="wzTiltVal">${wizard.opts.tilt}</b>°</span><input type="range" id="wzTilt" min="0" max="3" step="0.5" value="${wizard.opts.tilt}"/></label>
            <label class="mini-field"><span>Скорость <b id="wzSpeedVal">${Number(wizard.opts.speed).toFixed(2)}</b>×</span><input type="range" id="wzSpeed" min="1" max="1.1" step="0.01" value="${wizard.opts.speed}"/></label>
            <label class="mini-field"><span>Питч <b id="wzPitchVal">${Number(wizard.opts.pitch).toFixed(2)}</b>×</span><input type="range" id="wzPitch" min="0.95" max="1.05" step="0.01" value="${wizard.opts.pitch}"/></label>
            <label class="mini-field"><span>Цвет</span><select id="wzLook">
              <option value="none">Без обработки</option><option value="warm">Тёплый</option>
              <option value="cool">Холодный</option><option value="contrast">Контрастный</option>
              <option value="cinematic">Кинематографичный</option><option value="soft">Мягкий</option>
            </select></label>
          </div>
        </div>
      </div>`;
  }

  function bindFrame() {
    $("#wzLayout").value = wizard.opts.layout || "";
    $("#wzLayout").addEventListener("change", (e) => { wizard.opts.layout = e.target.value; });
    $("#wzLook").value = wizard.opts.look || "none";
    $("#wzLook").addEventListener("change", (e) => { wizard.opts.look = e.target.value; applyFrameStyle(); });
    $("#wzHflip").addEventListener("change", (e) => { wizard.opts.hflip = e.target.checked; applyFrameStyle(); });
    $("#wzCuts").addEventListener("change", (e) => { wizard.opts.jump_cuts = e.target.checked; });
    $("#wzCutZoom").addEventListener("change", (e) => { wizard.opts.cut_zoom = e.target.checked; });
    $("#wzTilt").addEventListener("input", (e) => { wizard.opts.tilt = Number(e.target.value); $("#wzTiltVal").textContent = e.target.value; applyFrameStyle(); });
    $("#wzSpeed").addEventListener("input", (e) => { wizard.opts.speed = Number(e.target.value); $("#wzSpeedVal").textContent = Number(e.target.value).toFixed(2); });
    $("#wzPitch").addEventListener("input", (e) => { wizard.opts.pitch = Number(e.target.value); $("#wzPitchVal").textContent = Number(e.target.value).toFixed(2); });
    $$("#wzBody .wz-card").forEach((btn) => btn.addEventListener("click", () => {
      const group = btn.dataset.wzGroup;
      wizard.opts[group] = btn.dataset.wzVal;
      $$(`#wzBody .wz-card[data-wz-group="${group}"]`).forEach((b) => b.classList.toggle("active", b === btn));
      if (group === "aspect") loadFrame();
      else applyPreviewLayout(wizard.lastBox);
    }));
    $("#wzReroll").addEventListener("click", () => { wizard.frameT = -1; loadFrame(); });
  }

  function applyFrameStyle() {
    const cap = $("#wzCap");
    if (!cap) return;
    const transforms = [];
    if (Number(wizard.opts.tilt) > 0) transforms.push("scale(1.04)", `rotate(${wizard.opts.tilt}deg)`);
    if (wizard.opts.hflip) transforms.push("scaleX(-1)");
    cap.style.transform = transforms.join(" ");
    const looks = { warm: "saturate(1.1)", cool: "saturate(1.05) hue-rotate(-8deg)",
                    contrast: "contrast(1.12) saturate(1.1)", cinematic: "contrast(1.08) saturate(0.92)",
                    soft: "contrast(0.96) brightness(1.02)" };
    cap.style.filter = looks[wizard.opts.look] || "";
  }

  function loadFrame() {
    const img = $("#wzFrame");
    if (!img || !wizard.pid) return;
    const meta = ASPECT_META[wizard.opts.aspect] || ASPECT_META["9:16"];
    const preview = $("#wzPreview");
    if (preview) preview.style.aspectRatio = `${meta.w} / ${meta.h}`;
    const t = wizard.frameT < 0 ? "" : `&t=${wizard.frameT}`;
    api(`/api/projects/${wizard.pid}/frame-info?aspect=${encodeURIComponent(wizard.opts.aspect)}${t}`)
      .then((info) => {
        wizard.frameT = info.time;
        wizard.lastBox = info.box;
        wizard.frameUrl = `/api/projects/${wizard.pid}/frame.jpg?t=${info.time}&w=1280`;
        img.onload = () => { applyPreviewLayout(info.box); updateCaption(); };
        img.src = wizard.frameUrl;
      }).catch(() => {});
  }

  function applyPreviewLayout(box) {
    const preview = $("#wzPreview");
    const img = $("#wzFrame");
    if (!preview || !img) return;
    const meta = ASPECT_META[wizard.opts.aspect] || ASPECT_META["9:16"];
    preview.style.aspectRatio = `${meta.w} / ${meta.h}`;
    const W = preview.clientWidth || 360;
    const zones = $("#wzZones");
    if (zones) {
      const zone = PLATFORM_ZONES[wizard.opts.platform] || PLATFORM_ZONES.universal;
      zones.innerHTML = wizard.opts.platform === "none" ? "" :
        `<i class="wz-zone top" style="height:${(zone.top / 1920) * 100}%"></i>` +
        `<i class="wz-zone bottom" style="height:${(zone.bottom / 1920) * 100}%"></i>`;
    }
    const blur = $("#wzBlurBg");
    if (wizard.opts.mode === "blur") {
      preview.classList.add("is-blur");
      if (blur) {
        blur.style.display = "block";
        blur.style.backgroundImage = wizard.frameUrl ? `url("${wizard.frameUrl}")` : "";
      }
      img.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;object-fit:contain;";
      return;
    }
    if (blur) blur.style.display = "none";
    preview.classList.remove("is-blur");
    if (!box) {
      img.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover;";
      return;
    }
    let bx = Number(box.x), by = Number(box.y);
    if (wizard.opts.mode === "crop") {
      bx = (box.source_w - box.crop_w) / 2;
      by = (box.source_h - box.crop_h) / 2;
    }
    const scale = W / Math.max(1, box.crop_w);
    img.style.cssText = `position:absolute;left:${-bx * scale}px;top:${-by * scale}px;` +
      `width:${box.source_w * scale}px;height:${box.source_h * scale}px;object-fit:fill;`;
  }

  function stepSubs() {
    return `
      <div class="wz-frame-layout">
        <div class="wz-preview" id="wzPreview">
          <div class="wz-blur-bg" id="wzBlurBg"></div>
          <img id="wzFrame" alt="кадр">
          <div class="wz-zones" id="wzZones"></div>
          <div class="wz-caption" id="wzCap">ПРИМЕР СУБТИТРОВ</div>
          <button type="button" class="wz-reroll" id="wzReroll">Другой кадр</button></div>
        <div class="wz-controls">
          <div class="wz-block">
            <label class="toggle"><input type="checkbox" id="wzSubs" ${wizard.opts.subtitles ? "checked" : ""}/><span class="track"></span><span>Субтитры</span></label>
            <label class="toggle"><input type="checkbox" id="wzUpper" ${wizard.opts.uppercase ? "checked" : ""}/><span class="track"></span><span>КАПСОМ</span></label>
            <label class="toggle"><input type="checkbox" id="wzHook" ${wizard.opts.show_hook ? "checked" : ""}/><span class="track"></span><span>Хук сверху</span></label>
          </div>
          <div class="wz-block"><b>Шрифт и цвет</b>
            <label class="mini-field"><span>Шрифт</span><select id="wzFont">${fontOptionsHTML(wizard.opts.sub_font)}</select></label>
            <div class="swatches" id="wzAccents">${swatchesHTML(wizard.opts.accent)}</div>
          </div>
          <div class="wz-block">
            <label class="mini-field"><span>Размер <b id="wzSizeVal">${wizard.opts.sub_size}</b></span><input type="range" id="wzSize" min="70" max="180" step="2" value="${wizard.opts.sub_size}"/></label>
            <label class="mini-field"><span>Положение</span><select id="wzPos">${SUB_POSITIONS.map(([k, l]) => `<option value="${k}" ${wizard.opts.sub_position === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
            <label class="mini-field"><span>Сдвиг по вертикали <b id="wzOffVal">${wizard.opts.sub_offset}</b></span><input type="range" id="wzOff" min="${SUB_OFFSET_MIN}" max="${SUB_OFFSET_MAX}" step="10" value="${wizard.opts.sub_offset}"/></label>
            <label class="mini-field"><span>Межстрочный интервал <b id="wzGapVal">${wizard.opts.line_gap}</b></span><input type="range" id="wzGap" min="0" max="80" step="2" value="${wizard.opts.line_gap}"/></label>
            <label class="mini-field"><span>Темп</span><select id="wzSpeedSel">${SUB_SPEEDS.map(([k, l]) => `<option value="${k}" ${wizard.opts.sub_speed === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
            <label class="toggle"><input type="checkbox" id="wzExport" ${wizard.opts.export_subs ? "checked" : ""}/><span class="track"></span><span>Файлы субтитров отдельно</span></label>
          </div>
        </div>
      </div>`;
  }

  function bindSubs() {
    wizard.frameT = wizard.frameT < 0 ? -1 : wizard.frameT;
    loadFrame();
    const on = (id, key, prop = "checked") => {
      const el = $("#" + id);
      if (!el) return;
      el.addEventListener("input", () => {
        wizard.opts[key] = prop === "checked" ? el.checked : Number(el.value);
        if (key === "sub_size") $("#wzSizeVal").textContent = el.value;
        if (key === "sub_offset") { $("#wzOffVal").textContent = el.value; }
        if (key === "line_gap") $("#wzGapVal").textContent = el.value;
        updateCaption();
      });
    };
    on("wzSubs", "subtitles"); on("wzUpper", "uppercase"); on("wzHook", "show_hook");
    on("wzSize", "sub_size"); on("wzOff", "sub_offset"); on("wzGap", "line_gap");
    $("#wzPos").addEventListener("change", (e) => { wizard.opts.sub_position = e.target.value; updateCaption(); });
    $("#wzSpeedSel").addEventListener("change", (e) => { wizard.opts.sub_speed = e.target.value; });
    $("#wzFont").addEventListener("change", (e) => { wizard.opts.sub_font = e.target.value; updateCaption(); });
    $("#wzExport").addEventListener("change", (e) => { wizard.opts.export_subs = e.target.checked; });
    $("#wzAccents").addEventListener("click", (e) => {
      const b = e.target.closest(".swatch");
      if (!b) return;
      wizard.opts.accent = b.dataset.val;
      $$("#wzAccents .swatch").forEach((x) => x.classList.toggle("active", x === b));
      updateCaption();
    });
    $("#wzReroll").addEventListener("click", () => { wizard.frameT = -1; loadFrame(); });
    updateCaption();
  }

  function updateCaption() {
    const cap = $("#wzCap");
    const preview = $("#wzPreview");
    if (!cap || !preview) return;
    const words = (wizard.opts.uppercase ? "ПРИМЕР СУБТИТРОВ" : "Пример субтитров").split(" ");
    cap.innerHTML = words.map((w, i) => `<span class="w ${i === 0 ? "hl" : ""}">${esc(w)}</span>`).join(" ");
    // Размер шрифта — от ширины кадра (1080), позиция — от его высоты (1920).
    // Раньше брали размеры увеличенной картинки и всё уезжало.
    const w = Math.max(1, preview.clientWidth);
    const h = Math.max(1, preview.clientHeight);
    const size = Number(wizard.opts.sub_size || 118) * 0.45 * (w / 1080);
    cap.style.fontFamily = FONT_CSS[wizard.opts.sub_font] || "VCMontserrat";
    cap.style.fontSize = `${Math.max(9, size)}px`;
    cap.style.setProperty("--hl", ACCENT_HEX[wizard.opts.accent] || ACCENT_HEX.yellow);
    cap.style.lineHeight = (1.15 + Number(wizard.opts.line_gap || 0) / 90).toFixed(2);
    cap.style.display = wizard.opts.subtitles ? "block" : "none";
    const zone = PLATFORM_ZONES[wizard.opts.platform] || PLATFORM_ZONES.universal;
    const k = h / 1920;
    const off = Number(wizard.opts.sub_offset || 0) * k;
    cap.style.top = ""; cap.style.bottom = ""; cap.style.transform = "";
    if (wizard.opts.sub_position === "top") {
      cap.style.top = `${pxClamp((zone.top + 120) * k - off, 4, h - 10)}px`;
      cap.style.bottom = "auto";
    } else if (wizard.opts.sub_position === "middle") {
      cap.style.top = `${pxClamp(h / 2 - off, 4, h - 10)}px`;
      cap.style.bottom = "auto";
      cap.style.transform = "translateY(-50%)";
    } else {
      cap.style.bottom = `${pxClamp(Math.max(320, zone.bottom + 60) * k + off, 4, h - 10)}px`;
      cap.style.top = "auto";
    }
    applyFrameStyle();
  }

  function stepCount() {
    const dur = Object.entries(DUR_PRESETS).find(([, v]) =>
      Number(v.min) === Number(wizard.opts.min_dur) && Number(v.max) === Number(wizard.opts.max_dur));
    return `
      <div class="wz-count">
        <div class="wz-block"><b>Сколько нарезок</b>
          <div class="count-pick">
            <div class="seg" id="wzCountSeg">
              ${[5, 10, 20, 50, 0].map((c) => `<button type="button" data-val="${c}" class="${Number(wizard.opts.count) === c ? "active" : ""}">${c === 0 ? "Все" : c}</button>`).join("")}
            </div>
            <label class="count-manual"><input type="number" id="wzCount" min="1" max="200" value="${wizard.opts.count > 0 ? wizard.opts.count : ""}" placeholder="своё"/><span>шт.</span></label>
          </div>
        </div>
        <div class="row2">
          <div class="field"><label>Длительность клипа</label>
            <select id="wzDur">${Object.entries(DUR_PRESETS).map(([k, v]) => `<option value="${k}" ${dur && dur[0] === k ? "selected" : ""}>${v.label}</option>`).join("")}</select>
          </div>
          <div class="field"><label>Что делать</label>
            <select id="wzSelect">
              <option value="smart" ${wizard.opts.select === "smart" ? "selected" : ""}>Умные моменты</option>
              <option value="even" ${wizard.opts.select === "even" ? "selected" : ""}>Просто порезать</option>
            </select>
          </div>
          <div class="field"><label>Порядок экспорта</label>
            <select id="wzOrder"><option value="chrono" ${wizard.opts.export_order === "chrono" ? "selected" : ""}>По хронологии</option><option value="score" ${wizard.opts.export_order === "score" ? "selected" : ""}>Топ моменты</option></select>
          </div>
        </div>
        <div class="row2">
          <div class="field"><label>Распознавание речи</label>
            <select id="wzAsrProfile">
              <option value="" ${wizard.opts.asr_profile === "" ? "selected" : ""}>Как в настройках</option>
              <option value="fast" ${wizard.opts.asr_profile === "fast" ? "selected" : ""}>Быстро</option>
              <option value="balance" ${wizard.opts.asr_profile === "balance" ? "selected" : ""}>Баланс</option>
              <option value="max" ${wizard.opts.asr_profile === "max" ? "selected" : ""}>Максимум</option>
            </select>
            <div class="opt-hint">Профиль сам подбирает модель и параметры. «Баланс» и «Максимум» могут скачать модель один раз. Пустое значение использует модель из настроек.</div>
          </div>
          <div class="field"><label>Язык речи</label>
            <select id="wzLanguage">
              <option value="auto" ${!wizard.opts.language || wizard.opts.language === "auto" ? "selected" : ""}>Определить автоматически</option>
              <option value="ru" ${wizard.opts.language === "ru" ? "selected" : ""}>Русский</option>
              <option value="uk" ${wizard.opts.language === "uk" ? "selected" : ""}>Украинский</option>
              <option value="en" ${wizard.opts.language === "en" ? "selected" : ""}>Английский</option>
              <option value="de" ${wizard.opts.language === "de" ? "selected" : ""}>Немецкий</option>
              <option value="es" ${wizard.opts.language === "es" ? "selected" : ""}>Испанский</option>
            </select>
            <div class="opt-hint">Для русского лучше указать язык явно. Если модель определит другой, после распознавания появится предупреждение.</div>
          </div>
          <div class="field"><label>Кто выбирает моменты</label>
            <select id="wzPicker">${PICKER_OPTIONS.map(([k, v]) => `<option value="${k}" ${wizard.opts.picker === k ? "selected" : ""}>${v}</option>`).join("")}</select>
          </div>
          <div class="field"><label>Минимальная оценка</label>
            <select id="wzMinScore">${[[0, "Любая"], [0.5, "≥ 50"], [0.6, "≥ 60"], [0.7, "≥ 70"], [0.8, "≥ 80"]].map(([v, label]) => `<option value="${v}" ${Number(wizard.opts.min_score || 0) === v ? "selected" : ""}>${label}</option>`).join("")}</select>
          </div>
        </div>
        <div class="field" id="wzMoodField"><label>Настроения <span class="muted">(пусто — любые)</span></label>
          <div class="seg" id="wzMoods">
            ${MOODS.map(([k, label]) => `<button type="button" data-mood="${k}" class="${(wizard.opts.mood_filter || []).includes(k) ? "active" : ""}">${label}</button>`).join("")}
          </div>
        </div>
        <div class="opt-hint" id="wzPickerHint">Локально — эвристики по речи, офлайн и бесплатно. DeepSeek и Gemini читают весь текст выпуска и выбирают моменты по смыслу и настроению. Ключи — в «Настройки → Нейросеть».</div>
        <div class="opt-hint">Склейки пауз и скорость пересчитают субтитры автоматически. Хук и текст можно поправить после рендера в редакторе клипа.</div>
      </div>`;
  }

  function bindCount() {
    const input = $("#wzCount");
    input.addEventListener("input", () => {
      if (input.value === "") wizard.opts.count = 0;
      else {
        const value = pxClamp(Math.round(Number(input.value) || 1), 1, 200);
        wizard.opts.count = value;
        if (input.value !== String(value)) input.value = String(value);
      }
      $$("#wzCountSeg button").forEach((b) => b.classList.toggle("active", Number(b.dataset.val) === wizard.opts.count));
    });
    $("#wzCountSeg").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-val]");
      if (!btn) return;
      wizard.opts.count = Number(btn.dataset.val);
      $$("#wzCountSeg button").forEach((b) => b.classList.toggle("active", b === btn));
      input.value = wizard.opts.count > 0 ? String(wizard.opts.count) : "";
    });
    $("#wzDur").addEventListener("change", (e) => {
      const preset = DUR_PRESETS[e.target.value];
      if (preset) Object.assign(wizard.opts, { min_dur: preset.min, max_dur: preset.max, target_dur: preset.target });
    });
    $("#wzSelect").addEventListener("change", (e) => { wizard.opts.select = e.target.value; });
    const asr = $("#wzAsrProfile");
    if (asr) asr.addEventListener("change", (e) => { wizard.opts.asr_profile = e.target.value; });
    const lang = $("#wzLanguage");
    if (lang) lang.addEventListener("change", (e) => { wizard.opts.language = e.target.value; });
    $("#wzOrder").addEventListener("change", (e) => { wizard.opts.export_order = e.target.value; });
    $("#wzPicker").addEventListener("change", (e) => { wizard.opts.picker = e.target.value; });
    $("#wzMinScore").addEventListener("change", (e) => { wizard.opts.min_score = Number(e.target.value); });
    $("#wzMoods").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-mood]");
      if (!btn) return;
      const mood = btn.dataset.mood;
      const list = Array.isArray(wizard.opts.mood_filter) ? wizard.opts.mood_filter : [];
      wizard.opts.mood_filter = list.includes(mood) ? list.filter((m) => m !== mood) : [...list, mood];
      btn.classList.toggle("active", wizard.opts.mood_filter.includes(mood));
    });
  }

  async function next() {
    if (wizard.step < 4) { wizard.step += 1; render(); return; }
    const btn = $("#wzNext");
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Запуск`;
    try {
      await api(`/api/projects/${wizard.pid}/options`, {
        method: "POST", body: JSON.stringify({ options: wizard.opts })
      });
      await api(`/api/projects/${wizard.pid}/start`, {
        method: "POST", body: JSON.stringify({ options: wizard.opts })
      });
      const pid = wizard.pid;
      closeWizard();
      toast("Нарезка запущена");
      await loadProjects();
      openProject(pid);
      schedulePoll(500);
    } catch (err) {
      toast(err.message || "Не удалось запустить", "err");
      btn.disabled = false;
      btn.textContent = "Сделать нарезки";
    }
  }

  /* Настройки: вкладка «Интерфейс» и место под будущие. */
  function openSettings() {
    $("#modal").innerHTML = `
      <div class="modal-backdrop" data-wz-close></div>
      <div class="modal-panel settings-panel">
        <div class="modal-head"><h3>Настройки</h3><button class="icon-btn" data-wz-close>${ICONS.close}</button></div>
        <div class="settings-layout">
          <div class="settings-tabs">
            <button class="active" data-tab="frame">Кадр и формат</button>
            <button data-tab="ai">Нейросеть</button>
            <button data-tab="interface">Интерфейс</button>
            <button disabled title="Появится позже">Папки</button>
            <button disabled title="Появится позже">Обновления</button>
            <button disabled title="Появится позже">Горячие клавиши</button>
          </div>
          <div class="settings-body">
            <div id="settingsFrame">
              <div class="row2">
                <div class="field"><label>Формат кадра</label>
                  <select id="setAspect">${Object.entries(ASPECT_META).map(([k, m]) => `<option value="${k}" ${state.opts.aspect === k ? "selected" : ""}>${k} — ${m.short}</option>`).join("")}</select>
                </div>
                <div class="field"><label>Кадрирование</label>
                  <select id="setMode">
                    <option value="auto" ${state.opts.mode === "auto" ? "selected" : ""}>Умный кроп (по лицу)</option>
                    <option value="blur" ${state.opts.mode === "blur" ? "selected" : ""}>Размытый фон</option>
                    <option value="crop" ${state.opts.mode === "crop" ? "selected" : ""}>По центру</option>
                  </select>
                </div>
              </div>
              <div class="row2">
                <div class="field"><label>Площадка</label>
                  <select id="setPlatform">${PLATFORM_OPTIONS.map(([k, v]) => `<option value="${k}" ${state.opts.platform === k ? "selected" : ""}>${v}</option>`).join("")}</select>
                </div>
                <div class="field"><label>Пресет стрима</label>
                  <select id="setLayout">
                    <option value="" ${!state.opts.layout ? "selected" : ""}>Выключен</option>
                    <option value="band" ${state.opts.layout === "band" ? "selected" : ""}>Лицо крупно снизу</option>
                    <option value="band_top" ${state.opts.layout === "band_top" ? "selected" : ""}>Лицо крупно сверху</option>
                    <option value="adhd" ${state.opts.layout === "adhd" ? "selected" : ""}>Сплит-скрин</option>
                  </select>
                </div>
              </div>
              <div class="opt-hint">Эти настройки применяются ко всем новым видео. В мастере на шаге «Кадр» их можно поменять для конкретного проекта.</div>
              <div class="wz-actions" id="setApplyRow"></div>
            </div>
            <div id="settingsAi" hidden>
              <div class="row2">
                <div class="field"><label>Ключ DeepSeek</label>
                  <input type="password" id="setDeepseekKey" autocomplete="off" spellcheck="false" placeholder="не задан" />
                  <div class="opt-hint" id="deepseekState"></div>
                </div>
                <div class="field"><label>Модель DeepSeek</label>
                  <input type="text" id="setDeepseekModel" list="setDeepseekModelList" placeholder="ID модели — можно ввести вручную" spellcheck="false" />\n                  <datalist id="setDeepseekModelList"></datalist>
                </div>
              </div>
              <div class="row2">
                <div class="field"><label>Ключ Gemini (Google AI Studio)</label>
                  <input type="password" id="setGeminiKey" autocomplete="off" spellcheck="false" placeholder="не задан" />
                  <div class="opt-hint" id="geminiState"></div>
                </div>
                <div class="field"><label>Модель Gemini</label>
                  <input type="text" id="setGeminiModel" list="setGeminiModelList" placeholder="ID модели — можно ввести вручную" spellcheck="false" />\n                  <datalist id="setGeminiModelList"></datalist>
                </div>
              </div>
              <div class="row2">
                <div class="field"><label>Ключ OpenRouter</label>
                  <input type="password" id="setOpenrouterKey" autocomplete="off" spellcheck="false" placeholder="sk-or-v1-…" />
                  <div class="opt-hint" id="openrouterState"></div>
                </div>
                <div class="field"><label>Модель OpenRouter</label>
                  <input type="text" id="setOpenrouterModel" list="setOpenrouterModelList" placeholder="ID модели — можно ввести вручную" spellcheck="false" />\n                  <datalist id="setOpenrouterModelList"></datalist>
                </div>
              </div>
              <div class="field"><label>Прокси для нейросетей</label>
                <input type="text" id="setProxy" autocomplete="off" spellcheck="false" placeholder="http://127.0.0.1:7901 — если нужен" />
              </div>
              <div class="field"><label>Распознавание речи (Whisper)</label>
                <select id="setWhisperModel">
                  <option value="tiny">tiny — совсем быстро, ~75 МБ</option>
                  <option value="base">base — быстро, ~150 МБ</option>
                  <option value="small">small — быстро, ~460 МБ</option>
                  <option value="medium">medium — баланс, ~1.5 ГБ</option>
                  <option value="large-v3-turbo">large-v3-turbo — быстрый и точный, ~1.6 ГБ</option>
                  <option value="large-v3">large-v3 — лучше для русского, ~3 ГБ</option>
                </select>
                <div class="opt-hint">Модель по умолчанию, если в проекте не выбран профиль. Для финальных субтитров на GPU лучше large-v3 или large-v3-turbo.</div>
              </div>
              <div class="field"><label>Словарь имён и терминов</label>
                <textarea id="setAsrTerms" rows="3" spellcheck="false" placeholder="Например: OpenAI, GPT-5, Сбер, Kubernetes"></textarea>
                <div class="opt-hint">Через запятую или с новой строки. Слова попадают в подсказку распознавания: имена и термины пишутся чаще правильнее. Подсказка не гарантирует результат.</div>
              </div>
              <div class="wz-actions">
                <button class="btn-ghost" id="checkDeepseek" type="button">Проверить DeepSeek</button>
                <button class="btn-ghost" id="checkGemini" type="button">Проверить Gemini</button>
                <button class="btn-ghost" id="checkOpenrouter" type="button">Проверить OpenRouter</button>
                <button class="btn-ghost" id="refreshModels" type="button">Обновить модели</button>
                <span class="opt-hint" id="modelState"></span>
                <button class="btn-ghost" id="clearAiKeys" type="button">Удалить ключи</button>
              </div>
              <div class="opt-hint">Ключи хранятся в папке данных приложения и не попадают ни в проект, ни в репозиторий. Пустое поле не стирает сохранённый ключ. Выбор «кто ищет моменты» — на шаге «Нарезка».</div>
            </div>
            <div id="settingsInterface" hidden>
            <div class="field"><label>Анимации интерфейса</label>
              <label class="toggle"><input type="checkbox" id="setMotion" ${currentMotion() === "on" ? "checked" : ""}/><span class="track"></span><span>Плавные появления и наведения</span></label>
              <div class="opt-hint">Если система просит «уменьшить движение», анимации можно включить здесь вручную.</div>
            </div>
            <div class="field"><label>Тема оформления</label>
              <label class="wz-row"><input type="radio" name="wzTheme" value="dark" ${currentTheme() === "dark" ? "checked" : ""}/> <b>Тёмная</b><span>как раньше</span></label>
              <label class="wz-row"><input type="radio" name="wzTheme" value="light" ${currentTheme() === "light" ? "checked" : ""}/> <b>Светлая</b><span>новая, тёплая</span></label>
            </div>
            <div class="field"><label>Экран создания клипов</label>
              <label class="wz-row"><input type="radio" name="wzUi" value="wizard" ${usesWizard() ? "checked" : ""}/> <b>Мастер по шагам</b>
                <span>источник → кадр → субтитры → количество</span></label>
              <label class="wz-row"><input type="radio" name="wzUi" value="classic" ${!usesWizard() ? "checked" : ""}/> <b>Старый экран</b>
                <span>все настройки одной страницей</span></label>
            </div>
            </div>
            <div class="opt-hint">Остальные вкладки появятся позже — место под них уже готово.</div>
          </div>
        </div>
      </div>`;
    $("#modal").classList.remove("hidden");
    $$("[data-wz-close]").forEach((b) => b.addEventListener("click", () => {
      $("#modal").classList.add("hidden"); $("#modal").innerHTML = "";
    }));
    $$(".settings-tabs button[data-tab]").forEach((tab) => tab.addEventListener("click", () => {
      $$(".settings-tabs button").forEach((b) => b.classList.toggle("active", b === tab));
      $("#settingsFrame").hidden = tab.dataset.tab !== "frame";
      $("#settingsInterface").hidden = tab.dataset.tab !== "interface";
      $("#settingsAi").hidden = tab.dataset.tab !== "ai";
    }));
    bindAiSettings();
    const saveFrame = () => {
      saveFrameDefaults({
        aspect: $("#setAspect").value,
        mode: $("#setMode").value,
        platform: $("#setPlatform").value,
        layout: $("#setLayout").value
      });
      syncHeroFrameOptions();
      toast("Настройки кадра сохранены");
    };
    ["setAspect", "setMode", "setPlatform", "setLayout"].forEach((id) => {
      $("#" + id).addEventListener("change", saveFrame);
    });
    const applyRow = $("#setApplyRow");
    if (applyRow && state.detail) {
      const done = state.detail.project.status === "done";
      applyRow.innerHTML = `<button class="btn-ghost" id="applyToProject">Применить к текущему проекту</button>` +
        (done ? ` <button class="btn-ghost" id="rerenderProject">Перерендерить все клипы</button>` : "");
      $("#applyToProject").addEventListener("click", async () => {
        const pid = state.detail.project.id;
        try {
          await api(`/api/projects/${pid}/options`, {
            method: "POST",
            body: JSON.stringify({ options: loadFrameDefaults() })
          });
          toast("Настройки кадра применены к проекту");
        } catch (err) { toast(err.message || "Не удалось применить", "err"); }
      });
      const rerender = $("#rerenderProject");
      if (rerender) rerender.addEventListener("click", async () => {
        const ready = (state.detail.clips || []).filter((c) => c.status === "ready");
        if (!ready.length) { toast("Нет готовых клипов", "err"); return; }
        if (!confirm(`Перерендерить ${ready.length} клипов с новыми настройками кадра?`)) return;
        try {
          for (const clip of ready) {
            await api(`/api/clips/${clip.id}/rerender`, {
              method: "POST",
              body: JSON.stringify(loadFrameDefaults())
            });
          }
          toast(`Перерендер запущен: ${ready.length} клипов`);
        } catch (err) { toast(err.message || "Не удалось запустить", "err"); }
      });
    }
    const motionBox = $("#setMotion");
    if (motionBox) motionBox.addEventListener("change", () => {
      applyMotion(motionBox.checked);
      toast(motionBox.checked ? "Анимации включены" : "Анимации выключены");
    });
    $$('input[name="wzTheme"]').forEach((el) => el.addEventListener("change", () => {
      applyTheme(el.value);
      syncThemeButton();
      toast(el.value === "light" ? "Светлая тема включена" : "Тёмная тема включена");
    }));
    $$('input[name="wzUi"]').forEach((el) => el.addEventListener("change", () => {
      setUiMode(el.value);
      if (!state.current) { state.mainKey = ""; renderMain(true); }
      toast(el.value === "wizard" ? "Включён мастер по шагам" : "Включён старый экран");
    }));
  }

  /* Вкладка «Нейросеть»: ключи, модели и проверка доступа. */
  function bindAiSettings() {
    const fillModels = (selector, list, value) => {
      const el = $(selector);
      if (!el) return;
      const items = (list || []).map((m) => (typeof m === "string" ? { id: m, name: m } : m));
      const datalist = $(selector + "List");
      if (datalist) {
        datalist.innerHTML = items.map((m) =>
          `<option value="${esc(m.id)}" label="${esc(m.name || m.id)}"></option>`).join("");
      } else if ("options" in el) {
        el.innerHTML = items.map((m) => `<option value="${esc(m.id)}">${esc(m.name || m.id)}</option>`).join("");
      }
      if (value) el.value = value;
    };
    const fillCatalog = (selector, models) => {
      const el = $(selector);
      if (!el) return;
      const items = (models || []).map((m) => (typeof m === "string" ? { id: m, name: m } : m));
      const datalist = $(selector + "List");
      if (datalist) {
        datalist.innerHTML = items.map((m) =>
          `<option value="${esc(m.id)}" label="${esc(m.name || m.id)}"></option>`).join("");
      }
      if (!el.value && items.length) el.value = items[0].id;
    };
    const refreshModels = async (silent) => {
      const state = $("#modelState");
      try {
        const res = await api("/api/app-settings/models");
        const catalogs = res.catalogs || {};
        const names = {deepseek: "DeepSeek", gemini: "Gemini", openrouter: "OpenRouter"};
        const notes = [];
        for (const [key, data] of Object.entries(catalogs)) {
          if (data.ok) {
            fillCatalog(`#set${key[0].toUpperCase()}${key.slice(1)}Model`, data.models);
            notes.push(`${names[key] || key}: ${data.models.length}`);
          } else {
            notes.push(`${names[key] || key}: ${data.error || "нет списка"}`);
          }
        }
        if (state) state.textContent = notes.join(" · ");
        if (!silent) toast("Списки моделей обновлены");
      } catch (err) {
        if (state) state.textContent = err.message || "не удалось обновить";
        if (!silent) toast(err.message || "Не удалось обновить списки", "err");
      }
    };
    const applyState = (s) => {
      if (!s) return;
      $("#deepseekState").textContent = s.deepseek_key_set
        ? `Ключ сохранён: ${s.deepseek_key_hint}` : "Ключ не задан";
      $("#geminiState").textContent = s.gemini_key_set
        ? `Ключ сохранён: ${s.gemini_key_hint}` : "Ключ не задан";
      fillModels("#setDeepseekModel", (s.model_choices || {}).deepseek, s.deepseek_model);
      const orState = $("#openrouterState");
      if (orState) orState.textContent = s.openrouter_key_set
        ? `Сохранён ключ: ${s.openrouter_key_hint}` : "Ключ не задан";
      fillModels("#setOpenrouterModel", (s.model_choices || {}).openrouter, s.openrouter_model);
      fillModels("#setGeminiModel", (s.model_choices || {}).gemini, s.gemini_model);
      const proxy = $("#setProxy");
      if (proxy && document.activeElement !== proxy) proxy.value = s.proxy || "";
      const whisper = $("#setWhisperModel");
      if (whisper) whisper.value = s.whisper_model || "small";
      const terms = $("#setAsrTerms");
      if (terms && document.activeElement !== terms) terms.value = s.asr_terms || "";
      $("#setDeepseekKey").value = "";
      $("#setGeminiKey").value = "";
      const orKey = $("#setOpenrouterKey");
      if (orKey) orKey.value = "";
      $("#setDeepseekKey").placeholder = s.deepseek_key_set ? "ключ сохранён — введите новый, чтобы заменить" : "не задан";
      $("#setGeminiKey").placeholder = s.gemini_key_set ? "ключ сохранён — введите новый, чтобы заменить" : "не задан";
    };
    const save = () => api("/api/app-settings", {
      method: "POST",
      body: JSON.stringify({
        deepseek_key: $("#setDeepseekKey").value.trim(),
        gemini_key: $("#setGeminiKey").value.trim(),
        deepseek_model: $("#setDeepseekModel").value,
        gemini_model: $("#setGeminiModel").value,
        openrouter_key: ($("#setOpenrouterKey") || {}).value ? $("#setOpenrouterKey").value.trim() : "",
        openrouter_model: $("#setOpenrouterModel") ? $("#setOpenrouterModel").value : "",
        proxy: $("#setProxy").value.trim(),
        whisper_model: ($("#setWhisperModel") || {}).value || "small",
        asr_terms: ($("#setAsrTerms") || {}).value || ""
      })
    }).then(applyState).catch((err) => toast(err.message || "Не удалось сохранить", "err"));
    ["#setDeepseekKey", "#setGeminiKey", "#setOpenrouterKey", "#setDeepseekModel", "#setGeminiModel", "#setOpenrouterModel", "#setWhisperModel", "#setProxy", "#setAsrTerms"]
      .forEach((selector) => {
        const el = $(selector);
        if (el) el.addEventListener("change", save);
      });
    const check = (provider, button) => {
      const el = $(button);
      if (!el) return;
      const restore = el.textContent;
      el.disabled = true;
      el.textContent = "Проверяю…";
      api("/api/app-settings/check", { method: "POST", body: JSON.stringify({ provider }) })
        .then((res) => toast(res.message || (res.ok ? "Ключ работает" : "Ошибка"), res.ok ? "ok" : "err"))
        .catch((err) => toast(err.message || "Не удалось проверить", "err"))
        .finally(() => { el.disabled = false; el.textContent = restore; });
    };
    $("#checkDeepseek").addEventListener("click", () => check("deepseek", "#checkDeepseek"));
    $("#checkGemini").addEventListener("click", () => check("gemini", "#checkGemini"));
    const refreshBtn = $("#refreshModels");
    if (refreshBtn) refreshBtn.addEventListener("click", () => refreshModels(false));
    const orCheck = $("#checkOpenrouter");
    if (orCheck) orCheck.addEventListener("click", () => check("openrouter", "#checkOpenrouter"));
    $("#clearAiKeys").addEventListener("click", () => {
      if (!confirm("Удалить сохранённые ключи DeepSeek и Gemini?")) return;
      api("/api/app-settings", {
        method: "POST",
        body: JSON.stringify({ clear_deepseek_key: true, clear_gemini_key: true, clear_openrouter_key: true })
      }).then((s) => { applyState(s); toast("Ключи удалены"); })
        .catch((err) => toast(err.message || "Не удалось удалить", "err"));
    });
    api("/api/app-settings").then(applyState).then(() => refreshModels(true))
      .catch((err) => toast(err.message || "Не удалось загрузить настройки", "err"));
  }

  const themeBtn = $("#themeBtn");
  if (themeBtn) themeBtn.addEventListener("click", () => {
    applyTheme(currentTheme() === "light" ? "dark" : "light");
    syncThemeButton();
  });
  syncThemeButton();
  $("#settingsBtn").addEventListener("click", openSettings);

  /* Все точки входа вызывают openTemplate — подменяем на мастер по настройке. */
  const classicOpen = openTemplate;
  openTemplate = function (pid) {
    if (usesWizard()) openWizard(pid);
    else classicOpen(pid);
  };

  /* Файлы, выбранные в шаге 1, уходят в обычные загрузчики app.js. */
  document.addEventListener("change", (e) => {
    const endpoints = { wzFileInput: "upload", wzSubsInput: "subtitles",
                        wzDubInput: "dub", wzMusicInput: "music" };
    const endpoint = e.target ? endpoints[e.target.id] : "";
    if (!wizard.pid || !endpoint) return;
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    api(`/api/projects/${wizard.pid}/${endpoint}`, { method: "POST", body: form })
      .then(() => { toast("Файл подключён"); poll(); })
      .catch((err) => toast(err.message || "Не удалось загрузить файл", "err"));
  });

  window.openWizard = openWizard;
  window.openSettings = openSettings;
})();