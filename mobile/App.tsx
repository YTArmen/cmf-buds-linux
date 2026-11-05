import { StatusBar } from 'expo-status-bar';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AppState, FlatList, Linking, Modal, PermissionsAndroid, Platform, Pressable,
  ScrollView, StyleSheet, Switch, Text, View,
} from 'react-native';

import BudsBt, { BondedDevice } from './modules/buds-bt/src/BudsBtModule';
import { AirPodsInfo, parseAdv } from './src/airpods';
import * as cmf from './src/cmf';
import { Changes, CODECS, Noise, Profile, ProfileModel } from './src/codecs';
import { findProfile } from './src/profiles';
import { saveBattery } from './src/store';
import { Banner, BatteryCell, C, Card, fadeSwap, Segmented } from './src/ui';
import Animated from 'react-native-reanimated';

// --- разрешения --------------------------------------------------------------
async function askPermissions(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  const P = PermissionsAndroid.PERMISSIONS;
  const list = (Platform.Version as number) >= 31
    ? [P.BLUETOOTH_CONNECT, P.BLUETOOTH_SCAN, P.ACCESS_FINE_LOCATION]
    : [P.ACCESS_FINE_LOCATION];
  const res = await PermissionsAndroid.requestMultiple(list);
  const need = (Platform.Version as number) >= 31 ? [P.BLUETOOTH_CONNECT, P.BLUETOOTH_SCAN] : [P.ACCESS_FINE_LOCATION];
  return need.every((p) => res[p] === PermissionsAndroid.RESULTS.GRANTED);
}

// --- CMF Buds ------------------------------------------------------------------
const emptyCmf: cmf.CmfState = { battery: {}, gestures: {} };

function useCmf(dev?: BondedDevice) {
  const [state, setState] = useState<cmf.CmfState>(emptyCmf);
  const [status, setStatus] = useState<'off' | 'connecting' | 'on'>('connecting');
  const [error, setError] = useState<string>();
  const buf = useRef<number[]>([]);

  const send = useCallback((cmd: number, payload: number[] = []) => {
    if (dev) BudsBt.writeSpp(dev.address, cmf.packet(cmd, payload));
  }, [dev]);

  const readAll = useCallback(() => {
    Object.values(cmf.READ).forEach((c) => send(c));
  }, [send]);

  // само подключение — без изменения состояния (его меняют ответы модуля)
  const open = useCallback(() => {
    if (!dev) return;
    BudsBt.connectSpp(dev.address, cmf.CMF_UUID, cmf.CMF_CHANNEL).catch((e) => {
      setStatus('off');
      setError(String(e?.message ?? e));
    });
  }, [dev]);

  // повтор по нажатию на баннер
  const connect = useCallback(() => {
    setStatus('connecting');
    setError(undefined);
    open();
  }, [open]);

  useEffect(() => {
    if (!dev) return;
    const s1 = BudsBt.addListener('onSppState', (e) => {
      if (e.address !== dev.address) return;
      setStatus(e.connected ? 'on' : 'off');
      if (e.error) setError(e.error);
      if (e.connected) {
        buf.current = [];
        setTimeout(readAll, 300);
      }
    });
    const s2 = BudsBt.addListener('onSppData', (e) => {
      if (e.address !== dev.address) return;
      buf.current = cmf.parseStream([...buf.current, ...cmf.hexToBytes(e.hex)], (cmd, p) =>
        setState((s) => cmf.applyPacket(s, cmd, p)));
    });
    open();
    const poll = setInterval(() => send(cmf.READ.battery), 30_000);
    return () => {
      s1.remove(); s2.remove(); clearInterval(poll);
      BudsBt.disconnectSpp(dev.address);
    };
  }, [dev, open, readAll, send]);

  useEffect(() => {
    const b = state.battery;
    if (dev && b.left != null) saveBattery('cmf', { name: dev.name, address: dev.address, ...b, anc: state.anc, at: Date.now() });
  }, [state.battery, state.anc, dev]);

  return { state, setState, status, error, send, connect, readAll };
}

// --- AirPods ----------------------------------------------------------------------
function useAirPods(enabled: boolean) {
  const [info, setInfo] = useState<AirPodsInfo | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const sub = BudsBt.addListener('onAppleAdv', (e) => {
      if (e.rssi < -80) return; // чужие AirPods далеко — не наши
      const p = parseAdv(e.hex, e.rssi);
      if (!p) return;
      // если рядом несколько пар, берём самую близкую (сильный сигнал)
      setInfo((old) => (!old || Date.now() - old.at > 10_000 || p.rssi >= old.rssi - 5 ? p : old));
    });
    const start = () => BudsBt.startAppleScan();
    start();
    const appSub = AppState.addEventListener('change', (st) => (st === 'active' ? start() : BudsBt.stopAppleScan()));
    return () => { sub.remove(); appSub.remove(); BudsBt.stopAppleScan(); };
  }, [enabled]);

  useEffect(() => {
    if (info && (info.left != null || info.right != null)) {
      saveBattery('airpods', {
        name: info.model, left: info.left, right: info.right, case: info.case,
        leftCh: info.leftCh, rightCh: info.rightCh, caseCh: info.caseCh, at: info.at,
      });
    }
  }, [info]);
  return info;
}

// --- маленькие компоненты ------------------------------------------------------------
function Row({ title, subtitle, right, onPress, last, disabled }: {
  title: string; subtitle?: string; right?: React.ReactNode; onPress?: () => void; last?: boolean; disabled?: boolean;
}) {
  return (
    <Pressable onPress={onPress} disabled={!onPress || disabled}
      style={({ pressed }) => [st.row, !last && st.rowLine, pressed && { opacity: 0.6 }, disabled && { opacity: 0.4 }]}>
      <View style={{ flex: 1 }}>
        <Text style={st.rowTitle}>{title}</Text>
        {subtitle ? <Text style={st.rowSub}>{subtitle}</Text> : null}
      </View>
      {right}
    </Pressable>
  );
}

function Picker({ title, items, value, onChange, last, disabled }: {
  title: string; items: [number, string][]; value?: number; onChange: (v: number) => void; last?: boolean; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const label = items.find(([v]) => v === value)?.[1] ?? '—';
  return (
    <>
      <Row title={title} last={last} disabled={disabled} onPress={() => setOpen(true)}
        right={<Text style={st.pickValue}>{label} ›</Text>} />
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={st.backdrop} onPress={() => setOpen(false)}>
          <View style={st.sheet}>
            <Text style={st.sheetTitle}>{title}</Text>
            <FlatList data={items} keyExtractor={([v]) => String(v)} renderItem={({ item: [v, l] }) => (
              <Pressable style={st.sheetItem} onPress={() => { onChange(v); setOpen(false); }}>
                <Text style={[st.rowTitle, v === value && { color: C.accent, fontWeight: '700' }]}>{l}</Text>
                {v === value ? <Text style={{ color: C.accent }}>✓</Text> : null}
              </Pressable>
            )} />
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

// --- экраны ------------------------------------------------------------------------------
function CmfScreen({ dev }: { dev: BondedDevice }) {
  const { state, setState, status, error, send, connect } = useCmf(dev);
  const on = status === 'on';
  const b = state.battery;
  const ancMode = state.anc == null ? undefined : state.anc === cmf.ANC_OFF ? 'off' : state.anc === cmf.ANC_TRANSP ? 'transp' : 'anc';
  const setAnc = (level: number) => {
    setState((s) => ({ ...s, anc: level }));
    send(cmf.SET.anc, [1, level, 0]);
  };
  const bass = state.bass ?? { on: false, level: 1 };
  const setBass = (v: { on: boolean; level: number }) => {
    setState((s) => ({ ...s, bass: v }));
    send(cmf.SET.bass, [v.on ? 1 : 0, v.level * 2]);
  };

  return (
    <>
      {!on && (
        <Banner onPress={connect}
          text={status === 'connecting' ? 'Подключаюсь к наушникам…'
            : `Наушники не на связи. Достаньте их из кейса и нажмите здесь.${error ? `\n(${error})` : ''}`} />
      )}
      <Card>
        <View style={st.battRow}>
          <BatteryCell label="Левый" value={b.left} charging={b.leftCh} />
          <BatteryCell label="Правый" value={b.right} charging={b.rightCh} />
          <BatteryCell label="Кейс" value={b.case} charging={b.caseCh} />
        </View>
      </Card>

      <Card title="Шумоподавление" index={1}>
        <View style={{ padding: 12 }}>
          <Segmented disabled={!on} value={ancMode}
            items={[['off', 'Выкл'], ['transp', 'Прозрачность'], ['anc', 'Шумоподав.']]}
            onChange={(m) => setAnc(m === 'off' ? cmf.ANC_OFF : m === 'transp' ? cmf.ANC_TRANSP : cmf.ANC_LEVELS[0][0])} />
        </View>
        {ancMode === 'anc' && (
          <Picker title="Сила" items={cmf.ANC_LEVELS} value={state.anc} onChange={setAnc} last disabled={!on} />
        )}
      </Card>

      <Card title="Звук" index={2}>
        <Picker title="Эквалайзер" items={cmf.EQ_PRESETS} value={state.eq} disabled={!on}
          onChange={(v) => { setState((s) => ({ ...s, eq: v })); send(cmf.SET.eq, [v, 0]); }} />
        <Row title="Ultra Bass" subtitle="Усиление низких частот" disabled={!on}
          right={<Switch disabled={!on} value={bass.on} onValueChange={(v) => setBass({ ...bass, on: v })} />} />
        {bass.on && (
          <View style={[st.row, st.rowLine]}>
            <Text style={[st.rowTitle, { flex: 1 }]}>Уровень</Text>
            <Segmented disabled={!on} value={bass.level} items={[1, 2, 3, 4, 5].map((n) => [n, String(n)])}
              onChange={(n) => setBass({ ...bass, level: n })} />
          </View>
        )}
        <Row title="Низкая задержка" subtitle="Для игр и видео" last disabled={!on}
          right={<Switch disabled={!on} value={!!state.lowlat}
            onValueChange={(v) => { setState((s) => ({ ...s, lowlat: v })); send(cmf.SET.lowlat, [v ? 1 : 2, 0]); }} />} />
      </Card>

      {cmf.SIDES.map(([side, sideName]) => (
        <Card key={side} index={side + 1} title={`Жесты — ${sideName.toLowerCase()} наушник`}>
          {cmf.GESTURES.map(([g, gName], i) => (
            <Picker key={g} title={gName} items={cmf.ACTIONS} value={state.gestures[`${side}:${g}`]}
              last={i === cmf.GESTURES.length - 1} disabled={!on}
              onChange={(act) => {
                setState((s) => ({ ...s, gestures: { ...s.gestures, [`${side}:${g}`]: act } }));
                send(cmf.SET.gesture, [1, side, 1, g, act]);
              }} />
          ))}
        </Card>
      ))}

      <Card title="Об устройстве" index={5}>
        <Row title="Прошивка" right={<Text style={st.pickValue}>{state.fw ?? '—'}</Text>} />
        <Row title="Адрес" last right={<Text style={st.pickValue}>{dev.address}</Text>} />
      </Card>
    </>
  );
}

function AirPodsScreen({ bonded }: { bonded?: BondedDevice }) {
  const info = useAirPods(true);
  const ear = (v?: boolean) => (v ? 'в ухе' : undefined);
  return (
    <>
      {!info && <Banner text="Ищу AirPods рядом… Откройте кейс возле телефона или наденьте наушники." />}
      <Card>
        <View style={st.battRow}>
          <BatteryCell label="Левый" value={info?.left} charging={info?.leftCh} extra={ear(info?.leftInEar)} />
          <BatteryCell label="Правый" value={info?.right} charging={info?.rightCh} extra={ear(info?.rightInEar)} />
          <BatteryCell label="Кейс" value={info?.case} charging={info?.caseCh} />
        </View>
      </Card>
      <Card title="Об устройстве" index={5}>
        <Row title="Модель" right={<Text style={st.pickValue}>{info?.model ?? bonded?.name ?? '—'}</Text>} />
        <Row title="Сигнал" last right={<Text style={st.pickValue}>{info ? `${info.rssi} дБм` : '—'}</Text>} />
      </Card>
      <Text style={st.note}>
        Заряд AirPods приходит шагом 10% — так их передаёт сам Apple. Шумоподавление на Android
        переключать нельзя без root: Android не даёт приложениям нужный канал связи. Его можно
        переключить долгим нажатием на ножку наушника.
      </Text>
    </>
  );
}

// --- другие марки: по профилю ---------------------------------------------------------------
const NOISE_LABEL: Record<Noise, string> = { off: 'Выкл', anc: 'Шумоподав.', transparency: 'Прозрачн.', adaptive: 'Адаптив.' };
const EARS_LABEL = { both: 'Оба наушника в ушах', one: 'Один наушник в ухе', case: 'В кейсе', none: 'Не в ушах' };

function ProfileScreen({ dev, profile, model }: { dev: BondedDevice; profile: Profile; model: ProfileModel }) {
  const [info, setInfo] = useState<Changes>({});
  const [status, setStatus] = useState<'connecting' | 'on' | 'off'>('connecting');
  const [error, setError] = useState<string>();
  const codec = useRef<ReturnType<typeof makeCodec> | null>(null);
  const uuids = model.uuids ?? (model.uuid ? [model.uuid] : []);
  const [attempt, setAttempt] = useState(0);

  function makeCodec() {
    const Cls = CODECS[profile.codec];
    return new Cls(model, (bytes) => BudsBt.writeSpp(dev.address, bytes.map((b) => b.toString(16).padStart(2, '0')).join('')));
  }

  useEffect(() => {
    let uuidIdx = 0;
    const tryNext = () => BudsBt.connectSpp(dev.address, uuids[uuidIdx] ?? '', -1).catch((e) => setError(String(e?.message ?? e)));
    const s1 = BudsBt.addListener('onSppState', (e) => {
      if (e.address !== dev.address) return;
      if (e.connected) {
        setStatus('on');
        setError(undefined);
        codec.current = makeCodec();
        codec.current.start();
      } else if (e.error && uuidIdx + 1 < uuids.length) {
        uuidIdx += 1;
        tryNext(); // у Sony две службы: пробуем вторую
      } else {
        setStatus('off');
        if (e.error) setError(e.error);
      }
    });
    const s2 = BudsBt.addListener('onSppData', (e) => {
      if (e.address !== dev.address || !codec.current) return;
      const ch = codec.current.feed(Array.from({ length: e.hex.length / 2 }, (_, i) => parseInt(e.hex.substr(i * 2, 2), 16)));
      if (Object.keys(ch).length) setInfo((o) => ({ ...o, ...ch }));
    });
    tryNext();
    const poll = setInterval(() => codec.current?.poll(), 30_000);
    return () => { s1.remove(); s2.remove(); clearInterval(poll); BudsBt.disconnectSpp(dev.address); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dev.address, attempt]);

  useEffect(() => {
    if (info.left != null || info.right != null) {
      saveBattery('profile', {
        name: dev.name, left: info.left, right: info.right, case: info.case,
        leftCh: info.left_ch, rightCh: info.right_ch, caseCh: info.case_ch, at: Date.now(),
      });
    }
  }, [info.left, info.right, info.case, info.left_ch, info.right_ch, info.case_ch, dev.name]);

  const on = status === 'on';
  const modes = (model.modes ?? []).filter((m) => NOISE_LABEL[m]);
  return (
    <>
      {!on && (
        <Banner onPress={() => { setStatus('connecting'); setAttempt((a) => a + 1); }}
          text={status === 'connecting' ? 'Подключаюсь к наушникам…'
            : `Наушники не на связи. Нажмите здесь, чтобы попробовать снова.${error ? `\n(${error})` : ''}`} />
      )}
      <Card>
        <View style={st.battRow}>
          <BatteryCell label="Левый" value={info.left} charging={info.left_ch} />
          <BatteryCell label="Правый" value={info.right} charging={info.right_ch} />
          <BatteryCell label="Кейс" value={info.case} charging={info.case_ch} />
        </View>
      </Card>
      {modes.length > 0 && (
        <Card title="Шумоподавление" index={1}>
          <View style={{ padding: 12 }}>
            <Segmented disabled={!on} value={info.noise} items={modes.map((m) => [m, NOISE_LABEL[m]])}
              onChange={(m) => { setInfo((o) => ({ ...o, noise: m })); codec.current?.setNoise(m); }} />
          </View>
        </Card>
      )}
      <Card title="Об устройстве" index={2}>
        <Row title="В ушах" right={<Text style={st.pickValue}>{info.ears ? EARS_LABEL[info.ears] : '—'}</Text>} />
        <Row title="Профиль" right={<Text style={st.pickValue}>{profile.name}</Text>} />
        <Row title="Адрес" last right={<Text style={st.pickValue}>{dev.address}</Text>} />
      </Card>
      {profile.tested === false && (
        <Text style={st.note}>
          Профиль собран по описаниям из открытых проектов и ещё не проверен на настоящих наушниках.
          Если что-то не работает — напишите нам на GitHub.
        </Text>
      )}
    </>
  );
}

/** Наушники, для которых в приложении нет профиля. */
function OtherScreen({ dev }: { dev: BondedDevice }) {
  const found = findProfile(dev.name);
  if (found) return <ProfileScreen key={found.profile.id} dev={dev} profile={found.profile} model={found.model} />;
  return (
    <Card>
      <Row title={dev.name} subtitle={dev.address} />
      <Row title="Эти наушники пока не поддерживаются" last
        subtitle="Сейчас приложение умеет CMF Buds / Nothing, AirPods, Samsung Galaxy Buds и Sony" />
    </Card>
  );
}

// --- приложение -----------------------------------------------------------------------
export default function App() {
  const [ready, setReady] = useState<boolean | null>(null);
  const [devices, setDevices] = useState<BondedDevice[]>([]);
  const [tab, setTab] = useState<string>();

  const init = useCallback(async () => {
    const ok = await askPermissions();
    setReady(ok);
    if (ok) setDevices(BudsBt.bondedDevices());
  }, []);
  useEffect(() => {
    askPermissions().then((ok) => {
      setReady(ok);
      if (ok) setDevices(BudsBt.bondedDevices());
    });
  }, []);

  const cmfDev = devices.find((d) => d.name.toUpperCase().startsWith('CMF'));
  const podsDev = devices.find((d) => d.name.toUpperCase().includes('AIRPODS'));
  const others = devices.filter((d) => d !== cmfDev && d !== podsDev && d.audio === '1');
  const tabs: [string, string][] = [
    ['cmf', cmfDev?.name ?? 'CMF Buds'], ['airpods', podsDev?.name ?? 'AirPods'],
    ...others.map((d): [string, string] => [d.address, d.name]),
  ];
  const current = tab ?? (cmfDev && !podsDev ? 'cmf' : podsDev || !cmfDev ? 'airpods' : 'cmf');
  const otherDev = others.find((d) => d.address === current);

  let body: React.ReactNode;
  if (ready === null) body = null;
  else if (!ready) {
    body = (
      <Card>
        <Row title="Нужен доступ к Bluetooth" subtitle="Без него приложение не видит наушники. Нажмите, чтобы разрешить."
          onPress={init} />
        <Row title="Открыть настройки приложения" last onPress={() => Linking.openSettings()} />
      </Card>
    );
  } else if (!BudsBt.isEnabled()) {
    body = <Card><Row title="Bluetooth выключен" subtitle="Включите Bluetooth и нажмите здесь" last onPress={init} /></Card>;
  } else {
    body = (
      <>
        <View style={{ marginBottom: 18 }}>
          <Segmented value={current} onChange={setTab} items={tabs} />
        </View>
        <Animated.View key={current} entering={fadeSwap}>
        {current === 'cmf' ? (
          cmfDev ? <CmfScreen key={cmfDev.address} dev={cmfDev} /> : (
            <Card><Row title="CMF Buds не найдены" subtitle="Сначала подключите их в настройках Bluetooth телефона, потом нажмите здесь" last onPress={init} /></Card>
          )
        ) : otherDev ? <OtherScreen dev={otherDev} /> : <AirPodsScreen bonded={podsDev} />}
        </Animated.View>
      </>
    );
  }

  return (
    <View style={st.root}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={st.scroll}>
        <Text style={st.h1}>Наушники</Text>
        {body}
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  scroll: { padding: 16, paddingTop: 56, paddingBottom: 40 },
  h1: { color: C.text, fontSize: 32, fontWeight: '800', marginBottom: 16 },
  battRow: { flexDirection: 'row', padding: 16, gap: 12 },
  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 13, minHeight: 52, gap: 12 },
  rowLine: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.line },
  rowTitle: { color: C.text, fontSize: 16 },
  rowSub: { color: C.sub, fontSize: 13, marginTop: 2 },
  pickValue: { color: C.sub, fontSize: 15 },
  backdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'flex-end' },
  sheet: { backgroundColor: C.card, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, paddingBottom: 32, maxHeight: '70%' },
  sheetTitle: { color: C.text, fontSize: 18, fontWeight: '700', marginBottom: 8 },
  sheetItem: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 14 },
  note: { color: C.sub, fontSize: 13, lineHeight: 19, marginHorizontal: 4 },
});
