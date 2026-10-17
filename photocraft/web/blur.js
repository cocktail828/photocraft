// Portable thumbnail blur. CanvasRenderingContext2D.filter is unavailable in some Safari releases.
export function blurThumbnail(source, radius) {
  const width = source.width,
    height = source.height;
  const context = source.getContext("2d");
  const pixels = context.getImageData(0, 0, width, height);
  const data = pixels.data,
    horizontal = new Float32Array(data.length);
  radius = Math.max(1, Math.round(radius));
  const span = radius * 2 + 1;
  // Premultiply RGB to avoid dark edges around transparent pixels.
  const sample = (offset, channel) =>
    channel === 3
      ? data[offset + 3]
      : (data[offset + channel] * data[offset + 3]) / 255;
  for (let y = 0; y < height; y++) {
    for (let channel = 0; channel < 4; channel++) {
      let sum = 0;
      for (let x = -radius; x <= radius; x++)
        sum += sample(
          (y * width + Math.max(0, Math.min(width - 1, x))) * 4,
          channel,
        );
      for (let x = 0; x < width; x++) {
        horizontal[(y * width + x) * 4 + channel] = sum / span;
        sum +=
          sample(
            (y * width + Math.min(width - 1, x + radius + 1)) * 4,
            channel,
          ) - sample((y * width + Math.max(0, x - radius)) * 4, channel);
      }
    }
  }
  for (let x = 0; x < width; x++) {
    const sums = [0, 0, 0, 0];
    for (let y = -radius; y <= radius; y++) {
      const offset = (Math.max(0, Math.min(height - 1, y)) * width + x) * 4;
      for (let c = 0; c < 4; c++) sums[c] += horizontal[offset + c];
    }
    for (let y = 0; y < height; y++) {
      const offset = (y * width + x) * 4,
        alpha = sums[3] / span;
      data[offset + 3] = alpha;
      for (let c = 0; c < 3; c++)
        data[offset + c] = alpha ? ((sums[c] / span) * 255) / alpha : 0;
      const next = (Math.min(height - 1, y + radius + 1) * width + x) * 4;
      const previous = (Math.max(0, y - radius) * width + x) * 4;
      for (let c = 0; c < 4; c++)
        sums[c] += horizontal[next + c] - horizontal[previous + c];
    }
  }
  context.putImageData(pixels, 0, 0);
  return source;
}
