// Pick the ink and paper colours of a layer region from the source pixels, so a new region
// starts from the poster's own colours instead of a fixed red-on-white default.
// Two-means on RGB: the larger cluster is the paper (background), the smaller one the ink.
// `spread` is the median distance of paper pixels from the paper colour; a large value means
// the background is a gradient or a photo, which a single flat paper colour would replace.

export const PAPER_SPREAD_LIMIT = 8;

const hex = rgb => "#" + rgb.map(v => Math.round(v).toString(16).padStart(2, "0")).join("");
const luma = (r, g, b) => 0.299 * r + 0.587 * g + 0.114 * b;

export function pickRegionColors(data) {
  const count = Math.floor(data.length / 4);
  if (!count) return null;
  let dark = 0, light = 0;
  for (let i = 1; i < count; i++) {
    const y = luma(data[i * 4], data[i * 4 + 1], data[i * 4 + 2]);
    if (y < luma(data[dark * 4], data[dark * 4 + 1], data[dark * 4 + 2])) dark = i;
    if (y > luma(data[light * 4], data[light * 4 + 1], data[light * 4 + 2])) light = i;
  }
  let centres = [[data[dark * 4], data[dark * 4 + 1], data[dark * 4 + 2]], [data[light * 4], data[light * 4 + 1], data[light * 4 + 2]]];
  const label = new Uint8Array(count);
  for (let round = 0; round < 12; round++) {
    const sums = [[0, 0, 0, 0], [0, 0, 0, 0]];
    for (let i = 0; i < count; i++) {
      const p = [data[i * 4], data[i * 4 + 1], data[i * 4 + 2]];
      const d = centres.map(c => (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2);
      const k = d[1] < d[0] ? 1 : 0;
      label[i] = k;
      sums[k][0] += p[0]; sums[k][1] += p[1]; sums[k][2] += p[2]; sums[k][3]++;
    }
    centres = centres.map((c, k) => sums[k][3] ? sums[k].slice(0, 3).map(v => v / sums[k][3]) : c);
  }
  const sizes = [0, 0];
  for (let i = 0; i < count; i++) sizes[label[i]]++;
  const paper = sizes[1] >= sizes[0] ? 1 : 0;
  // Anti-aliased edge pixels sit between the two colours; average only the half of each
  // cluster farthest from the other colour, and judge flatness by the median distance.
  const core = (k, away) => {
    const rows = [];
    for (let i = 0; i < count; i++) if (label[i] === k) {
      const p = [data[i * 4], data[i * 4 + 1], data[i * 4 + 2]];
      rows.push([Math.hypot(p[0] - away[0], p[1] - away[1], p[2] - away[2]), p]);
    }
    rows.sort((a, b) => b[0] - a[0]);
    const kept = rows.slice(0, Math.max(1, Math.ceil(rows.length / 2)));
    return [0, 1, 2].map(c => kept.reduce((sum, row) => sum + row[1][c], 0) / kept.length);
  };
  const inkColor = core(1 - paper, centres[paper]);
  const paperColor = core(paper, centres[1 - paper]);
  const distances = [];
  for (let i = 0; i < count; i++) if (label[i] === paper)
    distances.push(Math.hypot(data[i * 4] - paperColor[0], data[i * 4 + 1] - paperColor[1], data[i * 4 + 2] - paperColor[2]));
  distances.sort((a, b) => a - b);
  const spread = distances[Math.floor(distances.length / 2)] || 0;
  return { ink: hex(inkColor), paper: hex(paperColor), spread, flat: spread <= PAPER_SPREAD_LIMIT };
}
