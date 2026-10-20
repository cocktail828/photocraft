import { blurThumbnail } from "./blur.js";
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export class EditorCanvas {
  constructor(element, callbacks) {
    this.el = element;
    this.ctx = element.getContext("2d");
    this.callbacks = callbacks;
    this.image = null;
    this.width = 0;
    this.height = 0;
    this.scale = 1;
    this.x = 0;
    this.y = 0;
    this.tool = "crop";
    this.crop = null;
    this.ratio = null;
    this.fixed = false;
    this.pan = false;
    this.space = false;
    this.drag = null;
    this.compareState = null;
    this.loadId = 0;
    this.brush = {
      size: 30,
      opacity: 1,
      color: "#ffffff",
      block: 12,
      erase: false,
    };
    new ResizeObserver(() => {
      if (this.image && this.autoFit) this.fit();
      else this.draw();
    }).observe(element.parentElement);
    element.addEventListener(
      "wheel",
      (e) => {
        if (!this.image) return;
        e.preventDefault();
        this.autoFit = false;
        const p = this.position(e);
        this.zoomAt(this.scale * (e.deltaY < 0 ? 1.12 : 1 / 1.12), p.x, p.y);
      },
      { passive: false },
    );
    element.addEventListener("pointerdown", (e) => this.down(e));
    element.addEventListener("pointermove", (e) => this.move(e));
    element.addEventListener("pointerup", (e) => this.up(e));
    element.addEventListener("pointercancel", (e) => this.up(e));
    window.addEventListener("keydown", (e) => {
      if (
        e.code === "Space" &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(
          document.activeElement.tagName,
        )
      ) {
        this.space = true;
        e.preventDefault();
      }
    });
    window.addEventListener("keyup", (e) => {
      if (e.code === "Space") this.space = false;
    });
    window.addEventListener("blur", () => {
      this.space = false;
      this.drag = null;
    });
  }
  async setImage(url, size, fit = false) {
    const id = ++this.loadId;
    if (
      this.url === url &&
      this.image &&
      this.width === size[0] &&
      this.height === size[1] &&
      !this.compareState
    ) {
      if (fit) this.fit();
      else this.draw();
      return;
    }
    const image = new Image();
    image.src = url;
    await image.decode();
    if (id !== this.loadId || this.compareState) return;
    const changed = this.width !== size[0] || this.height !== size[1];
    this.image = image;
    this.url = url;
    [this.width, this.height] = size;
    this.localImage = null;
    if (fit || changed || !this.initialized) {
      this.initialized = true;
      this.fit();
    } else this.draw();
  }
  fit() {
    if (!this.image) return;
    const box = this.el.getBoundingClientRect();
    this.scale = Math.min(
      (box.width - 56) / this.width,
      (box.height - 46) / this.height,
    );
    this.x = (box.width - this.width * this.scale) / 2;
    this.y = (box.height - this.height * this.scale) / 2;
    this.autoFit = true;
    this.draw();
    this.callbacks.zoom(this.scale);
  }
  zoomAt(value, x, y) {
    value = clamp(value, 0.01, 32);
    const dx = (x - this.x) / this.scale,
      dy = (y - this.y) / this.scale;
    this.x = x - dx * value;
    this.y = y - dy * value;
    this.scale = value;
    this.draw();
    this.callbacks.zoom(value);
  }
  actual() {
    this.autoFit = false;
    const box = this.el.getBoundingClientRect();
    this.zoomAt(1, box.width / 2, box.height / 2);
  }
  setTool(tool) {
    this.tool = tool;
    this.pan = false;
    this.draw();
  }
  setCrop(mode, size, allowResize, ratio = null) {
    if (!this.width) return;
    this.fixed = Array.isArray(size) && !allowResize;
    this.ratio = size ? size[0] / size[1] : mode === "custom" ? ratio : null;
    let w = this.width * 0.88,
      h = this.height * 0.88;
    if (this.fixed && size[0] <= this.width && size[1] <= this.height) {
      [w, h] = size;
    } else if (this.ratio) {
      w = Math.min(w, h * this.ratio);
      h = w / this.ratio;
    }
    this.crop = {
      x: Math.round((this.width - w) / 2),
      y: Math.round((this.height - h) / 2),
      w: Math.round(w),
      h: Math.round(h),
    };
    this.emitCrop();
    this.draw();
  }
  cropPixels(w, h) {
    if (!this.crop) return;
    w = clamp(Math.round(w), 1, this.width);
    h = clamp(Math.round(h), 1, this.height);
    this.crop = {
      x: clamp(
        Math.round(this.crop.x + (this.crop.w - w) / 2),
        0,
        this.width - w,
      ),
      y: clamp(
        Math.round(this.crop.y + (this.crop.h - h) / 2),
        0,
        this.height - h,
      ),
      w,
      h,
    };
    this.emitCrop();
    this.draw();
  }
  emitCrop() {
    if (this.crop) this.callbacks.crop({ ...this.crop });
  }
  position(e) {
    const r = this.el.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }
  source(p) {
    return {
      x: clamp((p.x - this.x) / this.scale, 0, this.width),
      y: clamp((p.y - this.y) / this.scale, 0, this.height),
    };
  }
  handles() {
    if (!this.crop) return [];
    const r = this.crop;
    return [
      [r.x, r.y],
      [r.x + r.w / 2, r.y],
      [r.x + r.w, r.y],
      [r.x + r.w, r.y + r.h / 2],
      [r.x + r.w, r.y + r.h],
      [r.x + r.w / 2, r.y + r.h],
      [r.x, r.y + r.h],
      [r.x, r.y + r.h / 2],
    ];
  }
  down(e) {
    if (!this.image || this.compareState || this.blocked) return;
    if (e.button !== 0 && e.button !== 1) return;
    this.el.focus();
    this.el.setPointerCapture(e.pointerId);
    const p = this.position(e),
      s = this.source(p);
    if (this.pan || this.space || e.button === 1) {
      this.drag = { type: "pan", p, x: this.x, y: this.y };
      this.autoFit = false;
      return;
    }
    if (this.tool === "crop" && this.crop) {
      const handle = this.fixed
        ? -1
        : this.handles().findIndex(
            ([x, y]) => Math.hypot(x - s.x, y - s.y) * this.scale < 10,
          );
      this.drag = { type: "crop", s, rect: { ...this.crop }, handle };
      return;
    }
    if (["brush", "mosaic", "blur"].includes(this.tool)) {
      if (
        p.x < this.x ||
        p.y < this.y ||
        p.x > this.x + this.width * this.scale ||
        p.y > this.y + this.height * this.scale
      )
        return;
      this.drag = {
        type: "stroke",
        points: [[s.x, s.y]],
        brush: { ...this.brush },
      };
      this.paintLocal();
      this.draw();
    }
  }
  move(e) {
    const p = this.position(e),
      s = this.source(p),
      d = this.drag;
    this.el.style.cursor = this.compareState
      ? "default"
      : this.pan || this.space
        ? "grab"
        : ["brush", "mosaic", "blur"].includes(this.tool)
          ? "crosshair"
          : this.tool === "crop" && this.crop
            ? "move"
            : "default";
    if (!d) return;
    if (d.type === "pan") {
      this.x = d.x + p.x - d.p.x;
      this.y = d.y + p.y - d.p.y;
    }
    if (d.type === "stroke") {
      const last = d.points[d.points.length - 1];
      if (
        Math.hypot(s.x - last[0], s.y - last[1]) * this.scale > 1 &&
        d.points.length < 5000
      ) {
        d.points.push([s.x, s.y]);
      }
      this.scheduleStroke();
      return;
    }
    if (d.type === "crop") {
      const r = d.rect,
        dx = s.x - d.s.x,
        dy = s.y - d.s.y;
      if (d.handle < 0) {
        this.crop = {
          ...r,
          x: Math.round(clamp(r.x + dx, 0, this.width - r.w)),
          y: Math.round(clamp(r.y + dy, 0, this.height - r.h)),
        };
      } else {
        const i = d.handle;
        let left = [0, 6, 7].includes(i) ? s.x : r.x,
          top = [0, 1, 2].includes(i) ? s.y : r.y;
        const right = [2, 3, 4].includes(i) ? s.x : r.x + r.w,
          bottom = [4, 5, 6].includes(i) ? s.y : r.y + r.h;
        let w = Math.max(1, right - left),
          h = Math.max(1, bottom - top);
        if (this.ratio) {
          if ([1, 5].includes(i)) {
            w = h * this.ratio;
            left = r.x + (r.w - w) / 2;
          } else {
            h = w / this.ratio;
            if ([3, 7].includes(i)) top = r.y + (r.h - h) / 2;
            else if ([0, 2].includes(i)) top = r.y + r.h - h;
          }
          const factor = Math.min(1, this.width / w, this.height / h);
          w *= factor;
          h *= factor;
        }
        w = clamp(Math.round(w), 1, this.width);
        h = clamp(Math.round(h), 1, this.height);
        this.crop = {
          x: Math.round(clamp(left, 0, this.width - w)),
          y: Math.round(clamp(top, 0, this.height - h)),
          w,
          h,
        };
      }
      this.emitCrop();
    }
    this.draw();
  }
  up(e) {
    const d = this.drag;
    if (d?.type === "stroke") {
      cancelAnimationFrame(this.strokeFrame);
      this.strokeFrame = null;
      this.paintLocal();
    }
    this.drag = null;
    if (this.el.hasPointerCapture(e.pointerId))
      this.el.releasePointerCapture(e.pointerId);
    if (d?.type === "stroke")
      this.callbacks.stroke({ points: d.points, ...d.brush });
    this.draw();
  }
  scheduleStroke() {
    if (this.strokeFrame) return;
    this.strokeFrame = requestAnimationFrame(() => {
      this.strokeFrame = null;
      if (this.drag?.type !== "stroke") return;
      this.paintLocal();
      this.draw();
    });
  }
  paintLocal() {
    const d = this.drag;
    if (!d || d.painted === d.points.length) return;
    const scale = this.image.naturalWidth / this.width;
    const make = () => {
      const c = document.createElement("canvas");
      c.width = this.image.naturalWidth;
      c.height = this.image.naturalHeight;
      return c;
    };
    if (!d.surface) {
      d.surface = make();
      d.surface.getContext("2d").drawImage(this.image, 0, 0);
      d.mask = make();
      d.overlay = make();
      d.painted = 0;
    }
    const points = d.points.slice(Math.max(0, d.painted - 1));
    const pad = d.brush.size * scale / 2 + 2;
    const xs = points.map(([x]) => x * scale), ys = points.map(([, y]) => y * scale);
    const x = Math.max(0, Math.floor(Math.min(...xs) - pad));
    const y = Math.max(0, Math.floor(Math.min(...ys) - pad));
    const w = Math.min(d.surface.width, Math.ceil(Math.max(...xs) + pad)) - x;
    const h = Math.min(d.surface.height, Math.ceil(Math.max(...ys) + pad)) - y;
    const mc = d.mask.getContext("2d");
    mc.strokeStyle = mc.fillStyle = "#fff";
    mc.lineWidth = d.brush.size * scale;
    mc.lineCap = mc.lineJoin = "round";
    mc.beginPath();
    points.forEach(([px, py], i) => i ? mc.lineTo(px * scale, py * scale) : mc.moveTo(px * scale, py * scale));
    if (points.length === 1) {
      mc.arc(xs[0], ys[0], d.brush.size * scale / 2, 0, Math.PI * 2);
      mc.fill();
    } else mc.stroke();
    d.painted = d.points.length;
    if (w <= 0 || h <= 0) return;
    const oc = d.overlay.getContext("2d"), ctx = d.surface.getContext("2d");
    oc.globalCompositeOperation = "source-over";
    oc.clearRect(x, y, w, h);
    if (this.tool === "brush") {
      oc.fillStyle = d.brush.color;
      oc.fillRect(x, y, w, h);
    } else {
      const key = `${this.tool}:${d.brush.block}`;
      if (this.effectCache?.image !== this.image || this.effectCache.key !== key) {
        const effect = make(), ec = effect.getContext("2d");
        if (this.tool === "blur") {
          ec.drawImage(this.image, 0, 0);
          blurThumbnail(effect, d.brush.block * scale / 2);
        } else {
          const small = document.createElement("canvas");
          small.width = Math.max(1, Math.ceil(this.width / d.brush.block));
          small.height = Math.max(1, Math.ceil(this.height / d.brush.block));
          small.getContext("2d").drawImage(this.image, 0, 0, small.width, small.height);
          ec.imageSmoothingEnabled = false;
          ec.drawImage(small, 0, 0, small.width * d.brush.block * scale, small.height * d.brush.block * scale);
        }
        this.effectCache = { image: this.image, key, canvas: effect };
      }
      oc.drawImage(this.effectCache.canvas, x, y, w, h, x, y, w, h);
    }
    oc.globalCompositeOperation = "destination-in";
    oc.drawImage(d.mask, x, y, w, h, x, y, w, h);
    ctx.clearRect(x, y, w, h);
    ctx.drawImage(this.image, x, y, w, h, x, y, w, h);
    ctx.globalCompositeOperation = this.tool === "brush" && d.brush.erase ? "destination-out" : "source-over";
    ctx.globalAlpha = d.brush.opacity;
    ctx.drawImage(d.overlay, x, y, w, h, x, y, w, h);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    this.localImage = d.surface;
  }
  draw() {
    const r = this.el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const dpr = window.devicePixelRatio || 1;
    if (
      this.el.width !== Math.round(r.width * dpr) ||
      this.el.height !== Math.round(r.height * dpr)
    ) {
      this.el.width = Math.round(r.width * dpr);
      this.el.height = Math.round(r.height * dpr);
    }
    const c = this.ctx;
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, r.width, r.height);
    if (!this.image) return;
    const w = this.width * this.scale,
      h = this.height * this.scale;
    c.save();
    c.beginPath();
    c.rect(this.x, this.y, w, h);
    c.clip();
    c.fillStyle = document.body.classList.contains("dark") ? "#273244" : "#fff";
    c.fillRect(this.x, this.y, w, h);
    c.drawImage(this.localImage || this.image, this.x, this.y, w, h);
    c.restore();
    if (this.tool === "crop" && this.crop && !this.compareState) {
      const a = this.crop,
        x = this.x + a.x * this.scale,
        y = this.y + a.y * this.scale,
        cw = a.w * this.scale,
        ch = a.h * this.scale;
      c.fillStyle = "#14203380";
      c.beginPath();
      c.rect(this.x, this.y, w, h);
      c.rect(x, y, cw, ch);
      c.fill("evenodd");
      c.strokeStyle = "#fff";
      c.lineWidth = 1.3;
      c.strokeRect(x, y, cw, ch);
      c.strokeStyle = "#ffffff70";
      c.lineWidth = 0.7;
      for (let i = 1; i < 3; i++) {
        c.beginPath();
        c.moveTo(x + (cw * i) / 3, y);
        c.lineTo(x + (cw * i) / 3, y + ch);
        c.moveTo(x, y + (ch * i) / 3);
        c.lineTo(x + cw, y + (ch * i) / 3);
        c.stroke();
      }
      if (!this.fixed) {
        c.fillStyle = "#fff";
        for (const [hx, hy] of this.handles()) {
          c.fillRect(
            this.x + hx * this.scale - 3,
            this.y + hy * this.scale - 3,
            6,
            6,
          );
        }
      }
    }
  }
  async beginCompare(url, size) {
    if (this.compareState || !this.image) return;
    const saved = {
      image: this.image,
      width: this.width,
      height: this.height,
      scale: this.scale,
      x: this.x,
      y: this.y,
      autoFit: this.autoFit,
    };
    this.compareState = saved;
    this.loadId++;
    let original =
      this.originalCache?.url === url ? this.originalCache.image : null;
    if (!original) {
      original = new Image();
      original.src = url;
      await original.decode();
      this.originalCache = { url, image: original };
    }
    if (this.compareState !== saved) return;
    this.image = original;
    [this.width, this.height] = size;
    this.localImage = null;
    this.fit();
  }
  endCompare() {
    if (!this.compareState) return;
    Object.assign(this, this.compareState);
    this.compareState = null;
    this.draw();
    this.callbacks.zoom(this.scale);
  }
}
