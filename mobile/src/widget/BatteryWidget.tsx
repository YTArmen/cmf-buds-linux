'use no memo';
import React from 'react';
import { FlexWidget, TextWidget } from 'react-native-android-widget';

import type { Saved, SavedBattery } from '../store';

const fmt = (v?: number, ch?: boolean) => (v == null ? '—' : `${v}%${ch ? '⚡' : ''}`);

function ago(at: number) {
  const m = Math.round((Date.now() - at) / 60000);
  if (m < 1) return 'сейчас';
  if (m < 60) return `${m} мин назад`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} ч назад` : 'давно';
}

function Row({ b }: { b: SavedBattery }) {
  return (
    <FlexWidget style={{ flexDirection: 'column', marginBottom: 6, width: 'match_parent' }}>
      <FlexWidget style={{ flexDirection: 'row', justifyContent: 'space-between', width: 'match_parent' }}>
        <TextWidget text={b.name} style={{ fontSize: 14, fontWeight: '700', color: '#F2F2F2' }} />
        <TextWidget text={ago(b.at)} style={{ fontSize: 11, color: '#9A9A9A' }} />
      </FlexWidget>
      <TextWidget
        text={`Л ${fmt(b.left, b.leftCh)}   П ${fmt(b.right, b.rightCh)}   Кейс ${fmt(b.case, b.caseCh)}`}
        style={{ fontSize: 13, color: '#E0E0E0' }}
      />
    </FlexWidget>
  );
}

export function BatteryWidget({ data }: { data: Saved }) {
  const items = Object.values(data).sort((a, b) => b.at - a.at);
  return (
    <FlexWidget
      clickAction="OPEN_APP"
      style={{
        height: 'match_parent', width: 'match_parent', padding: 12,
        backgroundColor: '#1C1C1E', borderRadius: 20, flexDirection: 'column',
      }}>
      {items.length ? (
        items.map((b) => <Row key={b.name} b={b} />)
      ) : (
        <TextWidget text="Откройте приложение, чтобы увидеть заряд" style={{ fontSize: 13, color: '#E0E0E0' }} />
      )}
    </FlexWidget>
  );
}
