import { icon } from "./icons.js";
import { EditorCanvas } from "./canvas.js";
import { FILTERS, filterParams } from "./filters.js";

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
  ["crop", "裁剪与旋转", "crop"],
  ["brush", "画笔", "brush"],
  ["mosaic", "马赛克", "mosaic"],
  ["blur", "局部模糊", "blur"],
  ["enhance", "调整", "settings"],
  ["filters", "图像增强", "enhance"],
  ["watermark", "水印", "watermark"],
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
  },
  enhance: { ...defaults },
  filters: { preset: null, strength: 100 },
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

let cropFrame = null;
function cropFrameKey() { return session ? JSON.stringify([session.id, session.revision, settings.crop]) : ""; }
const brushModes = { paint: { ...settings.brush }, erase: { ...settings.brush, erase: true } };

function hydrate(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = icon(el.dataset.icon);
  });
}
function status(text, busy = false) {
  $("status").textContent = text;
  $("status").title = text;
  document.body.classList.toggle("busy", busy);
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
function showInfo(id, data, warning = "") {
  const details = info(data);
  const element = $(id);
  element.textContent = details.split("\n")[0] +
    (data?.quality == null ? "" : ` · 质量 ${data.quality}`) +
    (warning ? ` · ${warning}` : "");
  element.title = details + (warning ? "\n" + warning : "");
}
function showCurrent() {
  if (!session) return;
  $("filename").textContent = session.name;
  $("filename").title = `原文件：${info(session.original)}`;
  $("undo-button").disabled = !session.can_undo || applying;
  $("redo-button").disabled = !session.can_redo || applying;
  $("save-button").disabled = false;
  $("compare-button").disabled = false;
}
function showAppliedPreview() {
  if (!session) return;
  showInfo("preview-info", session.current);
}
function updateApply() {
  canvas.blocked = applying;
  const remove = $("remove-marks");
  if (remove) remove.disabled = applying || !session?.can_remove_marks;
  syncGeometryControls();
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
  zoom: (value) => {
    $("zoom").textContent = `${Math.round(value * 100)}%`;
    $("view-size-value").textContent = canvas.autoFit ? "适应窗口" : Math.abs(value - 1) < 0.00001 ? "实际大小" : "自定义缩放";
  },
  crop: (rect) => {
    if (tool !== "crop") return;
    const w = $("crop-width"),
      h = $("crop-height");
    if (w) w.value = rect.w;
    if (h) h.value = rect.h;
    if (session) cropFrame = { key: cropFrameKey(), rect: { ...rect } };
    const summary = $("crop-size-summary");
    const selected = template();
    if (summary) {
      summary.textContent = selected ? `${selected.width} × ${selected.height} px` : `${rect.w} × ${rect.h} px`;
      summary.title = summary.textContent;
    }
    const selectionSize = $("crop-selection-size");
    if (selectionSize) selectionSize.textContent = `取景 ${rect.w} × ${rect.h} px`;
    const preset = $("crop-preset-summary");
    if (preset && settings.crop.mode === "custom") {
      preset.textContent = `自定义比例 ${settings.crop.ratio_w}:${settings.crop.ratio_h}`;
      preset.title = preset.textContent;
    }
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
  return `<div class="range-field"><div class="range-label"><span>${label}</span><output class="range-value" for="field-${name}">${Number(value).toFixed(step < 1 ? 2 : 0)}${suffix}</output></div><input id="field-${name}" data-field="${name}" type="range" min="${min}" max="${max}" step="${step}" value="${value}" style="--range-progress: ${((value - min) / (max - min)) * 100}%" ${extra} aria-label="${label}"></div>`;
}
function strokeParameter(name, label, min, max, step = 1, suffix = "") {
  const value = settings[tool][name];
  const display = name === "opacity" ? `${Math.round(value * 100)}%` : `${value}${suffix}`;
  const id = `stroke-${name}-popover`;
  return `<div class="stroke-parameter"><button type="button" class="stroke-parameter-trigger" popovertarget="${id}" aria-expanded="false" aria-controls="${id}" aria-haspopup="dialog"><span>${label}</span><span class="stroke-parameter-value" data-stroke-value="${name}">${display}</span>${icon("chevron", 12)}</button><div id="${id}" class="stroke-parameter-popover" popover="auto" role="dialog" aria-label="${label}"><div class="range-field"><div class="range-label"><label for="field-${name}">${label}</label><output class="range-value" for="field-${name}" ${name === "opacity" ? 'data-percent="true"' : ""}>${display}</output></div><input id="field-${name}" data-field="${name}" type="range" min="${min}" max="${max}" step="${step}" value="${value}" aria-label="${label}" style="--range-progress:${((value - min) / (max - min)) * 100}%"></div></div></div>`;
}
function brushModePopover(mode, label) {
  const params = brushModes[mode];
  const slider = (name, title, min, max, step, suffix = "") => {
    const id = `brush-${mode}-${name}`;
    const value = params[name];
    const display = name === "opacity" ? `${Math.round(value * 100)}%` : `${value}${suffix}`;
    return `<div class="range-field"><div class="range-label"><label for="${id}">${title}</label><output class="range-value" for="${id}" ${name === "opacity" ? 'data-percent="true"' : ""}>${display}</output></div><input id="${id}" type="range" data-field="${name}" data-brush-mode="${mode}" min="${min}" max="${max}" step="${step}" value="${value}" aria-label="${title}"></div>`;
  };
  const colors = mode === "paint" ? `<div class="brush-colors"><div class="brush-color-row"><label for="brush-paint-color">颜色</label><input id="brush-paint-color" type="color" data-field="color" data-brush-mode="paint" value="${esc(params.color)}" aria-label="画笔颜色"><input type="text" class="brush-color-hex" data-field="color" data-brush-mode="paint" value="${esc(params.color)}" maxlength="7" pattern="#[0-9a-fA-F]{6}" aria-label="画笔颜色十六进制"></div><div class="brush-swatches">${boot.colors.map(value => `<button type="button" class="swatch" data-brush-color="${esc(value)}" style="background:${esc(value)}" aria-label="颜色 ${esc(value)}" aria-pressed="${params.color.toLowerCase() === value.toLowerCase()}"></button>`).join("")}</div></div>` : "";
  const id = `stroke-${mode}-popover`;
  return `<div class="stroke-parameter"><button type="button" class="stroke-parameter-trigger brush-mode-trigger" data-brush-select="${mode}" popovertarget="${id}" aria-controls="${id}" aria-haspopup="dialog" aria-expanded="false" aria-pressed="${settings.brush.erase === (mode === "erase")}">${icon(mode === "paint" ? "brush" : "erase", 17)}<span>${label}</span>${icon("chevron", 12)}</button><div id="${id}" class="stroke-parameter-popover brush-mode-popover" data-brush-mode="${mode}" popover="auto" role="dialog" aria-label="${label}设置">${slider("size", "大小", 1, 100, 1, " px")}${slider("opacity", "不透明度", 0.01, 1, 0.01)}${colors}</div></div>`;
}
function selectBrushMode(mode) {
  brushModes[settings.brush.erase ? "erase" : "paint"] = { ...settings.brush };
  settings.brush = { ...brushModes[mode], erase: mode === "erase" };
  canvas.brush = { ...settings.brush };
  document.querySelectorAll("[data-brush-select]").forEach(button => button.setAttribute("aria-pressed", button.dataset.brushSelect === mode));
}
function positionStrokePopover(popover, button) {
  const rect = button.getBoundingClientRect();
  const filters = popover.id === "filter-presets-popover";
  const width = Math.min(filters ? 640 : 264, window.innerWidth - 24);
  const left = filters ? rect.left : rect.left + rect.width / 2 - width / 2;
  popover.style.left = `${Math.max(12, Math.min(left, window.innerWidth - width - 12))}px`;
  popover.style.top = rect.top < 120 ? `${rect.bottom + 8}px` : "auto";
  popover.style.bottom = rect.top < 120 ? "auto" : `${window.innerHeight - rect.top + 8}px`;
}
function repositionStrokePopovers() {
  document.querySelectorAll(".stroke-parameter-popover:popover-open").forEach(popover => {
    const button = document.querySelector(`[popovertarget="${popover.id}"]`);
    if (button) positionStrokePopover(popover, button);
  });
}
window.addEventListener("resize", repositionStrokePopovers);
window.addEventListener("scroll", repositionStrokePopovers, true);
function check(name, label) {
  return `<label class="check"><input type="checkbox" data-field="${name}" ${settings[tool][name] ? "checked" : ""}>${label}</label>`;
}
function toggle(name, label) {
  return `<button type="button" class="adjust-toggle" data-toggle="${name}" aria-pressed="${Boolean(settings[tool][name])}">${icon("check", 14)}${label}</button>`;
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
function effectPopover(id, label, body, summary = "") {
  return `<div class="stroke-parameter"><button type="button" class="stroke-parameter-trigger" popovertarget="${id}" aria-controls="${id}" aria-haspopup="dialog" aria-expanded="false"><span>${label}</span>${summary ? `<span class="stroke-parameter-value" data-effect-summary="${id === "filter-strength-popover" ? "strength" : "preset"}">${summary}</span>` : ""}${icon("chevron", 12)}</button><div id="${id}" class="stroke-parameter-popover effect-parameter-popover" popover="auto" role="dialog" aria-label="${label}">${body}</div></div>`;
}
function panelRoot() {
  if (["crop", "rotate"].includes(tool)) return $("crop-controls");
  if (["enhance", "filters", "watermark"].includes(tool)) return $("effect-controls");
  return ["brush", "mosaic", "blur"].includes(tool) ? $("stroke-controls") : $("properties");
}
function panel() {
  const names = {
    crop: ["裁剪与旋转", "调整构图与方向，满意后点击「应用」。"],
    rotate: ["裁剪与旋转", "调整构图与方向，满意后点击「应用」。"],
    brush: ["画笔与修正", "在画面上绘制，或擦除为透明。"],
    mosaic: ["马赛克", "沿笔触遮挡画面中的敏感信息。"],
    blur: ["局部模糊", "柔化笔触经过的区域，保留其余细节。"],
    watermark: ["文字水印", "整页重复平铺，预览满意后再应用。"],
    filters: ["图像增强", "选择一种风格，调整强度，满意后点击「应用」。"],
    enhance: ["调整", "让光线、颜色与细节恰到好处。调整自动应用。"],
    compress: ["图像压缩", "调整格式与画质，保持当前像素尺寸。"],
  };
  const [title, description] = names[tool];
  let content = "";
  const geometry = ["crop", "rotate"].includes(tool);
  const s = settings[geometry ? "crop" : tool];
  if (geometry) {
    const t = template();
    const rect = canvas.crop || (cropFrame?.key === cropFrameKey() ? cropFrame.rect : null);
    const width = t?.width || rect?.w || session?.current.width || 295;
    const height = t?.height || rect?.h || session?.current.height || 413;
    const label = t?.name || (s.mode === "custom" ? `自定义比例 ${s.ratio_w}:${s.ratio_h}` : "自由裁剪");
    const popover = (id, name, summary, body) => `<div class="stroke-parameter"><button type="button" class="stroke-parameter-trigger crop-parameter-trigger" popovertarget="${id}" aria-haspopup="dialog" aria-expanded="false" aria-controls="${id}"><span>${name}</span><span class="crop-selection" title="${esc(summary)}" id="${id === "crop-size-popover" ? "crop-size-summary" : "crop-preset-summary"}">${esc(summary)}</span>${icon("chevron", 12)}</button><div id="${id}" class="stroke-parameter-popover crop-parameter-popover" popover="auto" role="dialog" aria-label="${name}">${body}</div></div>`;
    const choices = `<label class="stacked">裁剪方式<select id="crop-mode" aria-label="裁剪方式">${boot.templates.map((preset, i) => `<option value="t:${i}" ${s.mode === `t:${i}` ? "selected" : ""}>${esc(preset.name)}</option>`).join("")}<option value="free" ${s.mode === "free" ? "selected" : ""}>自由裁剪</option><option value="custom" ${s.mode === "custom" ? "selected" : ""}>按比例裁剪</option></select></label><p class="small-hint">选择规格后，在画面中拖动取景框。</p>`;
    let dimensions = "";
    if (t) dimensions = `<div class="two-fields"><label class="stacked">宽度 / px<input type="number" value="${width}" readonly aria-label="模板宽度"></label><label class="stacked">高度 / px<input type="number" value="${height}" readonly aria-label="模板高度"></label></div><p id="crop-selection-size" class="small-hint">取景 ${rect?.w || width} × ${rect?.h || height} px</p><div class="resize-card ${s.allow_resize ? "is-enabled" : ""}"><button type="button" class="resize-control" data-toggle="allow_resize" aria-pressed="${s.allow_resize}" aria-describedby="resize-description resize-quality"><span class="resize-label">允许缩放</span><span class="resize-state">${s.allow_resize ? "已开启" : "已关闭"}</span><span class="resize-switch" aria-hidden="true"></span></button><p id="resize-description" class="resize-description">${s.allow_resize ? "将选区缩放至模板尺寸，灵活调整取景。" : "按模板像素裁剪，保留原始像素。"}</p><p id="resize-quality" class="resize-quality">${icon("info", 14)}<span>放大可能模糊，缩小可能丢失细节。</span></p></div>`;
    else if (s.mode === "custom") dimensions = `<div class="two-fields"><label class="stacked">比例宽<input type="number" min="1" max="30000" data-field="ratio_w" value="${s.ratio_w}" aria-label="比例宽"></label><label class="stacked">比例高<input type="number" min="1" max="30000" data-field="ratio_h" value="${s.ratio_h}" aria-label="比例高"></label></div><p class="small-hint">拖动取景框边角时保持所选比例。</p>`;
    else dimensions = `<div class="two-fields"><label class="stacked">宽度 / px<input id="crop-width" type="number" min="1" max="${session?.current.width || 30000}" value="${width}" aria-label="裁剪宽度"></label><label class="stacked">高度 / px<input id="crop-height" type="number" min="1" max="${session?.current.height || 30000}" value="${height}" aria-label="裁剪高度"></label></div><p class="small-hint">输入像素或拖动取景框，尺寸会同步更新。</p>`;
    let exam = "";
    if (t?.name.startsWith("教师资格考试")) exam = `<p class="small-hint">150 × 200 px 为参考尺寸，请核对报考地当次公告。通常要求白底、JPG/JPEG、不超过 200KB；格式与画质可在「图像压缩」中调整。</p>`;
    if (t?.name.startsWith("国家公务员考试")) exam = `<p class="small-hint">国考源照片宽至少 295 px、高至少 413 px，蓝底或白底，JPG/JPEG。仍需官方照片处理工具；省考请核对当地公告。</p>`;
    content = popover("crop-preset-popover", "裁剪规格", label, choices + exam) +
      popover("crop-size-popover", t ? "尺寸与缩放" : s.mode === "custom" ? "宽高比例" : "裁剪尺寸", `${width} × ${height} px`, dimensions) +
      (tool === "rotate" ? `<button id="resume-crop" class="crop-resume" type="button">${icon("crop", 15)}<span>调整取景</span></button>` : "");
  } else if (tool === "brush") {
    brushModes[s.erase ? "erase" : "paint"] = { ...s };
    content = brushModePopover("paint", "画笔") + brushModePopover("erase", "橡皮擦") +
      `<button type="button" id="remove-marks" class="remove-marks" title="单击撤销上一笔；长按撤销当前连续绘制的全部笔迹" aria-description="单击撤销上一笔，长按撤销当前连续绘制的全部笔迹，不跨越裁剪等其他编辑" ${!session?.can_remove_marks || applying ? "disabled" : ""}>${icon("undo", 15)}<span>移除标记</span></button>`;
  } else if (["mosaic", "blur"].includes(tool)) {
    content = strokeParameter("size", "画笔大小", 1, 100, 1, " px") +
      strokeParameter("opacity", "不透明度", 0.01, 1, 0.01) +
      strokeParameter("block", tool === "mosaic" ? "块大小" : "模糊强度", 2, 100, 1, " px");
  } else if (tool === "watermark") {
    const text = `<label class="field">水印文字<input id="mark-text" type="text" data-field="text" value="${esc(s.text)}" maxlength="50" title="最多 50 字，超长文字不允许。" aria-label="水印文字"></label><label class="stacked">系统字体<select data-field="font" aria-label="系统字体">${boot.fonts.map((f) => `<option value="${f.id}" ${s.font === f.id ? "selected" : ""}>${esc(f.name)}</option>`).join("")}</select></label><p class="small-hint">字体来自服务所在系统，字符支持取决于所选字体。</p>`;
    const colors = `<div class="brush-colors watermark-colors"><div class="brush-color-row"><label for="watermark-color">颜色</label><input id="watermark-color" type="color" data-field="color" data-watermark-color value="${esc(s.color)}" aria-label="水印颜色"><input type="text" class="brush-color-hex" data-field="color" data-watermark-color value="${esc(s.color)}" maxlength="7" pattern="#[0-9a-fA-F]{6}" aria-label="水印颜色十六进制"></div><div class="brush-swatches">${boot.colors.map(value => `<button type="button" class="swatch" data-watermark-swatch="${esc(value)}" style="background:${esc(value)}" aria-label="颜色 ${esc(value)}" aria-pressed="${s.color.toLowerCase() === value.toLowerCase()}"></button>`).join("")}</div></div>`;
    const style = range("size", "字号", 4, 200, 1, " px") + range("opacity", "不透明度", 0.01, 1, 0.01) + colors;
    const layout = range("angle", "倾斜角度", -180, 180, 1, "°") + range("row_spacing", "行间距", 0, 500, 1, " px") + range("column_spacing", "列间距", 0, 500, 1, " px");
    content = `<div class="stroke-fields watermark-fields">${effectPopover("watermark-text-popover", "文字与字体", text)}${effectPopover("watermark-style-popover", "样式", style)}${effectPopover("watermark-layout-popover", "排布", layout)}${check("multiple", "多重水印")}<button id="clear-marks" class="effect-reset" type="button">清除水印</button></div>`;
  } else if (tool === "enhance") {
    const light = `<div class="effect-auto">${toggle("autocontrast", "自动对比度")}</div>` +
      range("brightness", "亮度", 0.1, 3, 0.01) +
      range("contrast", "对比度", 0.1, 3, 0.01, "", s.autocontrast ? "disabled" : "") +
      range("gamma", "伽马", 0.1, 3, 0.01) + range("equalize", "明暗均衡", 0, 1, 0.01);
    const colors = `<div class="effect-auto">${toggle("white_balance", "自动白平衡")}</div>` +
      range("saturation", "饱和度", 0, 3, 0.01) +
      range("temperature", "色温", -1, 1, 0.01, "", s.white_balance ? "disabled" : "");
    const details = range("sharpness", "锐度", 0, 5, 0.01) + range("denoise", "降噪强度", 0, 1, 0.01);
    content = `<div class="stroke-fields">${effectPopover("adjust-light-popover", "光线", light)}${effectPopover("adjust-color-popover", "颜色", colors)}${effectPopover("adjust-detail-popover", "细节", details)}<button id="reset-enhance" class="effect-reset" type="button">${icon("reset", 15)}重置调整</button></div>`;
  } else if (tool === "filters") {
    const selected = FILTERS.find((item) => item.id === s.preset);
    const cards = `<div class="filter-grid" role="group" aria-label="增强模板">${FILTERS.map((item) => `<button type="button" class="filter-card" data-filter="${item.id}" aria-pressed="${s.preset === item.id}" title="${item.hint}" ${session ? "" : "disabled"}><span class="filter-thumbnail" style="--filter-style: ${item.thumbnail}"><img alt="" hidden><span class="filter-placeholder">${icon("image", 24)}</span><span class="filter-selected">${icon("check", 12)}</span></span><span class="filter-name">${item.name}</span></button>`).join("")}</div>`;
    const strength = `<p class="effect-selection" id="filter-selection">${selected?.name || "自定义调整"}</p>${range("strength", "效果强度", 0, 100, 1, "%", !session || !s.preset || s.preset === "none" ? "disabled" : "")}<p class="small-hint">选择模板后先预览，点击「应用」后生效。</p>`;
    content = `<div class="filter-bottom-row">${effectPopover("filter-presets-popover", "滤镜", cards, selected?.name || "自定义")}${effectPopover("filter-strength-popover", "强度", strength, `${s.strength}%`)}</div>`;
  } else if (tool === "compress") {
    const lossy = ["JPEG", "WEBP"].includes(s.format);
    content = `<label class="field">文件格式<select data-field="format" aria-label="文件格式">${["JPEG", "PNG", "WEBP", "BMP", "TIFF"].map((v) => `<option ${v === s.format ? "selected" : ""}>${v}</option>`).join("")}</select></label><p class="small-hint">${lossy ? "适合照片，可通过画质控制文件体积。" : "使用无损编码，保留图像细节。"}</p><div class="card">${check("live", "在画布查看压缩效果")}</div>`;
    if (lossy) content += range("quality", "画质", 1, 100);
    content += `<details><summary>高级设置</summary>${["JPEG", "BMP"].includes(s.format) ? "" : check("keep_alpha", "保留透明背景")}${color("background", "透明区域填充色")}${check("keep_exif", "保留 EXIF（可能含位置）")}${check("keep_icc", "保留 ICC 色彩配置")}</details><p class="small-hint">调整仅预览。应用后，保存才会使用所选格式与画质。</p>`;
  }
  $("properties").classList.toggle("adjust-panel", tool === "enhance" || tool === "filters");
  $("properties").classList.toggle("geometry-panel", geometry);
  const stroke = ["brush", "mosaic", "blur"].includes(tool);
  const effects = ["enhance", "filters", "watermark"].includes(tool);
  document.querySelector(".app-body").classList.toggle("stroke-workspace", stroke || geometry || effects);
  $("properties").hidden = stroke || geometry || effects;
  $("effect-controls").hidden = !effects || !session;
  $("effect-controls").classList.toggle("adjust-panel", effects);
  $("effect-controls").setAttribute("aria-label", `${title}参数`);
  $("crop-controls").hidden = !geometry || !session;
  $("stroke-controls").hidden = !stroke || !session;
  $("stroke-controls").setAttribute("aria-label", `${title}参数`);
  $("stroke-controls").classList.toggle("is-brush", tool === "brush");
  if (effects) {
    $("properties").innerHTML = "";
    $("stroke-controls").innerHTML = "";
    $("crop-controls").innerHTML = "";
    $("effect-controls").innerHTML = content;
  } else if (geometry) {
    $("effect-controls").innerHTML = "";
    $("properties").innerHTML = "";
    $("stroke-controls").innerHTML = "";
    $("crop-controls").innerHTML = `<div class="stroke-fields">${content}</div>`;
  } else if (stroke) {
    $("effect-controls").innerHTML = "";
    $("crop-controls").innerHTML = "";
    $("properties").innerHTML = "";
    $("stroke-controls").innerHTML = `<div class="stroke-fields">${content}</div>`;
  } else {
    $("effect-controls").innerHTML = "";
    $("crop-controls").innerHTML = "";
    $("stroke-controls").innerHTML = "";
    $("properties").innerHTML = `<h2>${title}</h2><p class="panel-description">${description}</p>${tool === "rotate" ? '<button id="resume-crop" class="full-button" type="button">调整裁剪框</button>' : ""}${content}`;
  }
  syncGeometryControls();
  wirePanel();
  if (tool === "filters") loadFilterThumbnails();
  updateApply();
}
let filterThumbnail = { key: "", src: "" };
async function loadFilterThumbnails() {
  if (!session) return;
  const key = session.image_url;
  try {
    if (filterThumbnail.key !== key) {
      const image = new Image();
      image.src = key;
      await image.decode();
      if (session?.image_url !== key || tool !== "filters") return;
      const thumb = document.createElement("canvas");
      thumb.width = 240;
      thumb.height = Math.max(1, Math.round(240 * image.naturalHeight / image.naturalWidth));
      // Bound both dimensions for unusually tall photos.
      if (thumb.height > 240) {
        thumb.width = Math.max(1, Math.round(240 * image.naturalWidth / image.naturalHeight));
        thumb.height = 240;
      }
      thumb.getContext("2d").drawImage(image, 0, 0, thumb.width, thumb.height);
      filterThumbnail = { key, src: thumb.toDataURL("image/png") };
    }
    panelRoot().querySelectorAll(".filter-thumbnail img").forEach((image) => {
      image.src = filterThumbnail.src;
      image.hidden = false;
      image.nextElementSibling.hidden = true;
    });
  } catch {
    // The placeholders remain usable if the current preview cannot be loaded.
  }
}
function syncFilterSelection() {
  if (!session) return;
  const matches = (params) => params && Object.keys(defaults).every(
    (key) => Math.abs(Number(params[key]) - Number(session.enhancement[key])) < 0.00001,
  );
  if (matches(filterParams(settings.filters.preset, settings.filters.strength, defaults))) return;
  settings.filters = {
    preset: FILTERS.find((item) => matches(filterParams(item.id, 100, defaults)))?.id || null,
    strength: 100,
  };
}
function wirePanel() {
  wireRemoveMarks();
  panelRoot().querySelectorAll(".stroke-parameter-trigger").forEach(button => {
    const popover = $(button.getAttribute("popovertarget"));
    popover.addEventListener("beforetoggle", event => {
      button.setAttribute("aria-expanded", event.newState === "open");
      if (event.newState === "open") {
        if (button.dataset.brushSelect) selectBrushMode(button.dataset.brushSelect);
        positionStrokePopover(popover, button);
      }
    });
  });
  panelRoot().querySelectorAll(".stroke-parameter-popover").forEach(popover => {
    popover.addEventListener("toggle", () => {
      if (!popover.matches(":popover-open")) return;
      if (popover.getBoundingClientRect().top < 12) {
        popover.style.top = "12px";
        popover.style.bottom = "auto";
      }
    });
  });
  panelRoot().querySelectorAll("[data-brush-color]").forEach(button => {
    button.addEventListener("click", () => {
      const input = $("brush-paint-color");
      input.value = button.dataset.brushColor;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });
  panelRoot().querySelectorAll("[data-watermark-swatch]").forEach(button => {
    button.addEventListener("click", () => {
      const input = $("watermark-color");
      input.value = button.dataset.watermarkSwatch;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });
  panelRoot().querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      settings.filters.preset = button.dataset.filter;
      gesture = uid();
      panel();
      $("filter-presets-popover").showPopover();
      panelRoot().querySelector(`[data-filter="${settings.filters.preset}"]`)?.focus();
      schedule();
    });
  });
  panelRoot().querySelectorAll("[data-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const name = button.dataset.toggle;
      const target = tool === "rotate" && name === "allow_resize" ? "crop" : tool;
      settings[target][name] = !settings[target][name];
      if (target !== tool) { selectTool(target); return; }
      gesture = uid();
      const openId = button.closest("[popover]")?.id;
      panel();
      if (openId) $(openId)?.showPopover();
      panelRoot().querySelector(`[data-toggle="${name}"]`)?.focus();
      if (tool === "crop") resetCrop();
      else schedule();
    });
  });
  panelRoot()
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
          if (tool === "rotate") { settings.crop[key] = value; selectTool("crop"); return; }
          if (input.dataset.brushMode) {
            if (key === "color" && !/^#[0-9a-fA-F]{6}$/.test(value)) return;
            brushModes[input.dataset.brushMode][key] = value;
            if (key === "color") {
              panelRoot().querySelectorAll('[data-brush-mode="paint"][data-field="color"]').forEach(field => { if (field !== input) field.value = value; });
              panelRoot().querySelectorAll("[data-brush-color]").forEach(button => button.setAttribute("aria-pressed", button.dataset.brushColor.toLowerCase() === value.toLowerCase()));
            }
          }
          if (input.hasAttribute("data-watermark-color")) {
            if (!/^#[0-9a-fA-F]{6}$/.test(value)) return;
            value = value.toLowerCase();
            panelRoot().querySelectorAll("[data-watermark-color]").forEach(field => { if (field !== input) field.value = value; });
            panelRoot().querySelectorAll("[data-watermark-swatch]").forEach(button => button.setAttribute("aria-pressed", button.dataset.watermarkSwatch.toLowerCase() === value));
          }
          settings[tool][key] = value;
          if (input.type === "range") input.style.setProperty("--range-progress", `${((value - Number(input.min)) / (Number(input.max) - Number(input.min))) * 100}%`);
          const output =
            input.parentElement.querySelector("output") ||
            input.closest(".range-field")?.querySelector("output");
          if (output) {
            const suffix = output.textContent.match(/(?: px|°|%)$/)?.[0] || "";
            output.textContent = output.dataset.percent
              ? `${Math.round(Number(value) * 100)}%`
              : Number(value).toFixed(Number(input.step) < 1 ? 2 : 0) + suffix;
            const triggerValue = panelRoot().querySelector(`[data-stroke-value="${key}"]`);
            if (triggerValue) triggerValue.textContent = output.textContent;
            const effectValue = panelRoot().querySelector(`[data-effect-summary="${key}"]`);
            if (effectValue) effectValue.textContent = output.textContent;
          }
          if (tool === "crop") {
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
    if (tool !== "crop") { selectTool("crop"); return; }
    panel();
    resetCrop();
  });
  $("resume-crop")?.addEventListener("click", () => selectTool("crop"));
  for (const id of ["crop-width", "crop-height"])
    $(id)?.addEventListener("change", async () => {
      const width = Number($("crop-width").value), height = Number($("crop-height").value);
      if (tool !== "crop") await selectTool("crop");
      canvas.cropPixels(width, height);
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
  panelRoot()
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
      status("水印文字超长，不允许超过 50 字。");
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
      status("水印文字超长，不允许超过 50 字。");
    }
  });
}
function syncGeometryControls() {
  const visible = Boolean(session && ["crop", "rotate"].includes(tool));
  $("geometry-controls").hidden = !visible;
  if (!visible) return;
  const rotation = settings.rotate;
  $("straighten-angle").value = rotation.angle;
  $("straighten-angle").setAttribute("aria-valuetext", `${rotation.angle} 度`);
  for (const flip of ["horizontal", "vertical"])
    $(`flip-${flip}`).setAttribute("aria-pressed", rotation.flip === flip || rotation.flip === "both");
  $("geometry-controls").querySelectorAll("button, input").forEach(el => el.disabled = applying);
  $("crop-controls").querySelectorAll("button, input, select").forEach(el => el.disabled = applying);
}
let rotationPreviewing = false;
let rotationPreviewAt = -Infinity;
const ROTATION_PREVIEW_MS = 280;
async function editGeometry(update, paced = false) {
  if (!session || applying) return;
  if (tool !== "rotate") await selectTool("rotate");
  if (!paced) rotationPreviewing = false;
  update(settings.rotate);
  settings.rotate.angle = wrapAngle(settings.rotate.angle);
  syncGeometryControls();
  schedule(paced && !rotationPreviewing ? 0 : 230, paced && rotationPreviewing);
}
$("straighten-angle").addEventListener("input", e => {
  const value = Number(e.target.value);
  rotationPreviewing = true;
  editGeometry(rotation => rotation.angle = value, true);
});
$("straighten-angle").addEventListener("change", () => {
  rotationPreviewing = false;
  if (tool === "rotate") schedule(0);
});
$("straighten-angle").addEventListener("pointercancel", () => {
  rotationPreviewing = false;
  if (tool === "rotate") schedule(0);
});
for (const [id, delta] of [["rotate-left", 1], ["rotate-right", -1]])
  $(id).addEventListener("click", () => editGeometry(rotation => rotation.angle += delta * 90));
for (const flip of ["horizontal", "vertical"])
  $(`flip-${flip}`).addEventListener("click", () => editGeometry(rotation => {
    const horizontal = rotation.flip === "horizontal" || rotation.flip === "both";
    const vertical = rotation.flip === "vertical" || rotation.flip === "both";
    const h = flip === "horizontal" ? !horizontal : horizontal;
    const v = flip === "vertical" ? !vertical : vertical;
    rotation.flip = h && v ? "both" : h ? "horizontal" : v ? "vertical" : null;
  }));

function wrapAngle(v) {
  while (v > 180) v -= 360;
  while (v < -180) v += 360;
  return v;
}
function operation() {
  if (!session || !draftActive) return null;
  let params = { ...settings[tool] };
  if (tool === "filters") {
    params = filterParams(settings.filters.preset, settings.filters.strength, defaults);
    return params ? { revision: session.revision, tool: "enhance", params } : null;
  }
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
  if (tool === "rotate") params = { angle: settings.rotate.angle, flip: settings.rotate.flip, expand: true };
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
  return tool !== "compress" || settings.compress.live;
}
function schedule(delay = 230, paced = false) {
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
  $("preview-info").textContent = "正在计算预览实测…";
  if (running) pending = true;
  else timer = setTimeout(() => runPreview(), paced ? Math.max(0, ROTATION_PREVIEW_MS - (performance.now() - rotationPreviewAt)) : delay);
}
async function acceptApplied(result, seq, { fit = false, reset = false } = {}) {
  if (!session || result.id !== session.id) return;
  const latest = seq === draftSeq;
  session = result;
  if (latest && tool === "filters") settings.enhance = { ...session.enhancement };
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
    syncFilterSelection();
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
  if (activeTool === "rotate") rotationPreviewAt = performance.now();
  status("正在生成预览…", true);
  pending = false;
  running = (async () => {
    try {
      const response = await api(`/api/sessions/${sid}/preview`, {
        method: "POST",
        body,
      });
      if (!session || session.id !== sid) return null;
      if (seq !== draftSeq) {
        // A paced rotation preview may finish while the user is still dragging.
        // Display it without making it eligible for Apply; the latest request
        // remains queued, and only an exact revision can be committed.
        if (activeTool === "rotate" && tool === "rotate" && rotationPreviewing &&
            activeGesture === gesture && body.revision === session.revision && !canvas.compareState) {
          showInfo("preview-info", response.info, response.warning);
          await canvas.setImage(response.image_url, [response.info.width, response.info.height]);
        }
        return null;
      }
      preview = { ...response, seq };
      showInfo("preview-info", response.info, response.warning);

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
      return response;
    } catch (e) {
      if (session?.id === sid && seq === draftSeq) {
        $("preview-info").textContent = e.message;
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
    if (pending && session) {
      pending = false;
      timer = setTimeout(() => runPreview(), tool === "rotate" && rotationPreviewing ? Math.max(0, ROTATION_PREVIEW_MS - (performance.now() - rotationPreviewAt)) : 80);
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
        expand: true,
      };
      panel();
    }
    status(tool === "filters" ? `已应用「${FILTERS.find((item) => item.id === settings.filters.preset)?.name || "模板"}」，保存将使用此结果` : "已应用，保存将使用当前结果");
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
function wireRemoveMarks() {
  const button = $("remove-marks");
  if (!button) return;
  let holdTimer = null, held = false, start = null;
  const cancel = () => { clearTimeout(holdTimer); holdTimer = null; button.classList.remove("is-holding"); };
  const begin = () => {
    if (button.disabled) return;
    cancel(); held = false;
    button.classList.add("is-holding");
    holdTimer = setTimeout(() => { held = true; cancel(); removeMarks(true); }, 700);
  };
  button.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    start = { x: event.clientX, y: event.clientY };
    button.setPointerCapture(event.pointerId);
    begin();
  });
  button.addEventListener("pointermove", event => {
    if (holdTimer && start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 12) { cancel(); held = true; }
  });
  button.addEventListener("pointerup", cancel);
  button.addEventListener("pointercancel", () => { cancel(); held = true; });
  button.addEventListener("lostpointercapture", cancel);
  button.addEventListener("blur", cancel);
  button.addEventListener("contextmenu", event => event.preventDefault());
  button.addEventListener("click", event => {
    event.preventDefault();
    if (!held) removeMarks(false);
  });
  button.addEventListener("keydown", event => {
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    if (!event.repeat) begin();
  });
  button.addEventListener("keyup", event => {
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault(); cancel();
    if (!held) removeMarks(false);
  });
}
async function removeMarks(all = false) {
  if (!session?.can_remove_marks || applying) return;
  clearTimeout(timer); pending = false; draftSeq++; draftActive = false;
  applying = true; updateApply();
  try {
    while (running) await running;
    const result = await api(endpoint("remove-strokes"), { method: "POST", body: { revision: session.revision, all } });
    await acceptApplied(result, draftSeq, { reset: true });
    status(all ? "已移除当前全部连续笔迹" : "已移除上一笔");
  } catch (e) { error(e.message); }
  finally { applying = false; updateApply(); showCurrent(); }
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
    status(redo ? "已重做" : "已撤销");
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
  if (name !== "rotate") rotationPreviewing = false;
  clearTimeout(timer);
  draftSeq++;
  pending = false;
  preview = null;
  if (tool === "rotate" && name !== tool)
    settings.rotate = { angle: 0, flip: null, expand: true };
  tool = name;
  if (tool === "filters") syncFilterSelection();
  if (tool === "enhance" && session) settings.enhance = { ...session.enhancement };
  gesture = uid();
  canvas.setTool(tool);
  canvas.localImage = null;
  document.querySelectorAll(".tool-button").forEach((el) => {
    el.classList.toggle("active", el.dataset.tool === (tool === "rotate" ? "crop" : tool));
    el.setAttribute("aria-pressed", el.dataset.tool === (tool === "rotate" ? "crop" : tool));
  });
  panel();
  if (!session) return;
  draftActive = !["brush", "mosaic", "blur", "enhance", "filters"].includes(tool);
  await canvas.setImage(session.image_url, [
    session.current.width,
    session.current.height,
  ]);
  if (tool === "crop") {
    const retained = cropFrame?.key === cropFrameKey() ? cropFrame.rect : null;
    resetCrop();
    if (retained) { canvas.crop = { ...retained }; canvas.emitCrop(); canvas.draw(); }
  } else canvas.crop = null;
  if (["brush", "mosaic", "blur"].includes(tool))
    canvas.brush = { ...settings[tool] };
  if (draftActive) schedule();
  else showAppliedPreview();
  status(`${TOOLS.find((t) => t[0] === (tool === "rotate" ? "crop" : tool))[1]} · 当前服务处理`);
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
    syncFilterSelection();
    settings.compress = { ...settings.compress, ...session.compression };
    filterThumbnail = { key: "", src: "" };
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
async function savedImage() {
  const result = await fetch(endpoint("download"));
  if (!result.ok) throw new Error("保存失败，请重试。");
  return {
    blob: await result.blob(),
    name: decodeURIComponent((result.headers.get("Content-Disposition") || "").match(/filename\*=UTF-8''(.+)/)?.[1] || "photocraft.png"),
    revision: Number(result.headers.get("X-PhotoCraft-Revision")),
  };
}
async function save() {
  if (!session) return;
  try {
    const image = await savedImage();
    download(image.blob, image.name);
    savedRevision = image.revision;
    status("已下载当前结果，未应用的预览不会保存");
  } catch (e) { error(e.message); }
}
function suggestedName() {
  const ext = {JPEG:"jpg", PNG:"png", WEBP:"webp", BMP:"bmp", TIFF:"tiff"}[session.current.format] || "png";
  return session.name.replace(/\.[^.]+$/, "") + "-edited." + ext;
}
async function saveAs() {
  if (!session) return;
  if (!window.showSaveFilePicker) {
    $("save-as-name").value = suggestedName();
    $("save-as-dialog").showModal();
    $("save-as-name").select();
    return;
  }
  try {
    const handle = await window.showSaveFilePicker({suggestedName: suggestedName()});
    const image = await savedImage();
    const writable = await handle.createWritable();
    await writable.write(image.blob);
    await writable.close();
    savedRevision = image.revision;
    status("已另存当前结果");
  } catch (e) { if (e.name !== "AbortError") error(e.message); }
}
async function copyImage() {
  if (!session) return;
  try {
    if (!navigator.clipboard?.write || !window.ClipboardItem)
      throw new Error("此浏览器暂不支持复制图片，请使用 HTTPS 或本机地址访问，或选择保存图片。");
    const png = fetch(endpoint("clipboard")).then(async response => {
      if (!response.ok) throw new Error("复制失败，请重试。");
      return response.blob();
    });
    await navigator.clipboard.write([new ClipboardItem({"image/png": png})]);
    status("已复制当前图片，未应用的预览不会复制");
  } catch (e) { error(e.message); }
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
if (/Mac|iPhone|iPad/.test(navigator.platform)) $("save-as-shortcut").textContent = "⌘+Shift+S";
$("choose-image").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (e) => {
  if (e.target.files[0]) openImage(e.target.files[0]);
});
$("demo-button").addEventListener("click", () => openImage(null, true));
$("save-menu").addEventListener("beforetoggle", e => {
  if (e.newState !== "open") return;
  const rect = $("save-button").getBoundingClientRect();
  $("save-menu").style.left = `${Math.max(8, Math.min(rect.right - 220, innerWidth - 228))}px`;
  $("save-menu").style.top = `${rect.bottom + 6}px`;
});
for (const [id, action] of [["save-default", save], ["save-as", saveAs], ["copy-image", copyImage]]) {
  $(id).addEventListener("click", () => { $("save-menu").hidePopover(); action(); });
}
$("save-as-form").addEventListener("submit", async e => {
  e.preventDefault();
  const chosen = $("save-as-name").value.trim().replace(/[\\/]/g, "_");
  if (!chosen) return;
  try {
    const image = await savedImage();
    const ext = image.name.split(".").pop();
    download(image.blob, chosen.toLowerCase().endsWith("." + ext) ? chosen : chosen + "." + ext);
    savedRevision = image.revision;
    $("save-as-dialog").close();
    status("已另存当前结果");
  } catch (err) { error(err.message); }
});
$("help-button").addEventListener("click", () => $("help-dialog").showModal());
$("apply-button").addEventListener("click", applyCurrent);
$("undo-button").addEventListener("click", () => travel());
$("redo-button").addEventListener("click", () => travel(true));
$("view-size-menu").addEventListener("beforetoggle", e => {
  if (e.newState !== "open") return;
  const rect = $("view-size-button").getBoundingClientRect();
  $("view-size-menu").style.left = `${Math.max(8, Math.min(rect.left, innerWidth - 228))}px`;
  $("view-size-menu").style.top = `${rect.bottom + 6}px`;
});
$("fit-button").addEventListener("click", () => { $("view-size-menu").hidePopover(); canvas.fit(); });
$("actual-button").addEventListener("click", () => { $("view-size-menu").hidePopover(); canvas.actual(); });
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
  showInfo("preview-info", session.original);
});
function endCompare() {
  canvas.endCompare();
  if (preview) {
    showInfo("preview-info", preview.info);
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
    if (!e.repeat && !document.querySelector("dialog[open]")) {
      $("save-menu").hidePopover();
      if (e.shiftKey) saveAs();
      else save();
    }
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
