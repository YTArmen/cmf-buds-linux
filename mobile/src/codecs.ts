// Кодеки Samsung и Sony — копия buds_codecs.py (Linux), проверенного тестами.
// Источники: GalaxyBudsClient, Gadgetbridge. На настоящих наушниках не проверено.

export type Noise = 'off' | 'anc' | 'transparency' | 'adaptive';
export type Changes = {
  left?: number; right?: number; case?: number;
  left_ch?: boolean; right_ch?: boolean; case_ch?: boolean;
  noise?: Noise; ears?: 'both' | 'one' | 'none' | 'case';
};
export type ProfileModel = {
  match: string; uuid?: string; uuids?: string[]; modes?: Noise[];
  legacy?: boolean; noise_variant?: 'modern' | 'live' | 'ambient';
};
export type Profile = {
  id: string; version: number; name: string; codec: string; tested?: boolean; models: ProfileModel[];
};

type Send = (bytes: number[]) => void;

export interface Codec {
  start(): void;
  poll(): void;
  feed(data: number[]): Changes;
  setNoise(mode: Noise): void;
}

export function crc16xmodem(data: number[]): number {
  let c = 0;
  for (const b of data) {
    c ^= b << 8;
    for (let i = 0; i < 8; i++) c = (c & 0x8000 ? (c << 1) ^ 0x1021 : c << 1) & 0xffff;
  }
  return c;
}

// --- Samsung -------------------------------------------------------------------
const SAMSUNG_NOISE: Record<Noise, number> = { off: 0, anc: 1, transparency: 2, adaptive: 3 };
const SAMSUNG_BACK: Noise[] = ['off', 'anc', 'transparency', 'adaptive'];

export class SamsungCodec implements Codec {
  private buf: number[] = [];
  private greeted = false;
  private legacy: boolean;
  private variant: string;

  constructor(model: ProfileModel, private send: Send) {
    this.legacy = !!model.legacy;
    this.variant = model.noise_variant ?? 'modern';
  }

  frame(id: number, payload: number[] = []): number[] {
    const body = [id, ...payload];
    const crc = crc16xmodem(body);
    const size = body.length + 2;
    const head = this.legacy ? [0xfe, 0x00, size] : [0xfd, size & 0xff, (size >> 8) & 0x03];
    return [...head, ...body, crc & 0xff, crc >> 8, this.legacy ? 0xee : 0xdd];
  }

  start() {}
  poll() {}

  feed(data: number[]): Changes {
    this.buf.push(...data);
    const out: Changes = {};
    const [som, eom] = this.legacy ? [0xfe, 0xee] : [0xfd, 0xdd];
    for (;;) {
      const i = this.buf.indexOf(som);
      if (i < 0) { this.buf = []; break; }
      this.buf = this.buf.slice(i);
      if (this.buf.length < 3) break;
      const size = this.legacy ? this.buf[2] : (this.buf[1] | (this.buf[2] << 8)) & 0x3ff;
      if (size < 3 || size > 1000) { this.buf = this.buf.slice(1); continue; }
      const total = 3 + size + 1;
      if (this.buf.length < total) break;
      const pkt = this.buf.slice(0, total);
      this.buf = this.buf.slice(total);
      const body = pkt.slice(3, 3 + size - 2);
      const crc = pkt[3 + size - 2] | (pkt[3 + size - 1] << 8);
      if (pkt[total - 1] !== eom || crc16xmodem(body) !== crc) continue;
      Object.assign(out, this.handle(body[0], body.slice(1)));
    }
    for (const k of ['left', 'right', 'case'] as const) if (out[k] === 0) delete out[k];
    return out;
  }

  private ears(pl: number): Changes['ears'] {
    const l = pl >> 4, r = pl & 0x0f;
    const worn = [l, r].filter((x) => x === 1).length;
    if (worn) return worn === 2 ? 'both' : 'one';
    return [3, 4].includes(l) && [3, 4].includes(r) ? 'case' : 'none';
  }

  private handle(id: number, p: number[]): Changes {
    if (id === 0x60 && p.length >= 7) {
      const out: Changes = this.legacy
        ? { left: p[1], right: p[2], ears: ({ 17: 'both', 1: 'one', 16: 'one' } as const)[p[5] as 17] ?? 'none' }
        : { left: p[1], right: p[2], case: p[6], ears: this.ears(p[5]) };
      if (!this.legacy && p.length >= 8) {
        Object.assign(out, { left_ch: !!(p[7] & 0x10), right_ch: !!(p[7] & 0x04), case_ch: !!(p[7] & 0x01) });
      }
      if (!this.greeted) {
        this.greeted = true;
        this.send(this.frame(0x88, [0x01, 0x01, 34]));
      }
      return out;
    }
    if (id === 0x61 && p.length >= 8) {
      const out: Changes = { left: p[2], right: p[3], case: p[7], ears: this.ears(p[6]) };
      if (p.length > 12 && this.variant === 'modern') out.noise = SAMSUNG_BACK[p[12]];
      if (p.length > 12 && this.variant === 'live') out.noise = p[12] === 1 ? 'anc' : 'off';
      return out;
    }
    if (id === 0x77 && p.length) return SAMSUNG_BACK[p[0]] ? { noise: SAMSUNG_BACK[p[0]] } : {};
    return {};
  }

  setNoise(mode: Noise) {
    if (this.variant === 'live') this.send(this.frame(0x98, [mode === 'anc' ? 1 : 0]));
    else if (this.variant === 'ambient') this.send(this.frame(0x80, [mode === 'transparency' ? 1 : 0]));
    else this.send(this.frame(0x78, [SAMSUNG_NOISE[mode]]));
  }
}

// --- Sony ------------------------------------------------------------------------
export class SonyCodec implements Codec {
  private buf: number[] = [];
  private seq = 0;
  private queue: number[][] = [];
  private waiting = false;
  version: 1 | 2 | null = null;
  private t2: number | null = null;
  private wind = false;
  private level = 10;

  constructor(_model: ProfileModel, private send: Send) {}

  static escape(b: number[]) {
    const out: number[] = [];
    for (const x of b) {
      if (x === 0x3c || x === 0x3d || x === 0x3e) out.push(0x3d, x & 0xef);
      else out.push(x);
    }
    return out;
  }

  static unescape(b: number[]) {
    const out: number[] = [];
    for (let i = 0; i < b.length; i++) {
      if (b[i] === 0x3d && i + 1 < b.length) out.push(b[++i] | 0x10);
      else out.push(b[i]);
    }
    return out;
  }

  static frame(type: number, seq: number, payload: number[] = []) {
    const n = payload.length;
    const inner = [type, seq, (n >>> 24) & 0xff, (n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff, ...payload];
    inner.push(inner.reduce((a, b) => a + b, 0) & 0xff);
    return [0x3e, ...SonyCodec.escape(inner), 0x3c];
  }

  private command(p: number[]) {
    this.queue.push(p);
    this.pump();
  }

  private pump() {
    if (!this.waiting && this.queue.length) {
      this.waiting = true;
      this.send(SonyCodec.frame(0x0c, this.seq, this.queue.shift()!));
    }
  }

  start() { this.command([0x00, 0x00]); }

  poll() { if (this.version) this.askBattery(); }

  private askBattery() {
    if (this.version === 1) { this.command([0x10, 0x01]); this.command([0x10, 0x02]); }
    else { this.command([0x22, 0x09]); this.command([0x22, 0x0a]); }
  }

  feed(data: number[]): Changes {
    this.buf.push(...data);
    const out: Changes = {};
    for (;;) {
      const i = this.buf.indexOf(0x3e);
      if (i < 0) { this.buf = []; break; }
      const j = this.buf.indexOf(0x3c, i + 1);
      if (j < 0) { this.buf = this.buf.slice(i); break; }
      const raw = SonyCodec.unescape(this.buf.slice(i + 1, j));
      this.buf = this.buf.slice(j + 1);
      if (raw.length < 7 || (raw.slice(0, -1).reduce((a, b) => a + b, 0) & 0xff) !== raw[raw.length - 1]) continue;
      const [type, seq] = raw;
      if (type === 0x01) {
        this.seq = seq;
        this.waiting = false;
        this.pump();
        continue;
      }
      this.send(SonyCodec.frame(0x01, seq === 0 || seq === 1 ? 1 - seq : 0));
      Object.assign(out, this.handle(raw.slice(6, -1)));
    }
    return out;
  }

  private handle(p: number[]): Changes {
    if (!p.length) return {};
    const code = p[0];
    if (code === 0x01 && this.version === null) {
      this.version = p.length <= 4 ? 1 : 2;
      this.askBattery();
      if (this.version === 1) this.command([0x66, 0x02]);
      else { this.command([0x66, 0x17]); this.command([0x66, 0x15]); }
      return {};
    }
    if ([0x11, 0x13, 0x23, 0x25].includes(code) && p.length >= 4) {
      const kind = p[1];
      if ((kind === 0x01 || kind === 0x09) && p.length >= 6) {
        const out: Changes = { left_ch: p[3] === 1, right_ch: p[5] === 1 };
        if (p[2]) out.left = p[2];
        if (p[4]) out.right = p[4];
        return out;
      }
      if ((kind === 0x02 || kind === 0x0a) && p[2]) return { case: p[2], case_ch: p[3] === 1 };
      if (kind === 0x00 && p[2]) return { left: p[2], right: p[2] };
      return {};
    }
    if (code === 0x67 || code === 0x69) return this.version === 1 ? this.noiseV1(p) : this.noiseV2(p);
    return {};
  }

  private noiseV1(p: number[]): Changes {
    if (p.length !== 8) return {};
    this.wind = p[3] === 0x02;
    this.level = p[7] || this.level;
    if (p[2] === 0x00) return { noise: 'off' };
    return { noise: p[4] === (this.wind ? 0x02 : 0x01) ? 'anc' : 'transparency' };
  }

  private noiseV2(p: number[]): Changes {
    if (p.length < 6 || ![0x15, 0x17, 0x22].includes(p[1])) return {};
    if (p[1] !== 0x22) this.t2 = p[1];
    this.wind = p[1] === 0x17 && p.length > 7;
    this.level = p[p.length - 1] || this.level;
    if (p[3] === 0x00) return { noise: 'off' };
    if (p[1] === 0x22) return { noise: 'transparency' };
    return { noise: p[4] === 0x01 ? 'transparency' : 'anc' };
  }

  setNoise(mode: Noise) {
    if (!this.version) return;
    const on = mode !== 'off';
    const amb = mode === 'transparency';
    if (this.version === 1) {
      const m = this.wind ? (mode === 'anc' ? 2 : 0) : mode === 'anc' ? 1 : 0;
      this.command([0x68, 0x02, on ? 0x11 : 0x00, this.wind ? 0x02 : 0x00, m, 0x01, 0x00, amb ? this.level : 0]);
      this.command([0x66, 0x02]);
    } else {
      const t = this.t2 ?? 0x15;
      const body = [0x68, t, 0x01, on ? 0x01 : 0x00, amb ? 0x01 : 0x00];
      if (t === 0x17 && this.wind) body.push(0x02);
      body.push(0x00, amb ? this.level : 0);
      this.command(body);
      this.command([0x66, t]);
    }
  }
}

export const CODECS: Record<string, new (m: ProfileModel, s: Send) => Codec> = {
  samsung: SamsungCodec,
  sony: SonyCodec,
};
