'use no memo';
import React from 'react';
import { FlexWidget, TextWidget } from 'react-native-android-widget';

import type { Saved, SavedBattery } from '../store';
import { ago, levelColor, W } from './theme';

/** Одна ячейка: крупный процент + полоска. */
export function Cell({ label, value, charging, big }: { label: string; value?: number; charging?: boolean; big?: boolean }) {
  const pct = value ?? 0;
  return (
    <FlexWidget style={{ flex: 1, flexDirection: 'column', alignItems: 'center', paddingHorizontal: 4 }}>
      <TextWidget
        text={value == null ? '—' : `${value}%${charging ? ' ⚡' : ''}`}
        style={{ fontSize: big ? 20 : 15, fontWeight: '700', color: W.text }}
      />
      <FlexWidget style={{ width: 'match_parent', height: 5, backgroundColor: W.track, borderRadius: 3, marginVertical: 5, flexDirection: 'row' }}>
        {pct > 0 ? (
          <FlexWidget style={{ flex: pct, height: 5, borderRadius: 3, backgroundColor: levelColor(value) }} />
        ) : null}
        {pct < 100 ? <FlexWidget style={{ flex: 100 - pct, height: 5 }} /> : null}
      </FlexWidget>
      <TextWidget text={label} style={{ fontSize: 11, color: W.sub }} />
    </FlexWidget>
  );
}

export function Header({ b }: { b: SavedBattery }) {
  return (
    <FlexWidget style={{ flexDirection: 'row', justifyContent: 'space-between', width: 'match_parent', marginBottom: 6 }}>
      <TextWidget text={b.name} style={{ fontSize: 13, fontWeight: '700', color: W.text }} maxLines={1} />
      <TextWidget text={ago(b.at)} style={{ fontSize: 11, color: W.sub }} />
    </FlexWidget>
  );
}

function Device({ b, last }: { b: SavedBattery; last: boolean }) {
  return (
    <FlexWidget style={{ flexDirection: 'column', width: 'match_parent', marginBottom: last ? 0 : 10 }}>
      <Header b={b} />
      <FlexWidget style={{ flexDirection: 'row', width: 'match_parent' }}>
        <Cell label="Левый" value={b.left} charging={b.leftCh} big />
        <Cell label="Правый" value={b.right} charging={b.rightCh} big />
        <Cell label="Кейс" value={b.case} charging={b.caseCh} big />
      </FlexWidget>
    </FlexWidget>
  );
}

/** Виджет «Заряд наушников» — только заряд. */
export function BatteryWidget({ data }: { data: Saved }) {
  const items = Object.values(data).sort((a, b) => b.at - a.at);
  return (
    <FlexWidget
      clickAction="OPEN_APP"
      style={{
        height: 'match_parent', width: 'match_parent', padding: 14, borderRadius: 24,
        backgroundGradient: { from: W.bgFrom, to: W.bgTo, orientation: 'TOP_BOTTOM' },
        flexDirection: 'column', justifyContent: 'center',
      }}>
      {items.length ? (
        items.map((b, i) => <Device key={b.name} b={b} last={i === items.length - 1} />)
      ) : (
        <TextWidget text="Откройте приложение «Наушники», чтобы увидеть заряд" style={{ fontSize: 13, color: W.text }} />
      )}
    </FlexWidget>
  );
}
