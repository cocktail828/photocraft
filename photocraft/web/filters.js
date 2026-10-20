// Style recipes use the same bounded adjustments as the manual panel.
export const FILTERS = [
  { id: "none", name: "无效果", hint: "恢复自然色彩", values: {}, thumbnail: "none" },
  { id: "vivid", name: "鲜明", hint: "通透鲜亮，突出色彩", values: { brightness: 1.04, contrast: 1.16, saturation: 1.35, sharpness: 1.18 }, thumbnail: "brightness(1.04) contrast(1.16) saturate(1.35)" },
  { id: "warm", name: "暖阳", hint: "温暖明亮的日光感", values: { brightness: 1.06, temperature: 0.32, saturation: 1.08 }, thumbnail: "sepia(.22) saturate(1.12) brightness(1.06)" },
  { id: "cool", name: "冷调", hint: "清冷色调，干净利落", values: { temperature: -0.32, contrast: 1.12, saturation: 0.9 }, thumbnail: "sepia(.12) hue-rotate(165deg) contrast(1.12) saturate(.9)" },
  { id: "soft", name: "柔和", hint: "轻盈柔光，柔化反差", values: { brightness: 1.08, contrast: 0.86, saturation: 0.88, sharpness: 0.85, gamma: 1.08 }, thumbnail: "brightness(1.08) contrast(.86) saturate(.88)" },
  { id: "film", name: "复古", hint: "低饱和的暖色氛围", values: { temperature: 0.24, saturation: 0.65, contrast: 0.88, gamma: 1.12 }, thumbnail: "sepia(.3) saturate(.65) contrast(.88)" },
  { id: "mono", name: "黑白", hint: "去除色彩，突出明暗", values: { saturation: 0, contrast: 1.2, sharpness: 1.12 }, thumbnail: "grayscale(1) contrast(1.2)" },
  { id: "dramatic", name: "戏剧", hint: "深邃阴影，强化层次", values: { contrast: 1.38, saturation: 0.8, sharpness: 1.3, gamma: 0.85 }, thumbnail: "contrast(1.38) saturate(.8) brightness(.9)" },
];

export function filterParams(id, strength, defaults) {
  const recipe = FILTERS.find((item) => item.id === id);
  if (!recipe) return null;
  const params = { ...defaults };
  for (const [key, target] of Object.entries(recipe.values)) {
    params[key] = Number((defaults[key] + (target - defaults[key]) * strength / 100).toFixed(4));
  }
  return params;
}
