import { icon } from "./icons.js";
import { EditorCanvas } from "./canvas.js";

const $ = (id) => document.getElementById(id);
const esc = (v) =>
  String(v).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const uid = () =>
  globalThis.crypto?.randomUUID?.() ||
  `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const TOOLS = [
  ["crop", "裁剪", "crop"],
  ["background", "背景色", "background"],
  ["rotate", "旋转翻转", "rotate"],
  ["brush", "画笔", "brush"],
  ["mosaic", "马赛克", "mosaic"],
  ["blur", "局部模糊", "blur"],
  ["watermark", "水印", "watermark"],
  ["enhance", "图片增强", "enhance"],
  ["compress", "图像压缩", "compress"],
];
let boot = null,
  session = null,
  tool = "crop",
  preview = null,
  draftSeq = 0,
  draftActive = false,
  running = null,
  pending = false,
  timer = null,
  applying = false,
  gesture = uid(),
  toastTimer,
  savedRevision = -1;
const defaults = {
  brightness: 1,
  contrast: 1,
  saturation: 1,
  sharpness: 1,
  temperature: 0,
  gamma: 1,
  autocontrast: false,
  white_balance: false,
  denoise: 0,
  equalize: 0,
};
const settings = {
  crop: { mode: "t:0", ratio_w: 16, ratio_h: 9, allow_resize: false },
  background: { color: "#ffffff" },
  rotate: { angle: 0, flip: null, expand: true },
  brush: { size: 30, opacity: 1, color: "#ffffff", block: 12, erase: false },
  mosaic: { size: 30, opacity: 1, color: "#ffffff", block: 12 },
  blur: { size: 30, opacity: 1, color: "#ffffff", block: 12 },
  watermark: {
    text: "仅用于报名审核",
    font: "",
    size: 28,
    color: "#64748b",
    opacity: 0.28,
    angle: 30,
    row_spacing: 60,
    column_spacing: 80,
    multiple: false,
    live: true,
  },
  enhance: { ...defaults },
  compress: {
    format: "JPEG",
    quality: 95,
    keep_alpha: true,
    keep_exif: false,
    keep_icc: true,
    background: "#ffffff",
    live: true,
  },
};

function hydrate(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = icon(el.dataset.icon);
  });
}
function status(text, busy = false) {
  $("status").textContent = text;
  document.body.classList.toggle("busy", busy);
}
function toast(text) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("toast").hidden = true), 3200);
}
function error(message) {
  $("error-message").textContent = String(message);
  if (!$("error-dialog").open) $("error-dialog").showModal();
  status("操作未完成");
}
async function api(
  path,
  { method = "GET", body, raw = false, headers = {} } = {},
) {
  const result = await fetch(path, {
    method,
    headers: raw ? headers : { "Content-Type": "application/json", ...headers },
    body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
  });
  if (!result.ok) {
    let message;
    try {
      const json = await result.json();
      message =
        typeof json.detail === "string"
          ? json.detail
          : JSON.stringify(json.detail);
    } catch {
      message = `服务返回错误（${result.status}）`;
    }
    throw new Error(message);
  }
  return result.json();
}
const endpoint = (suffix) => `/api/sessions/${session.id}/${suffix}`;
function bytes(size) {
  return size >= 1024 * 1024
    ? `${(size / 1024 / 1024).toFixed(2)} MB`
    : `${(size / 1024).toFixed(2)} KB`;
}
function info(data) {
  if (!data) return "—";
  const encoding = data.original
    ? "原文件字节，未重新编码"
    : data.lossy
      ? "有损"
      : "无损";
  return `${bytes(data.bytes)}  ·  ${data.width} × ${data.height} px  ·  ${data.format}\n${data.bytes.toLocaleString()} 字节  ·  ${encoding}${data.quality == null ? "" : ` · 质量 ${data.quality}`}`;
}
function showCurrent() {
  if (!session) return;
  $("current-info").textContent = info(session.current);
  $("filename").textContent = session.name;
  $("filename").title = `原文件：${info(session.original)}`;
  $("undo-button").disabled = !session.can_undo || applying;
  $("redo-button").disabled = !session.can_redo || applying;
  $("save-button").disabled = false;
  $("compare-button").disabled = false;
}
function showAppliedPreview() {
  if (!session) return;
  $("preview-badge").textContent = "与当前一致";
  $("preview-info").textContent = info(session.current);
}
function updateApply() {
  canvas.blocked = applying;
  const automatic = ["brush", "mosaic", "blur", "enhance"].includes(tool);
  $("apply-button").disabled =
    !session ||
    automatic ||
    applying ||
    !draftActive ||
    (tool === "crop" && !canvas.crop);
  $("apply-button").title = automatic
    ? "此功能调整后自动应用。"
    : "应用当前功能的调整，之后才会参与保存。";
}
const canvas = new EditorCanvas($("editor-canvas"), {
  zoom: (value) => ($("zoom").textContent = `${Math.round(value * 100)}%`),
  crop: (rect) => {
    if (tool !== "crop") return;
    const w = $("crop-width"),
      h = $("crop-height");
    if (w) w.value = rect.w;
    if (h) h.value = rect.h;
    if (session) schedule();
  },
  stroke: (body) => performStroke(body),
});
function template() {
  const index = Number(settings.crop.mode.slice(2));
  return settings.crop.mode.startsWith("t:") ? boot?.templates[index] : null;
}
function resetCrop() {
  if (!session) return;
  const t = template(),
    s = settings.crop;
  canvas.setCrop(
    s.mode,
    t ? [t.width, t.height] : null,
    s.allow_resize,
    s.ratio_w / s.ratio_h,
  );
  draftActive = true;
  updateApply();
}
function range(name, label, min, max, step = 1, suffix = "", extra = "") {
  const value = settings[tool][name];
  return `<div class="range-field"><div class="range-label"><span>${label}</span><output class="range-value" for="field-${name}">${Number(value).toFixed(step < 1 ? 2 : 0)}${suffix}</output></div><input id="field-${name}" data-field="${name}" type="range" min="${min}" max="${max}" step="${step}" value="${value}" ${extra} aria-label="${label}"></div>`;
}
function check(name, label) {
  return `<label class="check"><input type="checkbox" data-field="${name}" ${settings[tool][name] ? "checked" : ""}>${label}</label>`;
}
function color(name, label) {
  const value = settings[tool][name];
  return `<div class="field"><span>${label}</span><button type="button" class="color-trigger" data-pick-color="${name}" aria-label="${label}" aria-haspopup="dialog"><span class="color-chip" style="background:${esc(value)}"></span><span>${esc(value)}</span></button></div>`;
}
let colorTarget = null;
function setPickerColor(value) {
  if (!/^#[0-9a-f]{6}$/i.test(value)) return;
  value = value.toLowerCase();
  $("color-hex").value = value;
  $("color-preview").style.background = value;
  ["r", "g", "b"].forEach((channel, index) => {
    const number = parseInt(value.slice(1 + index * 2, 3 + index * 2), 16);
    $(`color-${channel}`).value = number;
    $(`color-${channel}-value`).textContent = number;
  });
  $("color-presets")
    .querySelectorAll("[data-value]")
    .forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.value === value),
      );
    });
}
function openColor(name) {
  colorTarget = { tool, name };
  $("color-presets").innerHTML = boot.colors
    .map(
      (value) =>
        `<button type="button" class="swatch" data-value="${esc(value)}" style="background:${esc(value)}" title="${esc(value)}" aria-label="颜色 ${esc(value)}" aria-pressed="false"></button>`,
    )
    .join("");
  $("color-presets")
    .querySelectorAll("button")
    .forEach((button) => {
      button.addEventListener("click", () =>
        setPickerColor(button.dataset.value),
      );
    });
  setPickerColor(settings[tool][name]);
  $("color-dialog").showModal();
}
$("color-hex").addEventListener("input", (event) =>
  setPickerColor(event.target.value),
);
for (const channel of ["r", "g", "b"]) {
  $(`color-${channel}`).addEventListener("input", () => {
    const value = ["r", "g", "b"]
      .map((key) =>
        Number($(`color-${key}`).value)
          .toString(16)
          .padStart(2, "0"),
      )
      .join("");
    setPickerColor("#" + value);
  });
}
$("color-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const value = $("color-hex").value;
  if (!colorTarget || !/^#[0-9a-f]{6}$/i.test(value)) return;
  settings[colorTarget.tool][colorTarget.name] = value.toLowerCase();
  $("color-dialog").close();
  if (tool === colorTarget.tool) {
    panel();
    if (["brush", "mosaic", "blur"].includes(tool))
      canvas.brush = { ...settings[tool] };
    schedule();
  }
});
function panel() {
  const names = {
    crop: ["裁剪", "选择规格、调整取景，确认后点击上方「应用」。"],
    background: ["背景色", "为透明或半透明区域填充颜色。"],
    rotate: ["旋转与翻转", "调整方向或角度，让画面恰到好处。"],
    brush: ["画笔与修正", "在画面上绘制，或擦除为透明。"],
    mosaic: ["马赛克", "沿笔触遮挡画面中的敏感信息。"],
    blur: ["局部模糊", "柔化笔触经过的区域，保留其余细节。"],
    watermark: ["文字水印", "整页重复平铺，预览满意后再应用。"],
    enhance: ["图片增强", "调整即应用，滑块保留当前位置。"],
    compress: ["图像压缩", "调整格式与画质，保持当前像素尺寸。"],
  };
  const [title, description] = names[tool];
  let content = "";
  const s = settings[tool];
  if (tool === "crop") {
    const t = template();
    content = `<div class="section-heading"><span>裁剪方式</span></div><select id="crop-mode" aria-label="裁剪方式">${boot.templates.map((t, i) => `<option value="t:${i}" ${s.mode === `t:${i}` ? "selected" : ""}>${esc(t.name)}</option>`).join("")}<option value="free" ${s.mode === "free" ? "selected" : ""}>自由裁剪</option><option value="custom" ${s.mode === "custom" ? "selected" : ""}>按比例裁剪</option></select>`;
    if (t)
      content += `<div class="card"><div class="card-title">模板尺寸</div><div class="two-fields"><label class="stacked">宽度 / px<input type="number" value="${t.width}" readonly aria-label="模板宽度"></label><label class="stacked">高度 / px<input type="number" value="${t.height}" readonly aria-label="模板高度"></label></div></div><div class="card">${check("allow_resize", "允许缩放")}<p class="small-hint">${s.allow_resize ? "将选区缩放至模板尺寸。" : "按模板像素裁剪，不进行缩放。"}<br>放大可能模糊，缩小会损失细节。</p></div>`;
    else if (s.mode === "custom")
      content += `<div class="card"><div class="card-title">宽高比例</div><div class="two-fields"><label class="stacked">宽<input type="number" min="1" max="30000" data-field="ratio_w" value="${s.ratio_w}"></label><label class="stacked">高<input type="number" min="1" max="30000" data-field="ratio_h" value="${s.ratio_h}"></label></div></div>`;
    else
      content += `<div class="card"><div class="card-title">裁剪框像素</div><div class="two-fields"><label class="stacked">宽度 / px<input id="crop-width" type="number" min="1" max="${session?.current.width || 30000}" value="${canvas.crop?.w || 295}"></label><label class="stacked">高度 / px<input id="crop-height" type="number" min="1" max="${session?.current.height || 30000}" value="${canvas.crop?.h || 413}"></label></div></div>`;
  } else if (tool === "background")
    content = `<div class="card">${color("color", "填充颜色")}</div><p class="small-hint">仅填充透明区域，不会自动抠图。可先用橡皮擦擦除原背景。</p>`;
  else if (tool === "rotate")
    content = `<div class="panel-buttons"><button id="rotate-left">${icon("undo", 16)}左转 90°</button><button id="rotate-right">${icon("redo", 16)}右转 90°</button></div>${range("angle", "旋转角度", -180, 180, 1, "°")}<div class="panel-buttons"><button id="flip-horizontal" class="${s.flip === "horizontal" ? "active" : ""}">水平翻转</button><button id="flip-vertical" class="${s.flip === "vertical" ? "active" : ""}">垂直翻转</button></div>${check("expand", "扩展画布，保留完整内容")}`;
  else if (["brush", "mosaic", "blur"].includes(tool)) {
    content =
      range("size", "画笔大小", 1, 100, 1, " px") +
      range("opacity", "不透明度", 0.01, 1, 0.01);
    if (tool === "brush")
      content +=
        color("color", "画笔颜色") + check("erase", "橡皮擦（擦除为透明）");
    else
      content += range(
        "block",
        tool === "mosaic" ? "块大小" : "模糊强度",
        2,
        100,
        1,
        " px",
      );
    content +=
      '<p class="small-hint">松开鼠标后自动应用。Ctrl+Z 撤销上一笔。</p>';
  } else if (tool === "watermark") {
    content = `<label class="field">水印文字<input id="mark-text" type="text" data-field="text" value="${esc(s.text)}" maxlength="50" title="最多 50 字，超长文字不允许。" aria-label="水印文字"></label><label class="stacked">服务端字体<select data-field="font" aria-label="服务端字体">${boot.fonts.map((f) => `<option value="${f.id}" ${s.font === f.id ? "selected" : ""}>${esc(f.name)}</option>`).join("")}</select></label><p class="small-hint">字体来自当前服务，容器内置中文字体。</p>`;
    content +=
      range("size", "字号", 4, 200, 1, " px") + color("color", "文字颜色");

    content +=
      range("opacity", "不透明度", 0.01, 1, 0.01) +
      range("angle", "倾斜角度", -180, 180, 1, "°") +
      range("row_spacing", "行间距", 0, 500, 1, " px") +
      range("column_spacing", "列间距", 0, 500, 1, " px") +
      check("live", "实时预览") +
      check("multiple", "允许多重水印");
    content +=
      '<button id="clear-marks" class="full-button secondary">清除已应用水印</button>';
  } else if (tool === "enhance") {
    content =
      range("brightness", "亮度", 0.1, 3, 0.01) +
      range(
        "contrast",
        "对比度",
        0.1,
        3,
        0.01,
        "",
        s.autocontrast ? "disabled" : "",
      ) +
      check("autocontrast", "自动对比度") +
      range("saturation", "饱和度", 0, 3, 0.01) +
      range("sharpness", "锐度", 0, 5, 0.01) +
      range(
        "temperature",
        "色温",
        -1,
        1,
        0.01,
        "",
        s.white_balance ? "disabled" : "",
      ) +
      check("white_balance", "自动白平衡") +
      range("gamma", "伽马", 0.1, 3, 0.01) +
      range("denoise", "降噪强度", 0, 1, 0.01) +
      range("equalize", "明暗均衡", 0, 1, 0.01) +
      '<button id="reset-enhance" class="full-button secondary">恢复默认参数</button>';
  } else if (tool === "compress") {
    const lossy = ["JPEG", "WEBP"].includes(s.format);
    content = `<label class="field">文件格式<select data-field="format" aria-label="文件格式">${["JPEG", "PNG", "WEBP", "BMP", "TIFF"].map((v) => `<option ${v === s.format ? "selected" : ""}>${v}</option>`).join("")}</select></label><p class="small-hint">${lossy ? "适合照片，可通过画质控制文件体积。" : "使用无损编码，保留图像细节。"}</p><div class="card">${check("live", "在画布查看压缩效果")}</div>`;
    if (lossy) content += range("quality", "画质", 1, 100);
    content += `<details><summary>高级设置</summary>${["JPEG", "BMP"].includes(s.format) ? "" : check("keep_alpha", "保留透明背景")}${color("background", "透明区域填充色")}${check("keep_exif", "保留 EXIF（可能含位置）")}${check("keep_icc", "保留 ICC 色彩配置")}</details><p class="small-hint">调整仅预览。应用后，保存才会使用所选格式与画质。</p>`;
  }
  $("properties").innerHTML =
    `<div class="panel-eyebrow">PHOTO WORKSPACE</div><h2>${title}</h2><p class="panel-description">${description}</p>${content}`;
  wirePanel();
  updateApply();
}
function wirePanel() {
  $("properties")
    .querySelectorAll("[data-field]")
    .forEach((input) => {
      input.addEventListener(
        input.type === "range" ||
          input.type === "color" ||
          input.type === "text"
          ? "input"
          : "change",
        () => {
          const key = input.dataset.field;
          let value =
            input.type === "checkbox"
              ? input.checked
              : input.type === "number" || input.type === "range"
                ? Number(input.value)
                : input.value;
          if (
            input.type === "number" &&
            (!Number.isFinite(value) || value <= 0)
          )
            return;
          settings[tool][key] = value;
          const output =
            input.parentElement.querySelector("output") ||
            input.closest(".range-field")?.querySelector("output");
          if (output) {
            const suffix = output.textContent.match(/(?: px|°)$/)?.[0] || "";
            output.textContent =
              Number(value).toFixed(Number(input.step) < 1 ? 2 : 0) + suffix;
          }
          if (tool === "crop") {
            panel();
            resetCrop();
          } else if (
            tool === "enhance" &&
            ["autocontrast", "white_balance"].includes(key)
          ) {
            gesture = uid();
            panel();
            schedule();
          } else if (tool === "compress" && key === "format") {
            panel();
            schedule();
          } else {
            if (input.type === "checkbox") gesture = uid();
            schedule();
          }
          if (["brush", "mosaic", "blur"].includes(tool))
            canvas.brush = { ...settings[tool] };
        },
      );
      if (input.type === "range")
        input.addEventListener("pointerdown", () => {
          gesture = uid();
        });
    });
  $("crop-mode")?.addEventListener("change", (e) => {
    settings.crop.mode = e.target.value;
    panel();
    resetCrop();
  });
  for (const id of ["crop-width", "crop-height"])
    $(id)?.addEventListener("change", () =>
      canvas.cropPixels(
        Number($("crop-width").value),
        Number($("crop-height").value),
      ),
    );
  $("rotate-left")?.addEventListener("click", () => {
    settings.rotate.angle = wrapAngle(settings.rotate.angle + 90);
    panel();
    schedule();
  });
  $("rotate-right")?.addEventListener("click", () => {
    settings.rotate.angle = wrapAngle(settings.rotate.angle - 90);
    panel();
    schedule();
  });
  for (const flip of ["horizontal", "vertical"])
    $(`flip-${flip}`)?.addEventListener("click", () => {
      settings.rotate.flip = settings.rotate.flip === flip ? null : flip;
      panel();
      schedule();
    });
  $("reset-enhance")?.addEventListener("click", () => {
    settings.enhance = { ...defaults };
    gesture = uid();
    panel();
    schedule();
  });
  $("clear-marks")?.addEventListener("click", () =>
    directOperation("clear_watermarks", {}),
  );
  $("properties")
    .querySelectorAll("[data-pick-color]")
    .forEach((button) => {
      button.addEventListener("click", () =>
        openColor(button.dataset.pickColor),
      );
    });
  $("mark-text")?.addEventListener("beforeinput", (e) => {
    if (
      e.data &&
      e.target.value.length -
        (e.target.selectionEnd - e.target.selectionStart) +
        e.data.length >
        50
    ) {
      e.preventDefault();
      toast("水印文字超长，不允许超过 50 字。");
    }
  });
  $("mark-text")?.addEventListener("paste", (e) => {
    const text = e.clipboardData.getData("text");
    if (
      e.target.value.length -
        (e.target.selectionEnd - e.target.selectionStart) +
        text.length >
      50
    ) {
      e.preventDefault();
      toast("水印文字超长，不允许超过 50 字。");
    }
  });
}
function wrapAngle(v) {
  while (v > 180) v -= 360;
  while (v < -180) v += 360;
  return v;
}
function operation() {
  if (!session || !draftActive) return null;
  let params = { ...settings[tool] };
  if (tool === "crop") {
    const r = canvas.crop;
    if (!r) return null;
    const t = template();
    params = {
      box: [r.x, r.y, r.x + r.w, r.y + r.h],
      size: t ? [t.width, t.height] : null,
      allow_resize: settings.crop.allow_resize,
    };
  }
  if (tool === "watermark" || tool === "compress") delete params.live;
  if (tool === "compress")
    params = Object.fromEntries(
      [
        "format",
        "quality",
        "keep_alpha",
        "keep_exif",
        "keep_icc",
        "background",
      ].map((key) => [key, settings.compress[key]]),
    );
  if (["brush", "mosaic", "blur"].includes(tool)) return null;
  return { revision: session.revision, tool, params };
}
function live() {
  return !["watermark", "compress"].includes(tool) || settings[tool].live;
}
function schedule() {
  draftSeq++;
  draftActive = true;
  preview = null;
  clearTimeout(timer);
  updateApply();
  if (!session || !operation() || !live()) {
    showAppliedPreview();
    if (session && !canvas.compareState)
      canvas
        .setImage(session.image_url, [
          session.current.width,
          session.current.height,
        ])
        .catch(error);
    return;
  }
  $("preview-badge").textContent = "未应用";
  $("preview-info").textContent = "正在计算预览实测…";
  if (running) pending = true;
  else timer = setTimeout(() => runPreview(), 230);
}
async function acceptApplied(result, seq, { fit = false, reset = false } = {}) {
  if (!session || result.id !== session.id) return;
  const latest = seq === draftSeq;
  session = result;
  showCurrent();
  if (latest) {
    draftActive = false;
    preview = null;
    canvas.localImage = null;
    if (tool === "crop") canvas.crop = null;
    showAppliedPreview();
    await canvas.setImage(
      session.image_url,
      [session.current.width, session.current.height],
      fit,
    );
  }
  if (reset) {
    settings.enhance = { ...session.enhancement };
    settings.compress = { ...settings.compress, ...session.compression };
    panel();
  }
  updateApply();
}
function runPreview(showErrors = false) {
  if (running) return running;
  const body = operation();
  if (!body) return Promise.resolve(null);
  const seq = draftSeq,
    sid = session.id,
    activeTool = tool,
    activeGesture = gesture;
  status("正在生成预览…", true);
  pending = false;
  running = (async () => {
    try {
      const response = await api(`/api/sessions/${sid}/preview`, {
        method: "POST",
        body,
      });
      if (!session || session.id !== sid || seq !== draftSeq) return null;
      preview = { ...response, seq };
      $("preview-info").textContent =
        info(response.info) + (response.warning ? "\n" + response.warning : "");
      $("preview-badge").textContent = response.can_apply
        ? "未应用"
        : "与当前一致";
      if (activeTool !== "crop" && !canvas.compareState && live())
        await canvas.setImage(response.image_url, [
          response.info.width,
          response.info.height,
        ]);
      if (activeTool === "enhance" && response.can_apply) {
        const result = await api(`/api/sessions/${sid}/apply`, {
          method: "POST",
          body: {
            revision: body.revision,
            preview_id: response.preview_id,
            gesture: activeGesture,
          },
        });
        await acceptApplied(result, seq);
        status("增强已应用");
      } else status(response.warning || "预览已更新");
      if (activeTool === "background" && !response.can_apply)
        $("apply-button").disabled = true;
      return response;
    } catch (e) {
      if (session?.id === sid && seq === draftSeq) {
        $("preview-info").textContent = e.message;
        $("preview-badge").textContent = "无法应用";
        status("请检查调整参数");
        if (showErrors) error(e.message);
      }
      return null;
    } finally {
      document.body.classList.remove("busy");
    }
  })().finally(() => {
    running = null;
    updateApply();
    if (preview && !preview.can_apply && tool === "background")
      $("apply-button").disabled = true;
    if (pending && session) {
      pending = false;
      timer = setTimeout(() => runPreview(), 80);
    }
  });
  return running;
}
async function applyCurrent() {
  if (!session || applying) return;
  applying = true;
  updateApply();
  clearTimeout(timer);
  try {
    while (running) await running;
    if (!preview || preview.seq !== draftSeq) await runPreview(true);
    if (!preview || !preview.can_apply) return;
    const seq = draftSeq;
    const result = await api(endpoint("apply"), {
      method: "POST",
      body: { revision: session.revision, preview_id: preview.preview_id },
    });
    await acceptApplied(result, seq, {
      fit: tool === "crop" || tool === "rotate",
    });
    if (tool === "rotate") {
      settings.rotate = {
        angle: 0,
        flip: null,
        expand: settings.rotate.expand,
      };
      panel();
    }
    toast("已应用，保存将使用当前结果");
    status("调整已应用");
  } catch (e) {
    error(e.message);
  } finally {
    applying = false;
    updateApply();
    showCurrent();
  }
}
async function performStroke(body) {
  await directOperation(tool, body);
}
async function directOperation(name, params) {
  if (!session || applying) return;
  applying = true;
  updateApply();
  clearTimeout(timer);
  draftSeq++;
  try {
    while (running) await running;
    const seq = draftSeq;
    const response = await api(endpoint("preview"), {
      method: "POST",
      body: { revision: session.revision, tool: name, params },
    });
    if (response.can_apply) {
      const result = await api(endpoint("apply"), {
        method: "POST",
        body: { revision: session.revision, preview_id: response.preview_id },
      });
      await acceptApplied(result, seq);
    }
    status("调整已应用");
  } catch (e) {
    canvas.localImage = null;
    canvas.draw();
    error(e.message);
  } finally {
    applying = false;
    updateApply();
    showCurrent();
  }
}
async function travel(redo = false) {
  if (!session || applying || !(redo ? session.can_redo : session.can_undo))
    return;
  clearTimeout(timer);
  pending = false;
  draftSeq++;
  draftActive = false;
  applying = true;
  updateApply();
  try {
    while (running) await running;
    const result = await api(endpoint(redo ? "redo" : "undo"), {
      method: "POST",
      body: { revision: session.revision },
    });
    canvas.crop = null;
    settings.rotate.angle = 0;
    settings.rotate.flip = null;
    await acceptApplied(result, draftSeq, { fit: true, reset: true });
    toast(redo ? "已重做" : "已撤销");
  } catch (e) {
    error(e.message);
  } finally {
    applying = false;
    updateApply();
    showCurrent();
  }
}
async function selectTool(name) {
  if (!boot || applying) return;
  clearTimeout(timer);
  draftSeq++;
  pending = false;
  preview = null;
  if (tool === "rotate" && name !== tool)
    settings.rotate = { angle: 0, flip: null, expand: settings.rotate.expand };
  tool = name;
  gesture = uid();
  canvas.setTool(tool);
  canvas.localImage = null;
  document.querySelectorAll(".tool-button").forEach((el) => {
    el.classList.toggle("active", el.dataset.tool === tool);
    el.setAttribute("aria-pressed", el.dataset.tool === tool);
  });
  panel();
  if (!session) return;
  draftActive = !["brush", "mosaic", "blur", "enhance"].includes(tool);
  await canvas.setImage(session.image_url, [
    session.current.width,
    session.current.height,
  ]);
  if (tool === "crop") resetCrop();
  else canvas.crop = null;
  if (["brush", "mosaic", "blur"].includes(tool))
    canvas.brush = { ...settings[tool] };
  if (draftActive) schedule();
  else showAppliedPreview();
  status(`${TOOLS.find((t) => t[0] === tool)[1]} · 当前服务处理`);
  updateApply();
}
async function openImage(file, demo = false) {
  if (!boot) return;
  if (
    session?.dirty &&
    session.revision !== savedRevision &&
    !confirm("当前照片已有修改。打开另一张图片前，请确认已下载保存。继续打开？")
  )
    return;
  if (!demo && file.size > boot.max_upload_mb * 1024 * 1024) {
    error(`图片不能超过 ${boot.max_upload_mb} MB。`);
    return;
  }
  clearTimeout(timer);
  draftSeq++;
  pending = false;
  status(demo ? "正在打开演示照片…" : "正在上传至当前服务…", true);
  try {
    const result = demo
      ? await api("/api/demo", { method: "POST" })
      : await api("/api/sessions", {
          method: "POST",
          body: file,
          raw: true,
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Filename": encodeURIComponent(file.name),
          },
        });
    const old = session;
    session = result;
    savedRevision = -1;
    if (old)
      fetch(`/api/sessions/${old.id}/close`, { method: "POST" }).catch(
        () => {},
      );
    settings.enhance = { ...session.enhancement };
    settings.compress = { ...settings.compress, ...session.compression };
    $("welcome").hidden = true;
    $("editor-canvas").hidden = false;
    canvas.crop = null;
    showCurrent();
    showAppliedPreview();
    await canvas.setImage(
      session.image_url,
      [session.current.width, session.current.height],
      true,
    );
    await selectTool(tool);
    status("图片已打开，原文件保持不变");
  } catch (e) {
    error(e.message);
  } finally {
    document.body.classList.remove("busy");
    $("file-input").value = "";
  }
}
async function save() {
  if (!session) return;
  try {
    const result = await fetch(endpoint("download"));
    if (!result.ok) throw new Error("保存失败，请重试。");
    const blob = await result.blob();
    const header = result.headers.get("Content-Disposition") || "";
    const name = decodeURIComponent(
      header.match(/filename\*=UTF-8''(.+)/)?.[1] || "photocraft.png",
    );
    download(blob, name);
    savedRevision = Number(result.headers.get("X-PhotoCraft-Revision"));
    toast("已下载当前结果，未应用的预览不会保存");
  } catch (e) {
    error(e.message);
  }
}
function download(blob, name) {
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
$("tools").innerHTML = TOOLS.map(
  ([name, title, glyph]) =>
    `<button class="tool-button ${name === tool ? "active" : ""}" data-tool="${name}" title="${title}" aria-pressed="${name === tool}">${icon(glyph)}<span>${title}</span></button>`,
).join("");
document
  .querySelectorAll("[data-tool]")
  .forEach((b) =>
    b.addEventListener("click", () => selectTool(b.dataset.tool)),
  );
hydrate();
$("choose-image").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (e) => {
  if (e.target.files[0]) openImage(e.target.files[0]);
});
$("demo-button").addEventListener("click", () => openImage(null, true));
$("save-button").addEventListener("click", save);
$("help-button").addEventListener("click", () => $("help-dialog").showModal());
$("apply-button").addEventListener("click", applyCurrent);
$("undo-button").addEventListener("click", () => travel());
$("redo-button").addEventListener("click", () => travel(true));
$("fit-button").addEventListener("click", () => canvas.fit());
$("actual-button").addEventListener("click", () => canvas.actual());
$("pan-button").addEventListener("click", () => {
  canvas.pan = !canvas.pan;
  $("pan-button").classList.toggle("active", canvas.pan);
});
$("checker").addEventListener("change", (e) => {
  canvas.checker = e.target.checked;
  canvas.draw();
});
$("compare-button").addEventListener("pointerdown", (e) => {
  if (!session) return;
  e.preventDefault();
  e.target.closest("button").setPointerCapture(e.pointerId);
  canvas
    .beginCompare(session.original_url, [
      session.original.width,
      session.original.height,
    ])
    .catch(error);
  $("preview-info").textContent = info(session.original);
  $("preview-badge").textContent = "原图";
});
function endCompare() {
  canvas.endCompare();
  if (preview) {
    $("preview-info").textContent = info(preview.info);
    $("preview-badge").textContent = "未应用";
  } else showAppliedPreview();
}
for (const event of ["pointerup", "pointercancel", "lostpointercapture"])
  $("compare-button").addEventListener(event, endCompare);
$("compare-button").addEventListener("keydown", (e) => {
  if ((e.key === " " || e.key === "Enter") && !e.repeat && session) {
    e.preventDefault();
    canvas.beginCompare(session.original_url, [
      session.original.width,
      session.original.height,
    ]);
  }
});
$("compare-button").addEventListener("keyup", endCompare);
document
  .querySelectorAll(".dialog-close")
  .forEach((b) =>
    b.addEventListener("click", () => b.closest("dialog").close()),
  );
$("theme-button").addEventListener("click", () => {
  document.body.classList.toggle("dark");
  localStorage.setItem(
    "photocraft.theme",
    document.body.classList.contains("dark") ? "dark" : "light",
  );
  canvas.draw();
});
let dragDepth = 0;
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("dragenter", (e) => {
  e.preventDefault();
  if (e.dataTransfer.types.includes("Files")) {
    dragDepth++;
    $("drop-overlay").hidden = false;
  }
});
document.addEventListener("dragleave", () => {
  if (--dragDepth <= 0) {
    dragDepth = 0;
    $("drop-overlay").hidden = true;
  }
});
document.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  $("drop-overlay").hidden = true;
  if (e.dataTransfer.files[0]) openImage(e.dataTransfer.files[0]);
});
document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  const input = ["INPUT", "TEXTAREA", "SELECT"].includes(
      document.activeElement.tagName,
    ),
    key = e.key.toLowerCase();
  if (key === "o") {
    e.preventDefault();
    $("file-input").click();
  } else if (key === "s") {
    e.preventDefault();
    if (!document.querySelector("dialog[open]")) save();
  } else if (key === "z" && !input && !document.querySelector("dialog[open]")) {
    e.preventDefault();
    travel(e.shiftKey);
  } else if (key === "0") {
    e.preventDefault();
    canvas.fit();
  }
});
window.addEventListener("pagehide", (event) => {
  if (session && !event.persisted)
    navigator.sendBeacon(`/api/sessions/${session.id}/close`);
});
window.addEventListener("beforeunload", (e) => {
  if (session?.dirty && session.revision !== savedRevision) {
    e.preventDefault();
    e.returnValue = "";
  }
});
try {
  boot = await api("/api/bootstrap");
  $("version").textContent = boot.version;
  $("version").title = boot.version;
  settings.crop.mode = boot.templates.length ? "t:0" : "free";
  settings.watermark.font = boot.fonts[0]?.id || "";
  settings.watermark.color = boot.watermark_color || settings.watermark.color;
  const theme = localStorage.getItem("photocraft.theme") || boot.theme;
  document.body.classList.toggle("dark", theme === "dark");
  $("service-label").textContent = ["localhost", "127.0.0.1", "[::1]"].includes(
    location.hostname,
  )
    ? "本机服务已连接"
    : "服务端处理";
  panel();
  status("服务已连接 · 选择一张照片开始");
} catch (e) {
  $("service-label").textContent = "服务未连接";
  status("连接失败，请检查服务是否启动");
  error(e.message);
}
