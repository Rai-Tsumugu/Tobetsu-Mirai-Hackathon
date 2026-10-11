// M10 用の ZIP 読み取りと最小の XML パーサー（Python の zipfile / xml.etree.ElementTree 相当）。
// 依存を足さず、node:zlib の inflateRawSync だけを使う。サーバー側専用。
import { inflateRawSync } from "node:zlib";

// ---- ZIP ----

/** zipfile.BadZipFile 相当。 */
export class BadZipFile extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BadZipFile";
  }
}

export type ZipEntry = {
  filename: string;
  /** 展開後のサイズ（中央ディレクトリの値。ZipInfo.file_size）。 */
  file_size: number;
  read: () => Uint8Array;
};

const CP437_HIGH =
  "ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ";

function decodeName(bytes: Uint8Array, utf8: boolean): string {
  if (utf8) return new TextDecoder("utf-8").decode(bytes);
  let out = "";
  for (const byte of bytes) out += byte < 0x80 ? String.fromCharCode(byte) : CP437_HIGH[byte - 0x80];
  return out;
}

let crcTable: Uint32Array | null = null;

function crc32(data: Uint8Array): number {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n += 1) {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (const byte of data) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function u16(data: Uint8Array, offset: number): number {
  return data[offset] | (data[offset + 1] << 8);
}

function u32(data: Uint8Array, offset: number): number {
  return (data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16)) + data[offset + 3] * 0x1000000;
}

function rfind(data: Uint8Array, pattern: number[], from: number): number {
  for (let i = data.length - pattern.length; i >= from; i -= 1) {
    if (pattern.every((byte, k) => data[i + k] === byte)) return i;
  }
  return -1;
}

const EOCD = [0x50, 0x4b, 0x05, 0x06];

/** ZipFile(BytesIO(data)).infolist() 相当。ZIP として読めなければ BadZipFile。 */
export function readZip(data: Uint8Array): ZipEntry[] {
  if (data.length < 22) throw new BadZipFile("File is not a zip file");
  let end = -1;
  const tail = data.length - 22;
  if (EOCD.every((byte, k) => data[tail + k] === byte) && u16(data, tail + 20) === 0) {
    end = tail;
  } else {
    end = rfind(data, EOCD, Math.max(0, data.length - (65535 + 22)));
    if (end < 0 || end + 22 > data.length) throw new BadZipFile("File is not a zip file");
  }
  const sizeCd = u32(data, end + 12);
  const offsetCd = u32(data, end + 16);
  const concat = end - sizeCd - offsetCd;
  if (concat < 0) throw new BadZipFile("Bad offset for central directory");
  let pos = offsetCd + concat;
  const stop = pos + sizeCd;
  const entries: ZipEntry[] = [];
  while (pos < stop) {
    if (pos + 46 > data.length || u32(data, pos) !== 0x02014b50) {
      throw new BadZipFile("Bad magic number for central directory");
    }
    const flags = u16(data, pos + 8);
    const method = u16(data, pos + 10);
    const crc = u32(data, pos + 16);
    const compressedSize = u32(data, pos + 20);
    const fileSize = u32(data, pos + 24);
    const nameLength = u16(data, pos + 28);
    const extraLength = u16(data, pos + 30);
    const commentLength = u16(data, pos + 32);
    const headerOffset = u32(data, pos + 42);
    const filename = decodeName(data.subarray(pos + 46, pos + 46 + nameLength), (flags & 0x800) !== 0);
    pos += 46 + nameLength + extraLength + commentLength;
    entries.push({
      filename,
      file_size: fileSize,
      read: () => {
        const local = headerOffset + concat;
        if (local + 30 > data.length || u32(data, local) !== 0x04034b50) {
          throw new BadZipFile("Bad magic number for file header");
        }
        if (flags & 1) throw new Error(`File ${filename} is encrypted, password required for extraction`);
        const start = local + 30 + u16(data, local + 26) + u16(data, local + 28);
        const raw = data.subarray(start, start + compressedSize);
        let bytes: Uint8Array;
        if (method === 0) bytes = raw;
        else if (method === 8) {
          try {
            bytes = new Uint8Array(inflateRawSync(raw));
          } catch {
            throw new Error("Error -3 while decompressing data");
          }
        } else throw new Error("That compression method is not supported");
        if (crc32(bytes) !== crc) throw new BadZipFile(`Bad CRC-32 for file '${filename}'`);
        return bytes;
      },
    });
  }
  return entries;
}

// ---- XML ----

/** xml.etree.ElementTree.ParseError 相当。 */
export class XmlParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ParseError";
  }
}

/** ElementTree の Element。tag と属性名は "{名前空間}名前"。 */
export type XmlElement = {
  tag: string;
  attrib: Record<string, string>;
  text: string | null;
  tail: string | null;
  children: XmlElement[];
};

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };

function decodeEntities(text: string): string {
  return text.replace(/&([^;&]*);?/g, (match, name: string) => {
    if (!match.endsWith(";")) throw new XmlParseError("not well-formed (invalid token)");
    if (name.startsWith("#x")) {
      const code = parseInt(name.slice(2), 16);
      if (!/^[0-9a-fA-F]+$/.test(name.slice(2)) || code > 0x10ffff) throw new XmlParseError("reference to invalid character number");
      return String.fromCodePoint(code);
    }
    if (name.startsWith("#")) {
      const code = Number(name.slice(1));
      if (!/^\d+$/.test(name.slice(1)) || code > 0x10ffff) throw new XmlParseError("reference to invalid character number");
      return String.fromCodePoint(code);
    }
    if (!(name in ENTITIES)) throw new XmlParseError(`undefined entity &${name};`);
    return ENTITIES[name];
  });
}

const NAME = /^[A-Za-z_À-￿][\w.\-·À-￿]*(?::[A-Za-z_À-￿][\w.\-·À-￿]*)?$/;

/** ET.fromstring(bytes)。UTF-8 として読む。 */
export function parseXml(data: Uint8Array): XmlElement {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(data);
  } catch {
    throw new XmlParseError("not well-formed (invalid token)");
  }
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  let index = 0;
  type Frame = { element: XmlElement; rawTag: string; namespaces: Record<string, string> };
  const stack: Frame[] = [];
  let root: XmlElement | null = null;
  let last: XmlElement | null = null; // テキストの付け先（直前に閉じた要素の tail か、親の text）
  const appendText = (chunk: string) => {
    if (!chunk) return;
    if (stack.length === 0) {
      if (chunk.trim()) throw new XmlParseError(root ? "junk after document element" : "syntax error");
      return;
    }
    const parent = stack[stack.length - 1].element;
    if (last && parent.children.includes(last)) last.tail = (last.tail ?? "") + chunk;
    else parent.text = (parent.text ?? "") + chunk;
  };
  const resolve = (qname: string, namespaces: Record<string, string>, isAttr: boolean): string => {
    const colon = qname.indexOf(":");
    if (colon < 0) {
      if (isAttr || !namespaces[""]) return qname;
      return `{${namespaces[""]}}${qname}`;
    }
    const prefix = qname.slice(0, colon);
    if (prefix === "xml") return `{http://www.w3.org/XML/1998/namespace}${qname.slice(colon + 1)}`;
    if (!(prefix in namespaces)) throw new XmlParseError("unbound prefix");
    return `{${namespaces[prefix]}}${qname.slice(colon + 1)}`;
  };
  while (index < text.length) {
    const lt = text.indexOf("<", index);
    if (lt < 0) {
      appendText(decodeEntities(text.slice(index)));
      break;
    }
    if (lt > index) appendText(decodeEntities(text.slice(index, lt)));
    if (text.startsWith("<?", lt)) {
      const close = text.indexOf("?>", lt);
      if (close < 0) throw new XmlParseError("unclosed token");
      index = close + 2;
      continue;
    }
    if (text.startsWith("<!--", lt)) {
      const close = text.indexOf("-->", lt + 4);
      if (close < 0) throw new XmlParseError("unclosed token");
      index = close + 3;
      continue;
    }
    if (text.startsWith("<![CDATA[", lt)) {
      const close = text.indexOf("]]>", lt);
      if (close < 0 || stack.length === 0) throw new XmlParseError("unclosed token");
      appendText(text.slice(lt + 9, close));
      index = close + 3;
      continue;
    }
    if (text.startsWith("<!", lt)) throw new XmlParseError("syntax error");
    const gt = findTagEnd(text, lt);
    if (gt < 0) throw new XmlParseError("unclosed token");
    const inner = text.slice(lt + 1, gt);
    index = gt + 1;
    if (inner.startsWith("/")) {
      const name = inner.slice(1).trim();
      const frame = stack.pop();
      if (!frame || frame.rawTag !== name) throw new XmlParseError("mismatched tag");
      last = frame.element;
      continue;
    }
    const selfClosing = inner.endsWith("/");
    const body = selfClosing ? inner.slice(0, -1) : inner;
    const nameMatch = /^([^\s/>]+)/.exec(body);
    if (!nameMatch || !NAME.test(nameMatch[1])) throw new XmlParseError("not well-formed (invalid token)");
    const rawTag = nameMatch[1];
    const rawAttrs: [string, string][] = [];
    let rest = body.slice(rawTag.length);
    const attrPattern = /^\s+([^\s=]+)\s*=\s*("([^"]*)"|'([^']*)')/;
    for (;;) {
      const m = attrPattern.exec(rest);
      if (!m) break;
      if (!NAME.test(m[1]) || m[2].includes("<")) throw new XmlParseError("not well-formed (invalid token)");
      if (rawAttrs.some(([name]) => name === m[1])) throw new XmlParseError("duplicate attribute");
      rawAttrs.push([m[1], decodeEntities(m[3] ?? m[4]).replace(/[\t\n\r]/g, " ")]);
      rest = rest.slice(m[0].length);
    }
    if (rest.trim()) throw new XmlParseError("not well-formed (invalid token)");
    if (stack.length === 0 && root) throw new XmlParseError("junk after document element");
    const namespaces = { ...(stack.length ? stack[stack.length - 1].namespaces : {}) };
    for (const [name, value] of rawAttrs) {
      if (name === "xmlns") namespaces[""] = value;
      else if (name.startsWith("xmlns:")) namespaces[name.slice(6)] = value;
    }
    const attrib: Record<string, string> = {};
    for (const [name, value] of rawAttrs) {
      if (name === "xmlns" || name.startsWith("xmlns:")) continue;
      attrib[resolve(name, namespaces, true)] = value;
    }
    const element: XmlElement = { tag: resolve(rawTag, namespaces, false), attrib, text: null, tail: null, children: [] };
    if (stack.length) stack[stack.length - 1].element.children.push(element);
    else root = element;
    last = null;
    if (selfClosing) {
      last = element;
      if (stack.length === 0) last = null;
    } else {
      stack.push({ element, rawTag, namespaces });
    }
  }
  if (stack.length) throw new XmlParseError("no element found");
  if (!root) throw new XmlParseError("no element found");
  return root;
}

function findTagEnd(text: string, start: number): number {
  let quote: string | null = null;
  for (let i = start + 1; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") quote = ch;
    else if (ch === ">") return i;
    else if (ch === "<") return -1;
  }
  return -1;
}

/** 子孫を文書順に（自身を含まない）。 */
function descendants(element: XmlElement): XmlElement[] {
  const out: XmlElement[] = [];
  for (const child of element.children) {
    out.push(child, ...descendants(child));
  }
  return out;
}

/** Element.findall の一部: "tag"（子）, ".//tag"（子孫）, ".//a/b"（子孫 a の子 b）。 */
export function findall(element: XmlElement, path: string): XmlElement[] {
  let current: XmlElement[];
  let steps: string[];
  if (path.startsWith(".//")) {
    const [first, ...others] = splitPath(path.slice(3));
    current = descendants(element).filter((node) => node.tag === first);
    steps = others;
  } else {
    current = [element];
    steps = splitPath(path);
  }
  for (const step of steps) {
    current = current.flatMap((node) => node.children.filter((child) => child.tag === step));
  }
  return current;
}

function splitPath(path: string): string[] {
  // "{ns}a/{ns}b" を "/" で分ける（名前空間 URI 内の "/" は分けない）。
  const parts: string[] = [];
  let buffer = "";
  let depth = 0;
  for (const ch of path) {
    if (ch === "{") depth += 1;
    if (ch === "}") depth -= 1;
    if (ch === "/" && depth === 0) {
      parts.push(buffer);
      buffer = "";
    } else buffer += ch;
  }
  parts.push(buffer);
  return parts;
}

export function find(element: XmlElement, path: string): XmlElement | null {
  return findall(element, path)[0] ?? null;
}

/** Element.itertext() を連結したもの（自身の tail は含めない）。 */
export function itertext(element: XmlElement): string {
  let out = element.text ?? "";
  for (const child of element.children) out += itertext(child) + (child.tail ?? "");
  return out;
}
