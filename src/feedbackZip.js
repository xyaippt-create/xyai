const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

export const FEEDBACK_ZIP_ENTRIES = Object.freeze([
  "feedback.json",
  "related.log",
  "timeline.json",
  "manifest.json",
]);

const PAYLOAD_ENTRIES = FEEDBACK_ZIP_ENTRIES.slice(0, 3);

function concatBytes(parts) {
  const size = parts.reduce((total, part) => total + part.length, 0);
  const output = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

function littleEndian(values) {
  const size = values.reduce((total, [, bytes]) => total + bytes, 0);
  const output = new Uint8Array(size);
  const view = new DataView(output.buffer);
  let offset = 0;
  for (const [value, bytes] of values) {
    if (bytes === 2) view.setUint16(offset, value, true);
    else view.setUint32(offset, value, true);
    offset += bytes;
  }
  return output;
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) {
      value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
    }
    table[index] = value >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function dosTimestamp(value) {
  const date = value instanceof Date && !Number.isNaN(value.valueOf()) ? value : new Date();
  const year = Math.max(1980, Math.min(2107, date.getFullYear()));
  return {
    time: (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2),
    date: ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate(),
  };
}

function createStoredZip(entries, generatedAt) {
  const locals = [];
  const centrals = [];
  const timestamp = dosTimestamp(new Date(generatedAt));
  let localOffset = 0;
  for (const [name, data] of entries) {
    const nameBytes = encoder.encode(name);
    const content = data instanceof Uint8Array ? data : encoder.encode(String(data));
    const crc = crc32(content);
    const localHeader = littleEndian([
      [0x04034b50, 4], [20, 2], [0x0800, 2], [0, 2],
      [timestamp.time, 2], [timestamp.date, 2], [crc, 4],
      [content.length, 4], [content.length, 4], [nameBytes.length, 2], [0, 2],
    ]);
    const localRecord = concatBytes([localHeader, nameBytes, content]);
    locals.push(localRecord);
    const centralHeader = littleEndian([
      [0x02014b50, 4], [20, 2], [20, 2], [0x0800, 2], [0, 2],
      [timestamp.time, 2], [timestamp.date, 2], [crc, 4],
      [content.length, 4], [content.length, 4], [nameBytes.length, 2],
      [0, 2], [0, 2], [0, 2], [0, 2], [0, 4], [localOffset, 4],
    ]);
    centrals.push(concatBytes([centralHeader, nameBytes]));
    localOffset += localRecord.length;
  }
  const centralDirectory = concatBytes(centrals);
  const end = littleEndian([
    [0x06054b50, 4], [0, 2], [0, 2], [entries.length, 2], [entries.length, 2],
    [centralDirectory.length, 4], [localOffset, 4], [0, 2],
  ]);
  return concatBytes([...locals, centralDirectory, end]);
}

async function sha256Hex(bytes) {
  if (!globalThis.crypto?.subtle) throw new Error("浏览器缺少安全哈希能力，无法生成已验证的反馈包。");
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

function jsonBytes(value) {
  return encoder.encode(JSON.stringify(value, null, 2));
}

function readStoredZip(bytes) {
  const entries = new Map();
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 0;
  while (offset + 4 <= bytes.length && view.getUint32(offset, true) === 0x04034b50) {
    const compression = view.getUint16(offset + 8, true);
    const size = view.getUint32(offset + 18, true);
    const nameLength = view.getUint16(offset + 26, true);
    const extraLength = view.getUint16(offset + 28, true);
    if (compression !== 0) throw new Error("本地反馈包压缩格式无效。");
    const nameStart = offset + 30;
    const dataStart = nameStart + nameLength + extraLength;
    const dataEnd = dataStart + size;
    if (dataEnd > bytes.length) throw new Error("本地反馈包结构不完整。");
    const name = decoder.decode(bytes.slice(nameStart, nameStart + nameLength));
    entries.set(name, bytes.slice(dataStart, dataEnd));
    offset = dataEnd;
  }
  return entries;
}

export async function createValidatedFeedbackZip({ feedback, relatedLog, timeline, manifestBase, generatedAt }) {
  const payloads = new Map([
    ["feedback.json", jsonBytes(feedback)],
    ["related.log", encoder.encode(relatedLog)],
    ["timeline.json", jsonBytes(timeline)],
  ]);
  const payloadFiles = {};
  for (const name of PAYLOAD_ENTRIES) {
    const bytes = payloads.get(name);
    payloadFiles[name] = { size_bytes: bytes.length, sha256: await sha256Hex(bytes) };
  }
  const manifest = { ...manifestBase, payload_files: payloadFiles, package_validation_status: "PASS" };
  const zipBytes = createStoredZip([
    ...PAYLOAD_ENTRIES.map((name) => [name, payloads.get(name)]),
    ["manifest.json", jsonBytes(manifest)],
  ], generatedAt);
  const reopened = readStoredZip(zipBytes);
  if (FEEDBACK_ZIP_ENTRIES.some((name) => !reopened.has(name)) || reopened.size !== FEEDBACK_ZIP_ENTRIES.length) {
    throw new Error("本地反馈包文件结构校验失败。");
  }
  const reopenedManifest = JSON.parse(decoder.decode(reopened.get("manifest.json")));
  JSON.parse(decoder.decode(reopened.get("feedback.json")));
  JSON.parse(decoder.decode(reopened.get("timeline.json")));
  if (!decoder.decode(reopened.get("related.log")).startsWith("RELATED_LOG_STATUS=")) {
    throw new Error("本地反馈包日志状态无效。");
  }
  for (const name of PAYLOAD_ENTRIES) {
    const bytes = reopened.get(name);
    const entry = reopenedManifest.payload_files?.[name];
    if (!entry || entry.size_bytes !== bytes.length || entry.sha256 !== await sha256Hex(bytes)) {
      throw new Error(`本地反馈包完整性校验失败：${name}`);
    }
  }
  return {
    blob: new Blob([zipBytes], { type: "application/zip" }),
    manifest: reopenedManifest,
    validation: "PASS",
  };
}
