import AsyncStorage from '@react-native-async-storage/async-storage';
import React from 'react';
import { requestWidgetUpdate } from 'react-native-android-widget';

import { BatteryWidget } from './widget/BatteryWidget';
import { ControlsWidget } from './widget/ControlsWidget';

export type SavedBattery = {
  name: string;
  address?: string;
  left?: number; right?: number; case?: number;
  leftCh?: boolean; rightCh?: boolean; caseCh?: boolean;
  anc?: number; // режим шумоподавления CMF (код протокола)
  at: number;
};
export type Saved = Record<string, SavedBattery>; // 'cmf' | 'airpods'
export type WidgetUi = { pending?: number; error?: string };

const KEY = 'battery-v1';

export async function loadBattery(): Promise<Saved> {
  try {
    return JSON.parse((await AsyncStorage.getItem(KEY)) ?? '{}');
  } catch {
    return {};
  }
}

let last = '';

/** Перерисовать оба виджета. */
export async function renderWidgets(all: Saved, ui: WidgetUi = {}) {
  await Promise.all([
    requestWidgetUpdate({
      widgetName: 'Battery',
      renderWidget: () => React.createElement(BatteryWidget, { data: all }),
    }).catch(() => {}),
    requestWidgetUpdate({
      widgetName: 'Controls',
      renderWidget: () => React.createElement(ControlsWidget, { data: all, ...ui }),
    }).catch(() => {}),
  ]);
}

/** Запомнить данные наушников и обновить виджеты (только если что-то изменилось). */
export async function saveBattery(kind: string, b: Partial<SavedBattery> & { at: number }) {
  const all = await loadBattery();
  const prev = all[kind];
  const merged = { ...prev, ...b } as SavedBattery;
  all[kind] = merged;
  const sig = JSON.stringify({ ...all, [kind]: { ...merged, at: 0 } });
  if (sig === last && prev && merged.at - prev.at < 5 * 60_000) return;
  last = sig;
  await AsyncStorage.setItem(KEY, JSON.stringify(all));
  await renderWidgets(all);
}
