import fs from 'fs';
import { webcrypto } from 'crypto';
import { createRequire } from 'module';
import { fileURLToPath } from 'url';
import path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const require = createRequire(import.meta.url);

global.require = require;
global.__filename = __filename;
global.__dirname = __dirname;

const eventListeners = {};

const mockWindow = {
  crypto: webcrypto,
  addEventListener(event, fn) {
    if (!eventListeners[event]) eventListeners[event] = [];
    eventListeners[event].push(fn);
  },
  removeEventListener(event, fn) {},
  dispatchEvent(evt) {
    const list = eventListeners[evt.type] || [];
    for (const fn of list) fn(evt);
  },
  btoa(str) { return Buffer.from(str, 'binary').toString('base64'); },
  atob(b64) { return Buffer.from(b64, 'base64').toString('binary'); },
  TextEncoder: global.TextEncoder,
  TextDecoder: global.TextDecoder,
  location: {
    hostname: 'hanime.tv',
    href: 'https://hanime.tv',
    pathname: '/',
    protocol: 'https:',
    search: '',
    origin: 'https://hanime.tv',
    host: 'hanime.tv'
  },
  screen: { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040, colorDepth: 24, pixelDepth: 24 },
  innerWidth: 1920,
  innerHeight: 950,
  outerWidth: 1920,
  outerHeight: 1040,
  devicePixelRatio: 1,
  document: {
    documentElement: { style: { setProperty() {} }, setAttribute() {} },
    addEventListener() {},
    removeEventListener() {},
    cookie: '',
    location: { hostname: 'hanime.tv', href: 'https://hanime.tv', pathname: '/', protocol: 'https:', search: '', origin: 'https://hanime.tv', host: 'hanime.tv' },
    referrer: '',
    title: 'hanime.tv'
  },
  localStorage: { getItem() { return null; }, setItem() {} },
  sessionStorage: { getItem() { return null; }, setItem() {} },
  history: { length: 1 }
};

mockWindow.window = mockWindow;
mockWindow.self = mockWindow;
mockWindow.top = mockWindow;
mockWindow.parent = mockWindow;

for (const key of Object.keys(mockWindow)) {
  try {
    global[key] = mockWindow[key];
  } catch (e) {
    try {
      Object.defineProperty(global, key, { value: mockWindow[key], writable: true, configurable: true });
    } catch (e2) {}
  }
}
global.window = mockWindow;
global.self = mockWindow;
global.document = mockWindow.document;
global.location = mockWindow.location;

global.CustomEvent = class CustomEvent {
  constructor(type, eventInitDict = {}) {
    this.type = type;
    this.detail = eventInitDict.detail || null;
  }
};

global.Event = class Event {
  constructor(type) {
    this.type = type;
  }
};

// Encryption helpers
const HANDSHAKE_KEY_STR = 'htv-insecure-handshake-v1';
const HANDSHAKE_AAD_STR = 'htv-insecure-v1';

function b64urlDecode(str) {
  const base64 = str.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(str.length / 4) * 4, '=');
  const bin = window.atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function b64urlEncode(bytes) {
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return window.btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

async function getAesKey(usages = ['decrypt']) {
  const enc = new TextEncoder().encode(HANDSHAKE_KEY_STR);
  const digest = await webcrypto.subtle.digest('SHA-256', enc);
  return webcrypto.subtle.importKey('raw', digest, { name: 'AES-GCM' }, false, usages);
}

async function encryptPayload(data) {
  const enc = new TextEncoder();
  const jsonStr = typeof data === 'string' ? data : JSON.stringify(data);
  const iv = webcrypto.getRandomValues(new Uint8Array(12));
  const key = await getAesKey(['encrypt']);
  const encrypted = await webcrypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: enc.encode(HANDSHAKE_AAD_STR), tagLength: 128 },
    key,
    enc.encode(jsonStr)
  );
  const rawBytes = new Uint8Array(encrypted);
  const cipher = rawBytes.slice(0, -16);
  const tag = rawBytes.slice(-16);
  const envelope = {
    v: 1,
    alg: 'AES-256-GCM',
    iv: b64urlEncode(iv),
    tag: b64urlEncode(tag),
    data: b64urlEncode(cipher)
  };
  return b64urlEncode(enc.encode(JSON.stringify(envelope)));
}

async function decryptPayload(tokenStr) {
  const dec = new TextDecoder();
  const enc = new TextEncoder();
  const rawJson = dec.decode(b64urlDecode(tokenStr));
  const envelope = JSON.parse(rawJson);
  const key = await getAesKey(['decrypt']);
  const cipher = b64urlDecode(envelope.data);
  const tag = b64urlDecode(envelope.tag);
  const combined = new Uint8Array(cipher.length + tag.length);
  combined.set(cipher, 0);
  combined.set(tag, cipher.length);
  const decrypted = await webcrypto.subtle.decrypt(
    { name: 'AES-GCM', iv: b64urlDecode(envelope.iv), additionalData: enc.encode(HANDSHAKE_AAD_STR), tagLength: 128 },
    key,
    combined
  );
  return dec.decode(decrypted);
}

async function extract(slug) {
  const vendorPath = path.join(__dirname, 'hanimetv_vendor.js');
  let vendorCode;
  if (fs.existsSync(vendorPath)) {
    vendorCode = fs.readFileSync(vendorPath, 'utf-8');
  } else {
    const res = await fetch('https://hanime-cdn.com/js/vendor.6cb274d12de4872d245a5bc7781bdc5e.min.js');
    vendorCode = await res.text();
    try { fs.writeFileSync(vendorPath, vendorCode); } catch(e) {}
  }

  eval(vendorCode);

  // Wait until signature system is ready
  for (let i = 0; i < 20; i++) {
    window.dispatchEvent(new CustomEvent('e'));
    if (window.ssignature && window.stime) break;
    await new Promise(r => setTimeout(r, 100));
  }

  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      window.dispatchEvent(new CustomEvent('e'));
      const csrfRes = await fetch('https://ct.hanime.tv/csrf-token', {
        method: 'GET',
        headers: {
          'accept': 'application/json',
          'content-type': 'application/json',
          'x-signature-version': 'web2',
          'x-signature': window.ssignature,
          'x-time': String(window.stime),
          'Origin': 'https://hanime.tv',
          'Referer': `https://hanime.tv/videos/hentai/${slug}`,
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        }
      });

      if (!csrfRes.ok) {
        throw new Error(`CSRF token request failed (status ${csrfRes.status})`);
      }

      const csrfData = await csrfRes.json();
      const csrfToken = csrfData.csrf_token;
      if (!csrfToken) {
        throw new Error('No CSRF token returned');
      }

      window.dispatchEvent(new CustomEvent('e'));
      const handshakePayload = {
        timestamp_unix: parseInt(Date.now() / 1000, 10),
        directive: 'htv_player_handshake',
        slug: slug
      };

      const encryptedToken = await encryptPayload(handshakePayload);
      const handshakeRes = await fetch('https://auth.hanime.tv/api/v11/handshake', {
        method: 'POST',
        headers: {
          'accept': 'application/json',
          'content-type': 'application/json',
          'x-signature-version': 'web2',
          'x-signature': window.ssignature,
          'x-time': String(window.stime),
          'x-csrf-token': csrfToken,
          'Origin': 'https://hanime.tv',
          'Referer': `https://hanime.tv/videos/hentai/${slug}`,
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        },
        body: JSON.stringify({
          token: encryptedToken,
          csrf_token: csrfToken
        })
      });

      const xToken = handshakeRes.headers.get('x-token');
      if (!xToken) {
        throw new Error(`Handshake failed (status ${handshakeRes.status})`);
      }

      const decrypted = await decryptPayload(xToken);
      const parsed = JSON.parse(decrypted);

      const sources = [];
      for (const src of (parsed.sources || [])) {
        if (src.src) {
          const fullUrl = src.src.startsWith('http') ? src.src : `https://hanime.tv${src.src}`;
          sources.push({
            url: fullUrl,
            height: src.height || 0,
            width: src.width || 0,
            label: src.label || '',
            kind: src.kind || 'normal'
          });
        }
      }

      if (sources.length > 0) {
        return {
          status: 'ok',
          slug,
          sources
        };
      }
    } catch (err) {
      lastError = err;
      await new Promise(r => setTimeout(r, 600 * attempt));
    }
  }

  throw lastError || new Error('All handshake attempts failed');
}

const slug = process.argv[2] || 'momone-1';
extract(slug).then(res => {
  console.log(JSON.stringify(res));
}).catch(err => {
  console.error(JSON.stringify({ status: 'error', message: err.message }));
  process.exit(1);
});
