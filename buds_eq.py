"""Эквалайзер для любых наушников через PipeWire (filter-chain).

Как работает: запускаем отдельный процесс `pipewire -c eq.conf`. Он создаёт виртуальный выход
«Эквалайзер — <наушники>», звук из него проходит через 10 полос и уходит в наушники.
Этот выход ставим основным, при выключении возвращаем прежний.
Ползунки меняются на лету: `pw-cli set-param <узел> Props { params = [...] }`.
"""
import json
import os
import subprocess
import time

BANDS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
LABELS = ["32", "64", "125", "250", "500", "1к", "2к", "4к", "8к", "16к"]

PRESETS = [
    ("flat", "Ровный", [0] * 10),
    ("bass", "Больше баса", [6, 5, 4, 2, 0, 0, 0, 0, 0, 0]),
    ("bass_max", "Мощный бас", [9, 8, 6, 3, 0, -1, 0, 0, 0, 0]),
    ("vocal", "Голос", [-2, -2, -1, 0, 2, 4, 4, 2, 0, -1]),
    ("treble", "Больше высоких", [0, 0, 0, 0, 0, 1, 2, 4, 5, 5]),
    ("vshape", "Яркий (V)", [5, 4, 2, 0, -2, -2, 0, 2, 4, 5]),
    ("custom", "Свой", None),
]


def _dump():
    try:
        return json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def _nodes():
    for o in _dump():
        if o.get("type", "").endswith("Node"):
            yield o["id"], (o.get("info") or {}).get("props") or {}


def headphones_sink(mac):
    """Имя звукового выхода наушников в PipeWire (bluez_output.<адрес>)."""
    for _, p in _nodes():
        name = p.get("node.name", "")
        if p.get("media.class") == "Audio/Sink" and name.startswith("bluez_output.") and mac.upper() in name.upper():
            return name
    return None


def node_id(name):
    for i, p in _nodes():
        if p.get("node.name") == name:
            return i
    return None


def default_sink_name():
    try:
        out = subprocess.run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for ln in out.splitlines():
        if "node.name" in ln and "=" in ln:
            return ln.split("=", 1)[1].strip().strip('"')
    return None


def set_default(name):
    i = node_id(name)
    if i is not None:
        subprocess.run(["wpctl", "set-default", str(i)], capture_output=True, timeout=5)


def get_volume(name):
    i = node_id(name)
    if i is None:
        return None
    try:
        out = subprocess.run(["wpctl", "get-volume", str(i)], capture_output=True, text=True, timeout=5).stdout
        return float(out.split()[1])  # «Volume: 0.45»
    except (OSError, IndexError, ValueError, subprocess.TimeoutExpired):
        return None


def set_volume(name, vol):
    i = node_id(name)
    if i is not None and vol is not None:
        subprocess.run(["wpctl", "set-volume", str(i), f"{vol:.3f}"], capture_output=True, timeout=5)


def streams_into(node):
    """Потоки (плееры), которые сейчас играют в узел node."""
    ids = set()
    for o in _dump():
        if o.get("type", "").endswith("Link"):
            info = o.get("info") or {}
            if info.get("input-node-id") == node:
                ids.add(info.get("output-node-id"))
    return [i for i in ids if i is not None]


def move_streams(node, target_name):
    """Перевести плееры из node в другой выход на лету (без паузы)."""
    target = node_id(target_name)
    if target is None:
        return 0
    moved = 0
    for sid in streams_into(node):
        subprocess.run(["pw-metadata", str(sid), "target.object", target_name], capture_output=True, timeout=5)
        subprocess.run(["pw-metadata", str(sid), "target.node", str(target)], capture_output=True, timeout=5)
        moved += 1
    return moved


def preamp(gains):
    """Чтобы не было хрипа при подъёме полос, общий уровень чуть снижаем (на половину самого большого подъёма)."""
    return 10 ** (-max(0, max(gains)) / 2 / 20)


class Equalizer:
    def __init__(self, mac, title, conf_dir):
        self.mac, self.title, self.conf_dir = mac, title, conf_dir
        self.name = "buds_eq_" + mac.replace(":", "").lower()
        self.proc = None
        self.prev_default = None
        self.node = None
        self.target = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _conf(self, target, gains):
        nodes = []
        for i, (f, g) in enumerate(zip(BANDS, gains)):
            label = "bq_lowshelf" if i == 0 else "bq_highshelf" if i == len(BANDS) - 1 else "bq_peaking"
            q = 0.7 if label != "bq_peaking" else 1.0
            nodes.append(f'{{ type = builtin name = b{i} label = {label} '
                         f'control = {{ "Freq" = {f} "Q" = {q} "Gain" = {float(g)} }} }}')
        nodes.append(f'{{ type = builtin name = pre label = linear control = {{ "Mult" = {preamp(gains):.4f} "Add" = 0.0 }} }}')
        links = [f'{{ output = "b{i}:Out" input = "b{i + 1}:In" }}' for i in range(len(BANDS) - 1)]
        links.append(f'{{ output = "b{len(BANDS) - 1}:Out" input = "pre:In" }}')
        title = self.title.replace('"', "'")
        return f"""context.properties = {{ log.level = 0 }}
context.spa-libs = {{ audio.convert.* = audioconvert/libspa-audioconvert support.* = support/libspa-support }}
context.modules = [
  {{ name = libpipewire-module-rt flags = [ ifexists nofail ] }}
  {{ name = libpipewire-module-protocol-native }}
  {{ name = libpipewire-module-client-node }}
  {{ name = libpipewire-module-adapter }}
  {{ name = libpipewire-module-filter-chain
    args = {{
      node.description = "Эквалайзер — {title}"
      media.name = "Эквалайзер — {title}"
      filter.graph = {{
        nodes = [ {' '.join(nodes)} ]
        links = [ {' '.join(links)} ]
        inputs = [ "b0:In" ]
        outputs = [ "pre:Out" ]
      }}
      audio.channels = 2
      audio.position = [ FL FR ]
      capture.props = {{ node.name = "{self.name}" media.class = Audio/Sink }}
      playback.props = {{ node.name = "{self.name}.out" node.passive = true
                          target.object = "{target}" node.dont-reconnect = true }}
    }}
  }}
]
"""

    def start(self, gains):
        """Включить. Вернёт текст ошибки или None."""
        if self.running:
            self.set_gains(gains)
            return None
        target = headphones_sink(self.mac)
        if not target:
            return "Наушники не выводят звук. Подключите их как аудиоустройство."
        os.makedirs(self.conf_dir, exist_ok=True)
        path = os.path.join(self.conf_dir, self.name + ".conf")
        with open(path, "w") as f:
            f.write(self._conf(target, gains))
        cur = default_sink_name()
        if cur and cur != self.name:
            self.prev_default = cur
        self.proc = subprocess.Popen(["pipewire", "-c", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            self.node = node_id(self.name)
            if self.node is not None:
                break
            time.sleep(0.1)
        if self.node is None:
            self.stop()
            return "Не удалось запустить эквалайзер (PipeWire)."
        # громкость: эквалайзер забирает её себе, а наушники — на 100 %,
        # иначе кнопки громкости упрутся в прежний уровень наушников
        self.target = target
        vol = get_volume(target)
        set_volume(self.name, vol if vol is not None else 0.5)
        set_volume(target, 1.0)
        set_default(self.name)
        return None

    def set_gains(self, gains):
        if not self.running or self.node is None:
            return
        parts = []
        for i, g in enumerate(gains):
            parts += [f'"b{i}:Gain"', f"{float(g):.1f}"]
        parts += ['"pre:Mult"', f"{preamp(gains):.4f}"]
        subprocess.run(["pw-cli", "set-param", str(self.node), "Props", "{ params = [ " + " ".join(parts) + " ] }"],
                       capture_output=True, timeout=5)

    def stop(self):
        back = self.prev_default or self.target
        if self.running and self.target:
            vol = get_volume(self.name)  # вернуть наушникам ту громкость, что была у эквалайзера
            if vol is not None:
                set_volume(self.target, vol)
            # сначала увести звук из эквалайзера, потом закрыть его — иначе плееры встают на паузу
            if back and node_id(back) is not None:
                set_default(back)
                if self.node is not None and move_streams(self.node, back):
                    for _ in range(20):
                        if not streams_into(self.node):
                            break
                        time.sleep(0.05)
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.node = None, None
        if back and default_sink_name() in (None, self.name):
            set_default(back)
