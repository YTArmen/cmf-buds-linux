import React from 'react';
import type { WidgetTaskHandlerProps } from 'react-native-android-widget';

import { loadBattery } from '../store';
import { BatteryWidget } from './BatteryWidget';

export async function widgetTaskHandler({ widgetAction, renderWidget }: WidgetTaskHandlerProps) {
  if (widgetAction === 'WIDGET_DELETED') return;
  renderWidget(<BatteryWidget data={await loadBattery()} />);
}
