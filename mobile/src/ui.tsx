// Анимированные элементы интерфейса.
// Характер движения: «премиальный, но быстрый» — одна кривая, три длительности.
import * as Haptics from 'expo-haptics';
import React, { useEffect, useState } from 'react';
import { LayoutChangeEvent, Pressable, StyleSheet, Text, View, ViewStyle } from 'react-native';
import Animated, {
  Easing, FadeIn, FadeInDown, FadeOutUp, LinearTransition, ReduceMotion,
  useAnimatedStyle, useReducedMotion, useSharedValue, withRepeat, withSequence, withSpring, withTiming,
} from 'react-native-reanimated';

export const C = {
  bg: '#0E0E10', card: '#1C1C1E', line: '#2C2C2E', text: '#F2F2F7', sub: '#8E8E93',
  accent: '#E8452C', green: '#34C759', yellow: '#FFD60A', red: '#FF453A',
};

// фирменная кривая и длительности
export const EASE_OUT = Easing.bezier(0.23, 1, 0.32, 1);
export const D = { quick: 140, standard: 220, slow: 420 };
const SPRING = { duration: 380, dampingRatio: 0.82, reduceMotion: ReduceMotion.System };

/** Появление карточек каскадом при открытии экрана (один раз). */
export const enter = (i: number) =>
  FadeInDown.duration(D.slow).easing(EASE_OUT).delay(Math.min(i, 5) * 60).reduceMotion(ReduceMotion.System);
export const layout = LinearTransition.duration(D.standard).easing(EASE_OUT).reduceMotion(ReduceMotion.System);
export const fadeSwap = FadeIn.duration(D.standard).easing(EASE_OUT);

/** Кнопка с мягким «нажатием» (scale 0.97). */
export function PressScale({ children, onPress, disabled, style }: {
  children: React.ReactNode; onPress?: () => void; disabled?: boolean; style?: ViewStyle | ViewStyle[];
}) {
  const s = useSharedValue(1);
  const a = useAnimatedStyle(() => ({ transform: [{ scale: s.get() }] }));
  return (
    <Pressable disabled={disabled || !onPress} onPress={onPress}
      onPressIn={() => s.set(withTiming(0.97, { duration: 100, easing: EASE_OUT }))}
      onPressOut={() => s.set(withSpring(1, SPRING))}>
      <Animated.View style={[style, a]}>{children}</Animated.View>
    </Pressable>
  );
}

export function Card({ title, children, index = 0 }: { title?: string; children: React.ReactNode; index?: number }) {
  return (
    <Animated.View entering={enter(index)} layout={layout} style={{ marginBottom: 18 }}>
      {title ? <Text style={st.cardTitle}>{title}</Text> : null}
      <View style={st.card}>{children}</View>
    </Animated.View>
  );
}

/** Заряд: полоска плавно доезжает до нового значения, молния «дышит» при зарядке. */
export function BatteryCell({ label, value, charging, extra }: { label: string; value?: number; charging?: boolean; extra?: string }) {
  const [w, setW] = useState(0);
  const fill = useSharedValue(0);
  const pulse = useSharedValue(1);
  const reduced = useReducedMotion();
  const color = value == null ? C.line : value <= 20 ? C.red : value <= 40 ? C.yellow : C.green;

  useEffect(() => {
    fill.set(withTiming(((value ?? 0) / 100) * w, { duration: D.slow * 2, easing: EASE_OUT, reduceMotion: ReduceMotion.System }));
  }, [value, w, fill]);
  useEffect(() => {
    pulse.set(charging && !reduced
      ? withRepeat(withSequence(withTiming(0.35, { duration: 900 }), withTiming(1, { duration: 900 })), -1)
      : withTiming(1, { duration: D.quick }));
  }, [charging, reduced, pulse]);

  const fillStyle = useAnimatedStyle(() => ({ width: fill.get() }));
  const boltStyle = useAnimatedStyle(() => ({ opacity: pulse.get() }));

  return (
    <View style={st.battCell}>
      <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
        <Text style={st.battValue}>{value == null ? '—' : `${value}%`}</Text>
        {charging ? <Animated.Text style={[st.bolt, boltStyle]}> ⚡</Animated.Text> : null}
      </View>
      <View style={st.battTrack} onLayout={(e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width)}>
        <Animated.View style={[st.battFill, { backgroundColor: color }, fillStyle]} />
      </View>
      <Text style={st.battLabel}>{label}</Text>
      {extra ? <Animated.Text entering={fadeSwap} style={st.battExtra}>{extra}</Animated.Text> : null}
    </View>
  );
}

/** Переключатель режимов: цветная «таблетка» переезжает пружиной к выбранному пункту. */
export function Segmented<T extends string | number>({ items, value, onChange, disabled }: {
  items: [T, string][]; value?: T; onChange: (v: T) => void; disabled?: boolean;
}) {
  const [w, setW] = useState(0);
  const idx = items.findIndex(([v]) => v === value);
  const cell = w > 0 ? (w - 6) / items.length : 0;
  const x = useSharedValue(0);
  const shown = useSharedValue(0);

  useEffect(() => {
    if (!cell) return;
    if (idx < 0) {
      shown.set(withTiming(0, { duration: D.quick }));
      return;
    }
    const first = shown.get() === 0;
    x.set(first ? idx * cell : withSpring(idx * cell, SPRING));
    shown.set(withTiming(1, { duration: D.standard, easing: EASE_OUT }));
  }, [idx, cell, x, shown]);

  const pill = useAnimatedStyle(() => ({
    width: cell,
    opacity: shown.get(),
    transform: [{ translateX: x.get() }, { scale: 0.92 + 0.08 * shown.get() }],
  }));

  return (
    <View style={[st.seg, disabled && { opacity: 0.4 }]} onLayout={(e) => setW(e.nativeEvent.layout.width)}>
      <Animated.View style={[st.segPill, pill]} />
      {items.map(([v, label]) => (
        <Pressable key={String(v)} disabled={disabled} style={st.segItem}
          onPress={() => {
            if (v !== value) Haptics.selectionAsync().catch(() => {});
            onChange(v);
          }}>
          <Text style={[st.segText, value === v && st.segTextActive]} numberOfLines={1}>{label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

/** Баннер о связи: выезжает сверху и уезжает обратно. */
export function Banner({ text, onPress }: { text: string; onPress?: () => void }) {
  return (
    <Animated.View entering={FadeInDown.duration(D.standard).easing(EASE_OUT)}
      exiting={FadeOutUp.duration(D.quick)} layout={layout}>
      <PressScale onPress={onPress} style={st.banner}>
        <Text style={st.bannerText}>{text}</Text>
      </PressScale>
    </Animated.View>
  );
}

export const st = StyleSheet.create({
  card: { backgroundColor: C.card, borderRadius: 16, overflow: 'hidden' },
  cardTitle: { color: C.sub, fontSize: 13, fontWeight: '600', textTransform: 'uppercase', marginBottom: 6, marginLeft: 4 },
  battCell: { flex: 1, alignItems: 'center' },
  battValue: { color: C.text, fontSize: 22, fontWeight: '700' },
  bolt: { color: C.yellow, fontSize: 16 },
  battTrack: { height: 6, alignSelf: 'stretch', backgroundColor: C.line, borderRadius: 3, marginVertical: 8, overflow: 'hidden' },
  battFill: { position: 'absolute', left: 0, top: 0, bottom: 0, borderRadius: 3 },
  battLabel: { color: C.sub, fontSize: 13 },
  battExtra: { color: C.green, fontSize: 12, marginTop: 2 },
  seg: { flexDirection: 'row', backgroundColor: C.line, borderRadius: 12, padding: 3 },
  segPill: { position: 'absolute', top: 3, bottom: 3, left: 3, borderRadius: 9, backgroundColor: C.accent },
  segItem: { flex: 1, paddingVertical: 9, paddingHorizontal: 4, alignItems: 'center', minWidth: 34, minHeight: 40, justifyContent: 'center' },
  segText: { color: C.text, fontSize: 14 },
  segTextActive: { color: '#fff', fontWeight: '700' },
  banner: { backgroundColor: '#3A2A12', borderRadius: 14, padding: 14, marginBottom: 18 },
  bannerText: { color: '#FFD9A0', fontSize: 14, lineHeight: 20 },
});
