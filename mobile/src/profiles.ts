// Профили марок: хранятся на телефоне, скачиваются с GitHub по запросу (только данные).
import AsyncStorage from '@react-native-async-storage/async-storage';

import { CODECS, Profile, ProfileModel } from './codecs';

export const PROFILES_URL = 'https://raw.githubusercontent.com/YTArmen/cmf-buds-linux/main/profiles/';
const KEY = 'profiles-v1';

export type IndexEntry = { id: string; version: number; name: string; file: string; codec: string; match: string[] };

export function validProfile(p: unknown): p is Profile {
  const x = p as Profile;
  return !!x && typeof x === 'object' && /^[a-z0-9-]{1,40}$/.test(x.id ?? '') && !!CODECS[x.codec]
    && Array.isArray(x.models) && x.models.every((m) => typeof m?.match === 'string');
}

export async function localProfiles(): Promise<Profile[]> {
  try {
    const all = JSON.parse((await AsyncStorage.getItem(KEY)) ?? '[]');
    return Array.isArray(all) ? all.filter(validProfile) : [];
  } catch {
    return [];
  }
}

export function matchModel(p: Profile, name: string): ProfileModel | undefined {
  return p.models.find((m) => name.toLowerCase().includes(m.match.toLowerCase()));
}

export async function findLocal(name: string) {
  for (const p of await localProfiles()) {
    const m = matchModel(p, name);
    if (m) return { profile: p, model: m };
  }
  return null;
}

export async function findRemote(name: string): Promise<IndexEntry | null> {
  const r = await fetch(PROFILES_URL + 'index.json', { headers: { 'Cache-Control': 'no-cache' } });
  const idx = await r.json();
  for (const e of (idx?.profiles ?? []) as IndexEntry[]) {
    if (/^[a-z0-9-]+\.json$/.test(e.file) && e.match?.some((m) => name.toLowerCase().includes(m.toLowerCase()))) return e;
  }
  return null;
}

export async function download(entry: IndexEntry): Promise<Profile> {
  const r = await fetch(PROFILES_URL + entry.file, { headers: { 'Cache-Control': 'no-cache' } });
  const p = await r.json();
  if (!validProfile(p)) throw new Error('Профиль повреждён или нужна новая версия приложения');
  const all = (await localProfiles()).filter((x) => x.id !== p.id);
  all.push(p);
  await AsyncStorage.setItem(KEY, JSON.stringify(all));
  return p;
}
