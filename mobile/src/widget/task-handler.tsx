import React from 'react';
import type { WidgetTaskHandlerProps } from 'react-native-android-widget';

import BudsBt from '../../modules/buds-bt/src/BudsBtModule';
import * as cmf from '../cmf';
import { loadBattery, renderWidgets, saveBattery } from '../store';
import { BatteryWidget } from './BatteryWidget';
import { ControlsWidget } from './ControlsWidget';

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Подключиться к CMF (если приложение уже держит связь — использовать её), отправить режим. */
async function setCmfMode(address: string, mode: number): Promise<{ ok: boolean; battery?: cmf.Battery; error?: string }> {
  const opened = !BudsBt.isSppConnected(address);
  let state: cmf.CmfState = { battery: {}, gestures: {} };
  let buf: number[] = [];
  let connected = !opened;
  let failed: string | undefined;
  const s1 = BudsBt.addListener('onSppState', (e) => {
    if (e.address !== address) return;
    connected = e.connected;
    if (!e.connected) failed = e.error ?? 'нет связи';
  });
  const s2 = BudsBt.addListener('onSppData', (e) => {
    if (e.address !== address) return;
    buf = cmf.parseStream([...buf, ...cmf.hexToBytes(e.hex)], (c, p) => { state = cmf.applyPacket(state, c, p); });
  });
  try {
    if (opened) {
      await BudsBt.connectSpp(address, cmf.CMF_UUID, cmf.CMF_CHANNEL);
      for (let i = 0; i < 40 && !connected && !failed; i++) await wait(150);
      if (!connected) return { ok: false, error: 'Наушники не на связи — достаньте их из кейса' };
    }
    BudsBt.writeSpp(address, cmf.packet(cmf.SET.anc, [1, mode, 0]));
    BudsBt.writeSpp(address, cmf.packet(cmf.READ.battery));
    BudsBt.writeSpp(address, cmf.packet(cmf.READ.anc));
    for (let i = 0; i < 12 && state.anc == null; i++) await wait(150);
    return { ok: true, battery: state.battery.left != null ? state.battery : undefined };
  } finally {
    s1.remove();
    s2.remove();
    if (opened) BudsBt.disconnectSpp(address);
  }
}

export async function widgetTaskHandler({ widgetInfo, widgetAction, clickAction, clickActionData, renderWidget }: WidgetTaskHandlerProps) {
  if (widgetAction === 'WIDGET_DELETED') return;
  const data = await loadBattery();

  if (widgetAction === 'WIDGET_CLICK' && clickAction === 'ANC') {
    const mode = Number(clickActionData?.mode);
    const address = data.cmf?.address;
    if (!address) {
      renderWidget(<ControlsWidget data={data} error="Сначала откройте приложение" />);
      return;
    }
    // мгновенный отклик: кнопка подсвечивается сразу
    await renderWidgets(data, { pending: mode });
    const res = await setCmfMode(address, mode).catch((e) => ({ ok: false, error: String(e?.message ?? e) }) as const);
    if (res.ok) {
      await saveBattery('cmf', { ...(('battery' in res && res.battery) || {}), anc: mode, at: Date.now() });
      await renderWidgets(await loadBattery());
    } else {
      await renderWidgets(data, { error: res.error });
    }
    return;
  }

  if (widgetInfo.widgetName === 'Controls') renderWidget(<ControlsWidget data={data} />);
  else renderWidget(<BatteryWidget data={data} />);
}
