'use no memo';
import React from 'react';
import { FlexWidget, TextWidget } from 'react-native-android-widget';

import { ANC_OFF, ANC_TRANSP } from '../cmf';
import type { Saved } from '../store';
import { Cell, Header } from './BatteryWidget';
import { W } from './theme';

const ANC_ON = 0x01; // сильное шумоподавление
export const WIDGET_MODES: [number, string, string][] = [
  [ANC_OFF, 'Выкл', '○'],
  [ANC_TRANSP, 'Прозрачн.', '◐'],
  [ANC_ON, 'Шумодав.', '●'],
];

const modeOf = (anc?: number) => (anc == null ? undefined : anc === ANC_OFF ? ANC_OFF : anc === ANC_TRANSP ? ANC_TRANSP : ANC_ON);

function ModeButton({ code, label, icon, active, pending }: {
  code: number; label: string; icon: string; active: boolean; pending: boolean;
}) {
  return (
    <FlexWidget
      clickAction="ANC"
      clickActionData={{ mode: code }}
      style={{
        flex: 1, marginHorizontal: 3, paddingVertical: 9, borderRadius: 16,
        flexDirection: 'column', alignItems: 'center',
        ...(active
          ? { backgroundGradient: { from: W.accent, to: W.accentTo, orientation: 'LEFT_RIGHT' as const } }
          : { backgroundColor: W.track }),
      }}>
      <TextWidget text={pending ? '…' : icon} style={{ fontSize: 15, color: W.text }} />
      <TextWidget text={label} style={{ fontSize: 11, fontWeight: active ? '700' : '400', color: W.text }} />
    </FlexWidget>
  );
}

/** Виджет «Наушники»: заряд CMF Buds + кнопки режимов шумоподавления. */
export function ControlsWidget({ data, pending, error }: { data: Saved; pending?: number; error?: string }) {
  const b = data.cmf;
  const shown = pending ?? modeOf(b?.anc);
  return (
    <FlexWidget
      style={{
        height: 'match_parent', width: 'match_parent', padding: 14, borderRadius: 24,
        backgroundGradient: { from: W.bgFrom, to: W.bgTo, orientation: 'TOP_BOTTOM' },
        flexDirection: 'column', justifyContent: 'space-between',
      }}>
      {b ? (
        <FlexWidget clickAction="OPEN_APP" style={{ flexDirection: 'column', width: 'match_parent' }}>
          <Header b={b} />
          <FlexWidget style={{ flexDirection: 'row', width: 'match_parent' }}>
            <Cell label="Левый" value={b.left} charging={b.leftCh} />
            <Cell label="Правый" value={b.right} charging={b.rightCh} />
            <Cell label="Кейс" value={b.case} charging={b.caseCh} />
          </FlexWidget>
        </FlexWidget>
      ) : (
        <TextWidget clickAction="OPEN_APP" text="Откройте приложение и подключите CMF Buds"
          style={{ fontSize: 13, color: W.text }} />
      )}
      <FlexWidget style={{ flexDirection: 'row', width: 'match_parent', marginTop: 10 }}>
        {WIDGET_MODES.map(([code, label, icon]) => (
          <ModeButton key={code} code={code} label={label} icon={icon}
            active={shown === code} pending={pending === code} />
        ))}
      </FlexWidget>
      {error ? <TextWidget text={error} style={{ fontSize: 11, color: W.yellow, marginTop: 6 }} maxLines={1} /> : null}
    </FlexWidget>
  );
}
