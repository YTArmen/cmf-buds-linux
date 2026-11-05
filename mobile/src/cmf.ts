// Протокол Nothing / CMF Buds (тот же, что в cmf_buds.py для Linux).
// Пакет: 55 60 01 | cmd LE | len LE | 01 | payload | CRC16/Modbus LE

export const CMF_UUID = 'aeac4a03-dff5-498f-843a-34487cf133eb';
export const CMF_CHANNEL = 15;

export const READ = { battery: 0xc007, anc: 0xc01e, eq: 0xc01f, gestures: 0xc018, lowlat: 0xc041, fw: 0xc042, bass: 0xc04e };
export const SET = { gesture: 0xf003, anc: 0xf00f, eq: 0xf010, lowlat: 0xf040, bass: 0xf051 };

export const ANC_OFF = 0x05;
export const ANC_TRANSP = 0x07;
export const ANC_LEVELS: [number, string][] = [[0x01, 'Сильное'], [0x02, 'Среднее'], [0x03, 'Слабое']];
export const EQ_PRESETS: [number, string][] = [
  [0, 'Сбалансированный'], [3, 'Больше баса'], [2, 'Больше высоких'], [1, 'Голос'], [5, 'Свой'],
];
export const GESTURES: [number, string][] = [
  [2, 'Двойное касание'], [3, 'Тройное касание'], [7, 'Касание и удержание'], [9, 'Двойное касание и удержание'],
];
export const ACTIONS: [number, string][] = [
  [0x01, 'Нет действия'], [0x08, 'Пауза / воспроизведение'], [0x09, 'Следующий трек'],
  [0x0a, 'Предыдущий трек'], [0x0b, 'Голосовой помощник'], [0x12, 'Громче'], [0x13, 'Тише'],
  [0x16, 'Шумоподавление'],
];
export const SIDES: [number, string][] = [[2, 'Левый'], [3, 'Правый']];

function crc16(data: number[]): number {
  let c = 0xffff;
  for (const b of data) {
    c ^= b;
    for (let i = 0; i < 8; i++) c = c & 1 ? (c >> 1) ^ 0xa001 : c >> 1;
  }
  return c;
}

export function packet(cmd: number, payload: number[] = []): string {
  const head = [0x55, 0x60, 0x01, cmd & 0xff, cmd >> 8, payload.length & 0xff, payload.length >> 8, 0x01, ...payload];
  const c = crc16(head);
  return [...head, c & 0xff, c >> 8].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export const hexToBytes = (h: string) => Array.from({ length: h.length / 2 }, (_, i) => parseInt(h.substr(i * 2, 2), 16));

/** Склеивает поток байтов в пакеты. Возвращает остаток буфера. */
export function parseStream(buf: number[], onPacket: (cmd: number, p: number[]) => void): number[] {
  for (;;) {
    const i = buf.indexOf(0x55);
    if (i < 0) return [];
    buf = buf.slice(i);
    if (buf.length < 8) return buf;
    const n = buf[5] | (buf[6] << 8);
    if (n > 512) {
      buf = buf.slice(1);
      continue;
    }
    const total = 8 + n + (buf[1] ? 2 : 0); // 0x60 = есть CRC, 0x00 = уведомление без CRC
    if (buf.length < total) return buf;
    onPacket(buf[3] | (buf[4] << 8), buf.slice(8, 8 + n));
    buf = buf.slice(total);
  }
}

export type Battery = { left?: number; right?: number; case?: number; leftCh?: boolean; rightCh?: boolean; caseCh?: boolean };

export type CmfState = {
  battery: Battery;
  anc?: number;
  eq?: number;
  bass?: { on: boolean; level: number };
  lowlat?: boolean;
  fw?: string;
  gestures: Record<string, number>; // `${side}:${gesture}` -> action
};

/** Применяет ответ наушников к состоянию. */
export function applyPacket(s: CmfState, cmd: number, p: number[]): CmfState {
  const n = { ...s };
  if ((cmd === 0x4007 || cmd === 0xe001) && p.length) {
    const b = { ...s.battery };
    for (let i = 0; i < p[0]; i++) {
      const dev = p[1 + i * 2];
      const lvl = p[2 + i * 2];
      const pct = lvl & 0x7f;
      const ch = (lvl & 0x80) !== 0;
      if (dev === 2) Object.assign(b, { left: pct, leftCh: ch });
      if (dev === 3) Object.assign(b, { right: pct, rightCh: ch });
      if (dev === 4) Object.assign(b, { case: pct, caseCh: ch });
    }
    n.battery = b;
  } else if (cmd === 0x401e && p.length >= 5) n.anc = p[4];
  else if (cmd === 0xe003 && p.length >= 2) n.anc = p[1];
  else if (cmd === 0x401f && p.length) n.eq = p[0];
  else if (cmd === 0x404e && p.length >= 2) n.bass = { on: p[0] === 1, level: Math.max(1, Math.min(5, p[1] >> 1)) };
  else if ((cmd === 0x4041 || cmd === 0xe005) && p.length) n.lowlat = p[0] === 1;
  else if (cmd === 0x4042) n.fw = String.fromCharCode(...p);
  else if (cmd === 0x4018 && p.length) {
    const g = { ...s.gestures };
    for (let i = 0; i < p[0]; i++) {
      const [side, , gtype, act] = p.slice(1 + i * 4, 5 + i * 4);
      g[`${side}:${gtype}`] = act;
    }
    n.gestures = g;
  }
  return n;
}
