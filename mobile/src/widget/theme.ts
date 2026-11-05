import type { ColorProp } from 'react-native-android-widget';

// Общие цвета приложения и виджетов
export const W = {
  bgFrom: '#232326' as ColorProp,
  bgTo: '#141416' as ColorProp,
  text: '#F2F2F7' as ColorProp,
  sub: '#8E8E93' as ColorProp,
  track: '#2C2C2E' as ColorProp,
  accent: '#E8452C' as ColorProp,
  accentTo: '#FF7A45' as ColorProp,
  green: '#34C759' as ColorProp,
  yellow: '#FFD60A' as ColorProp,
  red: '#FF453A' as ColorProp,
};

export const levelColor = (v?: number): ColorProp =>
  v == null ? W.track : v <= 20 ? W.red : v <= 40 ? W.yellow : W.green;

export function ago(at: number) {
  const m = Math.round((Date.now() - at) / 60000);
  if (m < 1) return 'сейчас';
  if (m < 60) return `${m} мин назад`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} ч назад` : 'давно';
}
