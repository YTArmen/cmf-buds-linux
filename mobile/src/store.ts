import AsyncStorage from '@react-native-async-storage/async-storage';
import React from 'react';
import { requestWidgetUpdate } from 'react-native-android-widget';

import { BatteryWidget } from './widget/BatteryWidget';

export type SavedBattery = {
  name: string;
  left?: number; right?: number; case?: number;
  leftCh?: boolean; rightCh?: boolean; caseCh?: boolean;
  at: number;
};
export type Saved = Record<string, SavedBattery>; // 'cmf' | 'airpods'

const KEY = 'battery-v1';

export async function loadBattery(): Promise<Saved> {
  try {
    return JSON.parse((await AsyncStorage.getItem(KEY)) ?? '{}');
  } catch {
    return {};
  }
}

let last = '';

/** Запомнить заряд и обновить виджет (не чаще, чем данные реально меняются). */
export async function saveBattery(kind: string, b: SavedBattery) {
  const all = await loadBattery();
  const prev = all[kind];
  all[kind] = b;
  const sig = JSON.stringify({ ...all, [kind]: { ...b, at: 0 } });
  if (sig === last && prev && b.at - prev.at < 5 * 60_000) return;
  last = sig;
  await AsyncStorage.setItem(KEY, JSON.stringify(all));
  await requestWidgetUpdate({
    widgetName: 'Battery',
    renderWidget: () => React.createElement(BatteryWidget, { data: all }),
  }).catch(() => {});
}
