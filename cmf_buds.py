#!/usr/bin/env python3
"""Настройки наушников для Linux: CMF Buds и AirPods.

CMF Buds: Bluetooth RFCOMM, канал 15, протокол Nothing (пакеты 55 60 01 ... + CRC16).
Проверено 03.11.2026 на CMF Buds, прошивка 1.0.5.050.
AirPods: Bluetooth L2CAP, PSM 0x1001, протокол Apple AAP (пакеты 04 00 04 00 ...).
Проверено 05.11.2026 на AirPods Pro 2.
Неофициальная программа, не связана с Nothing Technology и Apple.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402


# --- поиск наушников -------------------------------------------------------
def _bt(*args):
    try:
        return subprocess.run(["bluetoothctl", *args], capture_output=True,
                              text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


AIRPODS_MODELS = {0x2002: "AirPods", 0x200F: "AirPods 2", 0x2013: "AirPods 3",
                  0x200E: "AirPods Pro", 0x2014: "AirPods Pro 2",
                  0x2024: "AirPods Pro 2 (USB-C)", 0x200A: "AirPods Max",
                  0x2019: "AirPods 4", 0x201B: "AirPods 4 (шумоподавление)"}


AIRPODS_MODEL_OF = {}  # адрес -> модель по Modalias


def find_devices():
    """Список (вид, адрес, название) сопряжённых наушников: 'cmf' или 'airpods'.

    Адрес CMF можно задать аргументом или переменной CMF_BUDS_MAC, AirPods — AIRPODS_MAC.
    """
    found = []
    cmf_mac = os.environ.get("CMF_BUDS_MAC")
    if len(sys.argv) > 1 and sys.argv[1].count(":") == 5:
        cmf_mac = sys.argv[1]
    if cmf_mac:
        found.append(("cmf", cmf_mac.upper(), "CMF Buds"))
    if os.environ.get("AIRPODS_MAC"):
        found.append(("airpods", os.environ["AIRPODS_MAC"].upper(), "AirPods"))
    for line in _bt("devices", "Paired").splitlines():
        parts = line.split(" ", 2)
        if len(parts) != 3 or any(mac == parts[1] for _, mac, _ in found):
            continue
        mac, name = parts[1], parts[2].strip()
        if name.upper().startswith("CMF BUDS") and not cmf_mac:
            found.append(("cmf", mac, name))
            continue
        info = _bt("info", mac)
        if "Modalias: bluetooth:v004C" in info or "AIRPODS" in name.upper():
            model = name
            for ln in info.splitlines():
                if "Modalias: bluetooth:v004Cp" in ln:
                    pid = int(ln.split("v004Cp")[1][:4], 16)
                    model = AIRPODS_MODELS.get(pid, name)
            if "AIRPODS" in model.upper() or "AIRPODS" in name.upper():
                AIRPODS_MODEL_OF[mac] = model
                found.append(("airpods", mac, name))  # на вкладке — имя из Bluetooth
    return found


def is_connected(mac):
    return "Connected: yes" in _bt("info", mac)


# --- общее: фоновое соединение ---------------------------------------------
class Link:
    """Держит соединение в фоне и переподключается. Ответы отдаются в on_packet."""

    def __init__(self, mac, on_packet, on_state):
        self.mac, self.on_packet, self.on_state = mac, on_packet, on_state
        self.sock = None
        self.enabled = True  # False — наушники скрыты, не подключаться
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def set_enabled(self, on):
        self.enabled = on
        if not on:
            with self.lock:
                if self.sock:
                    try:
                        self.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

    def send_raw(self, data):
        with self.lock:
            if not self.sock:
                return False
            try:
                self.sock.send(data)
                return True
            except OSError:
                return False

    def _loop(self):
        while True:
            # Ждём, пока наушники подключит сама система. Если подключиться первыми,
            # система решит, что связь уже есть, и не включит звук (A2DP).
            if not self.enabled or not is_connected(self.mac):
                time.sleep(3)
                continue
            time.sleep(2)  # дать системе подключить звук
            try:
                s = self.open()
                with self.lock:
                    self.sock = s
                self.on_state(True)
                self.read_forever(s)
            except OSError:
                pass
            with self.lock:
                if self.sock:
                    try:
                        self.sock.close()
                    except OSError:
                        pass
                self.sock = None
            self.on_state(False)
            time.sleep(4)


# --- CMF Buds (протокол Nothing) -------------------------------------------
READ_BATTERY, READ_ANC, READ_EQ = 0xC007, 0xC01E, 0xC01F
READ_GESTURES, READ_LOWLAT, READ_FW, READ_BASS = 0xC018, 0xC041, 0xC042, 0xC04E
SET_GESTURE, SET_ANC, SET_EQ, SET_LOWLAT, SET_BASS = 0xF003, 0xF00F, 0xF010, 0xF040, 0xF051

ANC_OFF, ANC_HIGH, ANC_MID, ANC_LOW, ANC_TRANSP = 0x05, 0x01, 0x02, 0x03, 0x07
ANC_LEVELS = [(ANC_HIGH, "Сильное"), (ANC_MID, "Среднее"), (ANC_LOW, "Слабое")]

EQ_PRESETS = [(0, "Сбалансированный"), (3, "Больше баса"), (2, "Больше высоких"),
              (1, "Голос"), (5, "Свой (из телефона)")]

GESTURES = [(2, "Двойное касание"), (3, "Тройное касание"),
            (7, "Касание и удержание"), (9, "Двойное касание и удержание")]
ACTIONS = [(0x01, "Нет действия"), (0x08, "Пауза / воспроизведение"),
           (0x09, "Следующий трек"), (0x0A, "Предыдущий трек"),
           (0x0B, "Голосовой помощник"), (0x12, "Громче"), (0x13, "Тише"),
           (0x16, "Шумоподавление (переключить)")]
SIDES = [(2, "Левый наушник"), (3, "Правый наушник")]


def crc16(data):
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


def make_packet(cmd, payload=b""):
    head = bytes([0x55, 0x60, 0x01, cmd & 0xFF, cmd >> 8,
                  len(payload) & 0xFF, len(payload) >> 8, 0x01]) + bytes(payload)
    c = crc16(head)
    return head + bytes([c & 0xFF, c >> 8])


class CmfLink(Link):
    CHANNEL = 15

    def send(self, cmd, payload=b""):
        return self.send_raw(make_packet(cmd, payload))

    def open(self):
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        s.settimeout(5)
        s.connect((self.mac, self.CHANNEL))
        s.settimeout(None)
        return s

    def read_forever(self, s):
        buf = b""
        while True:
            data = s.recv(1024)
            if not data:
                raise OSError("closed")
            buf = self._parse(buf + data)

    def _parse(self, buf):
        while True:
            i = buf.find(b"\x55")
            if i < 0:
                return b""
            buf = buf[i:]
            if len(buf) < 8:
                return buf
            n = buf[5] | (buf[6] << 8)
            total = 8 + n + (2 if buf[1] else 0)  # 0x60 = есть CRC, 0x00 = уведомление без CRC
            if n > 512:
                buf = buf[1:]
                continue
            if len(buf) < total:
                return buf
            cmd = buf[3] | (buf[4] << 8)
            self.on_packet(cmd, buf[8:8 + n])
            buf = buf[total:]


# --- AirPods (протокол Apple AAP) ------------------------------------------
AAP_HANDSHAKE = bytes.fromhex("00000400010002000000000000000000")
AAP_FEATURES = bytes.fromhex("040004004d00d700000000000000")
AAP_NOTIFY = bytes.fromhex("040004000f00ffffffff")
AAP_HEADER = b"\x04\x00\x04\x00"
OP_BATTERY, OP_EAR, OP_CONTROL = 0x04, 0x06, 0x09
CTL_NOISE, CTL_EAR_DETECT, CTL_ONE_BUD_ANC, CTL_CONVERSATION = 0x0D, 0x0A, 0x1B, 0x28
NOISE_MODES = [("off", 1, "Выкл"), ("anc", 2, "Шумоподав."),
               ("transp", 3, "Прозрачность"), ("adaptive", 4, "Адаптивный")]
EAR_IN, EAR_OUT, EAR_CASE = 0, 1, 2


class AirPodsLink(Link):
    PSM = 0x1001

    def set_control(self, ctl, value):
        return self.send_raw(AAP_HEADER + bytes([OP_CONTROL, 0, ctl, value, 0, 0, 0]))

    def open(self):
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        s.settimeout(5)
        s.connect((self.mac, self.PSM))
        s.send(AAP_HANDSHAKE)
        s.recv(1024)  # ответ на рукопожатие
        s.send(AAP_FEATURES)
        s.send(AAP_NOTIFY)
        s.settimeout(None)
        return s

    def read_forever(self, s):
        while True:
            data = s.recv(1024)
            if not data:
                raise OSError("closed")
            if data.startswith(AAP_HEADER) and len(data) >= 6:
                self.on_packet(data[4] | (data[5] << 8), data[6:])


def _mpris(method, only=None):
    """Позвать метод у плееров MPRIS через D-Bus. Возвращает плееры, у которых сработало.

    method='Pause' трогает только играющие плееры; only — список плееров для 'Play'.
    """
    done = []
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        names = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "ListNames", None, None,
                              Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
        for name in names:
            if not name.startswith("org.mpris.MediaPlayer2."):
                continue
            if only is not None and name not in only:
                continue
            try:
                status = bus.call_sync(
                    name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get",
                    GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "PlaybackStatus")),
                    None, Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
            except GLib.Error:
                continue
            if (method == "Pause" and status != "Playing") or (method == "Play" and status == "Playing"):
                continue
            bus.call(name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player",
                     method, None, None, Gio.DBusCallFlags.NONE, 2000, None, None)
            done.append(name)
    except GLib.Error:
        pass
    return done


def pause_media():
    """Поставить на паузу то, что играет. Вернёт список плееров, чтобы потом продолжить."""
    return _mpris("Pause")


def resume_media(players):
    """Продолжить только те плееры, которые мы сами поставили на паузу."""
    if players:
        _mpris("Play", only=players)


# --- страницы окна ---------------------------------------------------------
class DevicePage(Gtk.Box):
    """Общее для страниц: баннер о связи + список настроек."""

    WAIT_TEXT = "Наушники не на связи. Достаньте их из кейса — подключусь сам."

    def __init__(self, mac):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.mac = mac
        self.busy = False  # не слать команды, пока заполняем поля из ответа
        self.banner = Adw.Banner(title="Подключаюсь к наушникам…", revealed=True)
        self.append(self.banner)
        self.page = Adw.PreferencesPage(vexpand=True)
        self.append(self.page)

    def battery_group(self, items):
        g = Adw.PreferencesGroup(title="Заряд")
        rows = {}
        for key, name in items:
            row = Adw.ActionRow(title=name, subtitle="—")
            bar = Gtk.LevelBar(min_value=0, max_value=100, hexpand=True,
                               valign=Gtk.Align.CENTER, width_request=140)
            row.add_suffix(bar)
            g.add(row)
            rows[key] = (row, bar)
        self.page.add(g)
        return rows

    def state_from_thread(self, ok):
        GLib.idle_add(self.on_state, ok)

    def packet_from_thread(self, cmd, payload):
        GLib.idle_add(self._packet, cmd, payload)

    def _packet(self, cmd, payload):
        self.busy = True
        try:
            self.on_packet(cmd, payload)
        finally:
            self.busy = False
        return False

    def on_state(self, ok):
        self.set_controls_sensitive(ok)
        self.banner.set_revealed(not ok)
        if ok:
            self.read_all()
        else:
            self.banner.set_title(self.WAIT_TEXT)
        return False

    def read_all(self):
        pass


class CmfPage(DevicePage):
    def __init__(self, mac):
        super().__init__(mac)
        page = self.page
        self.batt = self.battery_group([(2, "Левый"), (3, "Правый"), (4, "Кейс")])

        g = Adw.PreferencesGroup(title="Шумоподавление")
        self.anc_group = Adw.ToggleGroup(margin_bottom=8)
        for name, label in [("off", "Выкл"), ("transp", "Прозрачность"), ("anc", "Шумоподавление")]:
            self.anc_group.add(Adw.Toggle(name=name, label=label))
        self.anc_group.connect("notify::active-name", self.on_anc_mode)
        g.add(self.anc_group)
        self.anc_level = Adw.ComboRow(title="Сила шумоподавления",
                                      model=Gtk.StringList.new([n for _, n in ANC_LEVELS]))
        self.anc_level.connect("notify::selected", self.on_anc_mode)
        g.add(self.anc_level)
        page.add(g)

        g = Adw.PreferencesGroup(title="Звук")
        self.eq = Adw.ComboRow(title="Эквалайзер",
                               model=Gtk.StringList.new([n for _, n in EQ_PRESETS]))
        self.eq.connect("notify::selected", self.on_eq)
        g.add(self.eq)
        self.bass = Adw.SwitchRow(title="Ultra Bass", subtitle="Усиление низких частот")
        self.bass.connect("notify::active", self.on_bass)
        g.add(self.bass)
        self.bass_level = Adw.SpinRow.new_with_range(1, 5, 1)
        self.bass_level.set_title("Уровень Ultra Bass")
        self.bass_level.connect("notify::value", self.on_bass)
        g.add(self.bass_level)
        self.lowlat = Adw.SwitchRow(title="Низкая задержка",
                                    subtitle="Для игр и видео, звук чуть хуже")
        self.lowlat.connect("notify::active", self.on_lowlat)
        g.add(self.lowlat)
        page.add(g)

        self.gest = {}
        for side, side_name in SIDES:
            g = Adw.PreferencesGroup(title=f"Жесты — {side_name.lower()}")
            for gtype, gname in GESTURES:
                row = Adw.ComboRow(title=gname,
                                   model=Gtk.StringList.new([n for _, n in ACTIONS]))
                row.connect("notify::selected", self.on_gesture, side, gtype)
                g.add(row)
                self.gest[(side, gtype)] = row
            page.add(g)

        g = Adw.PreferencesGroup(title="Об устройстве")
        self.fw = Adw.ActionRow(title="Прошивка", subtitle="—")
        g.add(self.fw)
        g.add(Adw.ActionRow(title="Адрес Bluetooth", subtitle=mac))
        page.add(g)

        self.set_controls_sensitive(False)
        self.link = CmfLink(mac, self.packet_from_thread, self.state_from_thread)
        GLib.timeout_add_seconds(30, self.poll_battery)

    def set_controls_sensitive(self, ok):
        for w in [self.anc_group, self.anc_level, self.eq, self.bass, self.bass_level,
                  self.lowlat, *self.gest.values()]:
            w.set_sensitive(ok)

    def read_all(self):
        for c in [READ_BATTERY, READ_ANC, READ_EQ, READ_BASS, READ_LOWLAT, READ_GESTURES, READ_FW]:
            self.link.send(c)

    def poll_battery(self):
        self.link.send(READ_BATTERY)
        return True

    def on_packet(self, cmd, p):
        if cmd in (0x4007, 0xE001) and p:  # заряд
            for i in range(p[0]):
                dev, lvl = p[1 + i * 2], p[2 + i * 2]
                if dev in self.batt:
                    row, bar = self.batt[dev]
                    pct = lvl & 0x7F
                    row.set_subtitle(f"{pct}%" + (" · заряжается" if lvl & 0x80 else ""))
                    bar.set_value(pct)
        elif cmd == 0x401E and len(p) >= 5:
            self.show_anc(p[4])
        elif cmd == 0xE003 and len(p) >= 2:  # сменили жестом на наушнике
            self.show_anc(p[1])
        elif cmd == 0x401F and p:
            idx = next((i for i, (v, _) in enumerate(EQ_PRESETS) if v == p[0]), None)
            if idx is not None:
                self.eq.set_selected(idx)
        elif cmd == 0x404E and len(p) >= 2:
            self.bass.set_active(p[0] == 1)
            self.bass_level.set_value(max(1, min(5, p[1] // 2)))
            self.bass_level.set_sensitive(p[0] == 1)
        elif cmd in (0x4041, 0xE005) and p:
            self.lowlat.set_active(p[0] == 1)
        elif cmd == 0x4042:
            self.fw.set_subtitle(p.decode(errors="replace"))
        elif cmd == 0x4018 and p:
            for i in range(p[0]):
                side, _, gtype, act = p[1 + i * 4: 5 + i * 4]
                row = self.gest.get((side, gtype))
                idx = next((j for j, (v, _) in enumerate(ACTIONS) if v == act), None)
                if row and idx is not None:
                    row.set_selected(idx)

    def show_anc(self, level):
        if level == ANC_OFF:
            self.anc_group.set_active_name("off")
        elif level == ANC_TRANSP:
            self.anc_group.set_active_name("transp")
        else:
            self.anc_group.set_active_name("anc")
            idx = next((i for i, (v, _) in enumerate(ANC_LEVELS) if v == level), 0)
            self.anc_level.set_selected(idx)
        self.anc_level.set_visible(self.anc_group.get_active_name() == "anc")

    def on_anc_mode(self, *_):
        mode = self.anc_group.get_active_name()
        self.anc_level.set_visible(mode == "anc")
        if self.busy:
            return
        level = {"off": ANC_OFF, "transp": ANC_TRANSP}.get(mode)
        if level is None:
            level = ANC_LEVELS[self.anc_level.get_selected()][0]
        self.link.send(SET_ANC, bytes([1, level, 0]))

    def on_eq(self, *_):
        if not self.busy:
            self.link.send(SET_EQ, bytes([EQ_PRESETS[self.eq.get_selected()][0], 0]))

    def on_bass(self, *_):
        on = self.bass.get_active()
        self.bass_level.set_sensitive(on)
        if not self.busy:
            self.link.send(SET_BASS, bytes([1 if on else 0, int(self.bass_level.get_value()) * 2]))

    def on_lowlat(self, *_):
        if not self.busy:
            self.link.send(SET_LOWLAT, bytes([1 if self.lowlat.get_active() else 2, 0]))

    def on_gesture(self, row, _pspec, side, gtype):
        if not self.busy:
            act = ACTIONS[row.get_selected()][0]
            self.link.send(SET_GESTURE, bytes([1, side, 1, gtype, act]))


class AirPodsPage(DevicePage):
    WAIT_TEXT = "AirPods не на связи. Откройте кейс или наденьте наушники — подключусь сам."

    def __init__(self, mac, model):
        super().__init__(mac)
        page = self.page
        self.ears = (None, None)
        self.paused_by_us = []  # плееры, которые мы поставили на паузу
        # 0x04 = левый, 0x02 = правый, 0x08 = кейс
        self.batt = self.battery_group([(0x04, "Левый"), (0x02, "Правый"), (0x08, "Кейс")])

        # шумоподавление есть только у Pro, Max и AirPods 4 с шумоподавлением;
        # адаптивный режим — у Pro 2 и AirPods 4 с шумоподавлением
        has_anc = any(w in model for w in ("Pro", "Max", "шумоподав"))
        has_adaptive = "Pro 2" in model or "шумоподав" in model
        g = Adw.PreferencesGroup(title="Шумоподавление", visible=has_anc)
        self.noise = Adw.ToggleGroup(margin_bottom=8)
        for name, _, label in NOISE_MODES:
            if name != "adaptive" or has_adaptive:
                self.noise.add(Adw.Toggle(name=name, label=label))
        self.noise.connect("notify::active-name", self.on_noise)
        g.add(self.noise)
        self.conversation = Adw.SwitchRow(
            title="Адаптация к разговору",
            subtitle="Когда вы заговорите, музыка станет тише")
        self.conversation.connect("notify::active", self.on_switch, CTL_CONVERSATION)
        g.add(self.conversation)
        self.one_bud = Adw.SwitchRow(
            title="Шумоподавление с одним наушником",
            subtitle="Работает, даже если в ухе только один AirPod")
        self.one_bud.connect("notify::active", self.on_switch, CTL_ONE_BUD_ANC)
        g.add(self.one_bud)
        page.add(g)

        g = Adw.PreferencesGroup(title="В ушах")
        self.ear_row = Adw.ActionRow(title="Сейчас", subtitle="—")
        g.add(self.ear_row)
        self.ear_detect = Adw.SwitchRow(
            title="Автоопределение уха",
            subtitle="Наушники сами понимают, что они в ушах. Если выключить, "
                     "звук всегда идёт в наушники, а пауза не срабатывает",
            active=True)
        self.ear_detect.connect("notify::active", self.on_switch, CTL_EAR_DETECT)
        g.add(self.ear_detect)
        self.autopause = Adw.SwitchRow(title="Пауза, когда вынимаете наушник",
                                       subtitle="Музыка и видео встанут на паузу, "
                                                "а когда вставите обратно — продолжатся",
                                       active=True)
        g.add(self.autopause)
        page.add(g)

        g = Adw.PreferencesGroup(title="Об устройстве")
        g.add(Adw.ActionRow(title="Модель", subtitle=model))
        g.add(Adw.ActionRow(title="Адрес Bluetooth", subtitle=mac))
        page.add(g)

        self.set_controls_sensitive(False)
        self.link = AirPodsLink(mac, self.packet_from_thread, self.state_from_thread)

    def set_controls_sensitive(self, ok):
        for w in [self.noise, self.conversation, self.one_bud, self.ear_detect, self.autopause]:
            w.set_sensitive(ok)

    def read_all(self):
        self.link.send_raw(AAP_NOTIFY)  # AirPods снова пришлют заряд и настройки

    def on_packet(self, op, p):
        if op == OP_BATTERY and p:
            for i in range(p[0]):
                part = p[1 + i * 5: 6 + i * 5]
                if len(part) < 5 or part[0] not in self.batt:
                    continue
                row, bar = self.batt[part[0]]
                level, status = part[2], part[3]
                if status == 4:  # не на связи (например, наушник в другом кейсе)
                    row.set_subtitle("нет связи")
                    bar.set_value(0)
                else:
                    row.set_subtitle(f"{level}%" + (" · заряжается" if status == 1 else ""))
                    bar.set_value(level)
        elif op == OP_CONTROL and len(p) >= 2:
            ctl, val = p[0], p[1]
            if ctl == CTL_NOISE:
                name = next((n for n, v, _ in NOISE_MODES if v == val), None)
                if name:
                    self.noise.set_active_name(name)
            elif ctl == CTL_CONVERSATION:
                self.conversation.set_active(val == 1)
            elif ctl == CTL_ONE_BUD_ANC:
                self.one_bud.set_active(val == 1)
            elif ctl == CTL_EAR_DETECT:
                self.ear_detect.set_active(val == 1)
                self.autopause.set_sensitive(val == 1)
        elif op == OP_EAR and len(p) >= 2:
            self.show_ears(p[0], p[1])

    def show_ears(self, a, b):
        in_ear = [a, b].count(EAR_IN)
        text = {2: "Оба наушника в ушах", 1: "Один наушник в ухе"}.get(in_ear)
        if not text:
            text = "Оба в кейсе" if a == b == EAR_CASE else "Не в ушах"
        self.ear_row.set_subtitle(text)
        before = [x for x in self.ears if x is not None].count(EAR_IN)
        known = self.ears != (None, None)
        auto = self.autopause.get_active() and self.ear_detect.get_active()
        if a == b == EAR_CASE:
            if known and auto and before:
                pause_media()
            self.paused_by_us = []  # убрали в кейс — потом сами не продолжаем
        elif known and auto and in_ear < before and before == 2:
            # вынули наушник: пауза; запомнить, что ставили мы
            self.paused_by_us = pause_media() or self.paused_by_us
        elif known and in_ear == 2 and before < 2 and self.paused_by_us:
            # вставили обратно: продолжить
            if auto:
                resume_media(self.paused_by_us)
            self.paused_by_us = []
        self.ears = (a, b)

    def on_noise(self, *_):
        if self.busy:
            return
        val = next((v for n, v, _ in NOISE_MODES if n == self.noise.get_active_name()), None)
        if val:
            self.link.set_control(CTL_NOISE, val)

    def on_switch(self, row, _pspec, ctl):
        if ctl == CTL_EAR_DETECT:
            self.autopause.set_sensitive(row.get_active())
        if not self.busy:
            self.link.set_control(ctl, 1 if row.get_active() else 2)


# --- окно ------------------------------------------------------------------
CONFIG = os.path.join(GLib.get_user_config_dir(), "cmf-buds", "settings.json")


def load_config():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Наушники")
        self.set_default_size(460, 780)
        self.cfg = load_config()
        self.hidden = set(self.cfg.get("hidden", []))

        view = Adw.ToolbarView()
        self.header = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Обновить")
        refresh.connect("clicked", self.on_refresh)
        self.header.pack_end(refresh)
        view.add_top_bar(self.header)
        self.set_content(view)

        self.stack = Adw.ViewStack()
        self.devices = find_devices()
        if not self.devices:
            view.set_content(Adw.StatusPage(
                icon_name="audio-headphones-symbolic", title="Наушники не найдены",
                description="Сначала подключите CMF Buds или AirPods в настройках Bluetooth, "
                            "потом откройте программу снова."))
            return

        self.pages = {}
        menu = Gio.Menu()
        section = Gio.Menu()
        for kind, mac, name in self.devices:
            if kind == "cmf":
                page = CmfPage(mac)
                icon = "audio-headphones-symbolic"
            else:
                page = AirPodsPage(mac, AIRPODS_MODEL_OF.get(mac, name))
                icon = "audio-headset-symbolic"
            self.pages[mac] = (self.stack.add_titled_with_icon(page, mac, name, icon), page)
            act = Gio.SimpleAction.new_stateful(
                "show-" + mac.replace(":", ""), None, GLib.Variant.new_boolean(mac not in self.hidden))
            act.connect("change-state", self.on_toggle_device, mac)
            self.add_action(act)
            section.append(name, "win.show-" + mac.replace(":", ""))
        menu.append_section("Показывать наушники", section)
        if len(self.devices) > 1:
            self.header.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                                                tooltip_text="Какие наушники показывать"))
        self.switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        view.set_content(self.stack)
        self.apply_visibility(prefer_connected=True)

    def apply_visibility(self, prefer_connected=False):
        visible = [d for d in self.devices if d[1] not in self.hidden] or self.devices[:1]
        for kind, mac, _ in self.devices:
            stack_page, page = self.pages[mac]
            on = any(v[1] == mac for v in visible)
            stack_page.set_visible(on)
            page.link.set_enabled(on)
        # открыть подключённые наушники, иначе первые видимые
        current = self.stack.get_visible_child_name()
        if prefer_connected or not any(v[1] == current for v in visible):
            pick = next((v for v in visible if is_connected(v[1])), visible[0])
            self.stack.set_visible_child_name(pick[1])
        if len(visible) > 1:
            self.header.set_title_widget(self.switcher)
        else:
            self.header.set_title_widget(None)
            self.set_title(visible[0][2])

    def on_toggle_device(self, action, value, mac):
        on = value.get_boolean()
        others = [d for d in self.devices if d[1] != mac and d[1] not in self.hidden]
        if not on and not others:
            return  # последние видимые наушники не скрываем
        action.set_state(value)
        (self.hidden.discard if on else self.hidden.add)(mac)
        self.cfg["hidden"] = sorted(self.hidden)
        save_config(self.cfg)
        self.apply_visibility()

    def on_refresh(self, *_):
        page = self.stack.get_visible_child()
        if page:
            page.read_all()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.ytarmen.CmfBuds")

    def do_activate(self):
        win = self.get_active_window() or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv[:1]))
