// QR codes for the on-set links, made on the page itself, so no link ever goes to an outside service to be drawn. Byte mode, error correction M, versions 1 to 9: enough for any link here.
(function (exports) {
  "use strict";
  const BLOCKS = { 1: [10, [[1, 16]]], 2: [16, [[1, 28]]], 3: [26, [[1, 44]]], 4: [18, [[2, 32]]], 5: [24, [[2, 43]]], 6: [16, [[4, 27]]], 7: [18, [[4, 31]]], 8: [22, [[2, 38], [2, 39]]], 9: [22, [[3, 36], [2, 37]]] };
  const ALIGN = { 1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46] };

  const EXP = new Array(512), LOG = new Array(256);
  for (let i = 0, x = 1; i < 255; i += 1) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; }
  for (let i = 255; i < 512; i += 1) EXP[i] = EXP[i - 255];
  const mul = (a, b) => (a && b ? EXP[LOG[a] + LOG[b]] : 0);

  function correction(data, count) {
    const gen = [1];
    for (let i = 0; i < count; i += 1) {
      gen.push(0);
      for (let j = gen.length - 1; j > 0; j -= 1) gen[j] = gen[j - 1] ^ mul(gen[j], EXP[i]);
      gen[0] = mul(gen[0], EXP[i]);
    }
    gen.reverse();   // highest power first
    const rem = new Array(count).fill(0);
    for (const byte of data) {
      const factor = byte ^ rem[0];
      rem.shift(); rem.push(0);
      for (let i = 0; i < count; i += 1) rem[i] ^= mul(gen[i + 1], factor);
    }
    return rem;
  }

  const capacity = (v) => BLOCKS[v][1].reduce((n, [blocks, size]) => n + blocks * size, 0);

  function codewords(text, version) {
    const bytes = Array.from(new TextEncoder().encode(text));
    const bits = [];
    const put = (value, length) => { for (let i = length - 1; i >= 0; i -= 1) bits.push((value >>> i) & 1); };
    put(4, 4); put(bytes.length, 8);
    for (const b of bytes) put(b, 8);
    const total = capacity(version) * 8;
    put(0, Math.min(4, total - bits.length));
    while (bits.length % 8) bits.push(0);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((n, b) => n * 2 + b, 0));
    for (let pad = 0xec; data.length < capacity(version); pad ^= 0xec ^ 0x11) data.push(pad);
    const [ecCount, groups] = BLOCKS[version];
    const blocks = [];
    let at = 0;
    for (const [howMany, size] of groups) for (let b = 0; b < howMany; b += 1) { const part = data.slice(at, at + size); at += size; blocks.push({ part, ec: correction(part, ecCount) }); }
    const out = [];
    const longest = Math.max(...blocks.map((b) => b.part.length));
    for (let i = 0; i < longest; i += 1) for (const b of blocks) if (i < b.part.length) out.push(b.part[i]);
    for (let i = 0; i < ecCount; i += 1) for (const b of blocks) out.push(b.ec[i]);
    return out;
  }

  const MASKS = [(r, c) => (r + c) % 2 === 0, (r) => r % 2 === 0, (r, c) => c % 3 === 0, (r, c) => (r + c) % 3 === 0, (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0, (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0, (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0, (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0];

  function score(m) {
    const n = m.length;
    let total = 0, dark = 0;
    const runs = (line) => {
      let run = 1;
      for (let i = 1; i <= n; i += 1) {
        if (i < n && line(i) === line(i - 1)) run += 1;
        else { if (run >= 5) total += run - 2; run = 1; }
      }
    };
    const A = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], B = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1];
    const pattern = (line) => { for (let i = 0; i + 11 <= n; i += 1) if (A.every((v, k) => (line(i + k) ? 1 : 0) === v) || B.every((v, k) => (line(i + k) ? 1 : 0) === v)) total += 40; };
    for (let i = 0; i < n; i += 1) { runs((j) => m[i][j]); runs((j) => m[j][i]); pattern((j) => m[i][j]); pattern((j) => m[j][i]); }
    for (let r = 0; r < n; r += 1) for (let c = 0; c < n; c += 1) {
      if (m[r][c]) dark += 1;
      if (r + 1 < n && c + 1 < n && m[r][c] === m[r][c + 1] && m[r][c] === m[r + 1][c] && m[r][c] === m[r + 1][c + 1]) total += 3;
    }
    return total + Math.floor(Math.abs((dark * 20) / (n * n) - 10)) * 10;
  }

  function qrMatrix(text) {
    const length = new TextEncoder().encode(text).length;
    let version = 1;
    while (version <= 9 && capacity(version) < length + 2) version += 1;
    if (version > 9) throw new Error("That's too long for a QR code.");
    const size = 17 + version * 4;
    const m = Array.from({ length: size }, () => new Array(size).fill(false));
    const fixed = Array.from({ length: size }, () => new Array(size).fill(false));
    const set = (x, y, dark) => { m[y][x] = dark; fixed[y][x] = true; };

    for (let i = 0; i < size; i += 1) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    for (const [cx, cy] of [[3, 3], [size - 4, 3], [3, size - 4]]) {
      for (let dy = -4; dy <= 4; dy += 1) for (let dx = -4; dx <= 4; dx += 1) {
        const x = cx + dx, y = cy + dy, far = Math.max(Math.abs(dx), Math.abs(dy));
        if (x >= 0 && x < size && y >= 0 && y < size) set(x, y, far !== 2 && far !== 4);
      }
    }
    const centres = ALIGN[version], last = centres.length - 1;
    centres.forEach((cy, i) => centres.forEach((cx, j) => {
      if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return;
      for (let dy = -2; dy <= 2; dy += 1) for (let dx = -2; dx <= 2; dx += 1) set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }));
    const format = (mask) => {
      const data = mask;   // error correction M is 00
      let rem = data;
      for (let i = 0; i < 10; i += 1) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
      const bits = ((data << 10) | rem) ^ 0x5412;
      const bit = (i) => ((bits >>> i) & 1) === 1;
      for (let i = 0; i <= 5; i += 1) set(8, i, bit(i));
      set(8, 7, bit(6)); set(8, 8, bit(7)); set(7, 8, bit(8));
      for (let i = 9; i < 15; i += 1) set(14 - i, 8, bit(i));
      for (let i = 0; i < 8; i += 1) set(size - 1 - i, 8, bit(i));
      for (let i = 8; i < 15; i += 1) set(8, size - 15 + i, bit(i));
      set(8, size - 8, true);
    };
    format(0);
    if (version >= 7) {
      let rem = version;
      for (let i = 0; i < 12; i += 1) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
      const bits = (version << 12) | rem;
      for (let i = 0; i < 18; i += 1) {
        const dark = ((bits >>> i) & 1) === 1, a = size - 11 + (i % 3), b = Math.floor(i / 3);
        set(a, b, dark); set(b, a, dark);
      }
    }
    const words = codewords(text, version);
    let i = 0;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < size; vert += 1) {
        for (let j = 0; j < 2; j += 1) {
          const x = right - j, y = ((right + 1) & 2) === 0 ? size - 1 - vert : vert;
          if (!fixed[y][x] && i < words.length * 8) { m[y][x] = ((words[i >>> 3] >>> (7 - (i & 7))) & 1) === 1; i += 1; }
        }
      }
    }
    const applyMask = (mask) => { for (let y = 0; y < size; y += 1) for (let x = 0; x < size; x += 1) if (!fixed[y][x] && MASKS[mask](y, x)) m[y][x] = !m[y][x]; };
    let best = 0, lowest = Infinity;
    for (let mask = 0; mask < 8; mask += 1) {
      applyMask(mask); format(mask);
      const s = score(m);
      if (s < lowest) { lowest = s; best = mask; }
      applyMask(mask);
    }
    applyMask(best); format(best);
    return m;
  }

  // The code as a picture, with its quiet border, built without any HTML strings.
  function qrSvg(text, doc) {
    const m = qrMatrix(text), quiet = 4, n = m.length + quiet * 2, NS = "http://www.w3.org/2000/svg";
    const svg = doc.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${n} ${n}`); svg.setAttribute("shape-rendering", "crispEdges"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "QR code");
    const back = doc.createElementNS(NS, "rect"); back.setAttribute("width", n); back.setAttribute("height", n); back.setAttribute("fill", "#fff"); svg.appendChild(back);
    let d = "";
    m.forEach((row, y) => row.forEach((dark, x) => { if (dark) d += `M${x + quiet} ${y + quiet}h1v1h-1z`; }));
    const path = doc.createElementNS(NS, "path"); path.setAttribute("d", d); path.setAttribute("fill", "#000"); svg.appendChild(path);
    return svg;
  }

  Object.assign(exports, { qrMatrix, qrSvg });
})(typeof module !== "undefined" && module.exports ? module.exports : (window.OnSetQr = {}));
