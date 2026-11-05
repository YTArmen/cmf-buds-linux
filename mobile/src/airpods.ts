// Разбор BLE-рассылки AirPods (Apple «proximity pairing», 0x07 0x19).
// Схема как в открытом приложении OpenPods. Заряд приходит шагом 10%.

export const MODELS: Record<string, string> = {
  '0220': 'AirPods', '0f20': 'AirPods 2', '1320': 'AirPods 3', '1920': 'AirPods 4',
  '1b20': 'AirPods 4 (шумоподавление)', '0e20': 'AirPods Pro', '1420': 'AirPods Pro 2',
  '2420': 'AirPods Pro 2 (USB-C)', '0a20': 'AirPods Max', '1f20': 'AirPods Max (USB-C)',
};

export type AirPodsInfo = {
  model: string;
  left?: number; right?: number; case?: number;
  leftCh: boolean; rightCh: boolean; caseCh: boolean;
  leftInEar: boolean; rightInEar: boolean;
  rssi: number;
  at: number;
};

const nib = (hex: string, i: number) => parseInt(hex[i], 16);
const pct = (v: number) => (v <= 10 ? v * 10 : undefined); // 15 = нет данных

export function parseAdv(hex: string, rssi: number): AirPodsInfo | null {
  hex = hex.toLowerCase();
  if (hex.length < 18 || !hex.startsWith('0719')) return null;
  const model = MODELS[hex.substr(6, 4)] ?? 'AirPods';
  // если «основной» наушник правый, половинки в пакете меняются местами
  const flip = (nib(hex, 10) & 0x02) === 0;
  const charge = nib(hex, 14);
  const ear = nib(hex, 11);
  return {
    model,
    left: pct(nib(hex, flip ? 12 : 13)),
    right: pct(nib(hex, flip ? 13 : 12)),
    case: pct(nib(hex, 15)),
    leftCh: (charge & (flip ? 0x02 : 0x01)) !== 0,
    rightCh: (charge & (flip ? 0x01 : 0x02)) !== 0,
    caseCh: (charge & 0x04) !== 0,
    leftInEar: (ear & (flip ? 0x08 : 0x02)) !== 0,
    rightInEar: (ear & (flip ? 0x02 : 0x08)) !== 0,
    rssi,
    at: Date.now(),
  };
}
