// Профили марок встроены в приложение (без скачивания из интернета).
// Источник — папка profiles/ в корне репозитория; при изменении скопировать сюда в src/builtin/.
import { CODECS, Profile, ProfileModel } from './codecs';
import samsung from './builtin/samsung-galaxy-buds.json';
import sony from './builtin/sony.json';

export const BUILTIN: Profile[] = ([samsung, sony] as Profile[]).filter((p) => !!CODECS[p.codec]);

export function matchModel(p: Profile, name: string): ProfileModel | undefined {
  return p.models.find((m) => name.toLowerCase().includes(m.match.toLowerCase()));
}

export function findProfile(name: string) {
  for (const p of BUILTIN) {
    const m = matchModel(p, name);
    if (m) return { profile: p, model: m };
  }
  return null;
}
