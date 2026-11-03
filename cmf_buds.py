#!/usr/bin/env python3
"""CMF Buds — мини-программа настроек наушников (как приложение Nothing X).

Связь: Bluetooth RFCOMM, канал 15, протокол Nothing (пакеты 55 60 01 ... + CRC16).
Проверено 03.11.2026 на CMF Buds, прошивка 1.0.5.050.
Неофициальная программа, не связана с Nothing Technology.
"""
import os
import socket
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

CHANNEL = 15


def find_mac():
    """Адрес наушников: аргумент, переменная CMF_BUDS_MAC или поиск по имени в bluetoothctl."""
    if len(sys.argv) > 1 and sys.argv[1].count(":") == 5:
        return sys.argv[1].upper()
    if os.environ.get("CMF_BUDS_MAC"):
        return os.environ["CMF_BUDS_MAC"].upper()
    try:
        out = subprocess.run(["bluetoothctl", "devices", "Paired"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[2].strip().upper().startswith("CMF BUDS"):
            return parts[1]
    return None


MAC = find_mac()

# --- команды -------------------------------------------------------------
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


class Buds:
    """Соединение с наушниками в фоне, ответы отдаются в on_packet(cmd, payload)."""

    def __init__(self, on_packet, on_state):
        self.on_packet, self.on_state = on_packet, on_state
        self.sock = None
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def send(self, cmd, payload=b""):
        with self.lock:
            if not self.sock:
                return False
            try:
                self.sock.send(make_packet(cmd, payload))
                return True
            except OSError:
                return False

    def _loop(self):
        if not MAC:
            self.on_state(None)
            return
        while True:
            try:
                s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                s.settimeout(5)
                s.connect((MAC, CHANNEL))
                s.settimeout(None)
                with self.lock:
                    self.sock = s
                self.on_state(True)
                buf = b""
                while True:
                    data = s.recv(1024)
                    if not data:
                        raise OSError("closed")
                    buf += data
                    buf = self._parse(buf)
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


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CMF Buds")
        self.set_default_size(440, 760)
        self.busy = False  # не слать команды, пока заполняем поля из ответа

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Обновить")
        refresh.connect("clicked", lambda *_: self.read_all())
        header.pack_end(refresh)
        view.add_top_bar(header)

        self.banner = Adw.Banner(title="Подключаюсь к наушникам…", revealed=True)
        view.add_top_bar(self.banner)

        page = Adw.PreferencesPage()
        view.set_content(page)
        self.set_content(view)

        # Заряд
        g = Adw.PreferencesGroup(title="Заряд")
        self.batt = {}
        for dev, name in [(2, "Левый"), (3, "Правый"), (4, "Кейс")]:
            row = Adw.ActionRow(title=name, subtitle="—")
            bar = Gtk.LevelBar(min_value=0, max_value=100, hexpand=True,
                               valign=Gtk.Align.CENTER, width_request=140)
            row.add_suffix(bar)
            g.add(row)
            self.batt[dev] = (row, bar)
        page.add(g)

        # Шумоподавление
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

        # Звук
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

        # Жесты
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

        # Об устройстве
        g = Adw.PreferencesGroup(title="Об устройстве")
        self.fw = Adw.ActionRow(title="Прошивка", subtitle="—")
        g.add(self.fw)
        g.add(Adw.ActionRow(title="Адрес Bluetooth", subtitle=MAC or "—"))
        page.add(g)

        self.set_controls_sensitive(False)
        self.buds = Buds(self.packet_from_thread, self.state_from_thread)
        GLib.timeout_add_seconds(30, self.poll_battery)

    # --- связь ------------------------------------------------------------
    def state_from_thread(self, ok):
        GLib.idle_add(self.on_state, ok)

    def packet_from_thread(self, cmd, payload):
        GLib.idle_add(self.on_packet, cmd, payload)

    def on_state(self, ok):
        self.set_controls_sensitive(ok)
        if ok:
            self.banner.set_revealed(False)
            self.read_all()
        elif ok is None:
            self.banner.set_title("CMF Buds не найдены. Сначала подключите их в настройках Bluetooth.")
            self.banner.set_revealed(True)
        else:
            self.banner.set_title("Наушники не на связи. Достаньте их из кейса — подключусь сам.")
            self.banner.set_revealed(True)

    def set_controls_sensitive(self, ok):
        for w in [self.anc_group, self.anc_level, self.eq, self.bass, self.bass_level,
                  self.lowlat, *self.gest.values()]:
            w.set_sensitive(ok)

    def read_all(self):
        for c in [READ_BATTERY, READ_ANC, READ_EQ, READ_BASS, READ_LOWLAT, READ_GESTURES, READ_FW]:
            self.buds.send(c)

    def poll_battery(self):
        self.buds.send(READ_BATTERY)
        return True

    def on_packet(self, cmd, p):
        self.busy = True
        try:
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
        finally:
            self.busy = False
        return False

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

    # --- действия пользователя ----------------------------------------------
    def on_anc_mode(self, *_):
        mode = self.anc_group.get_active_name()
        self.anc_level.set_visible(mode == "anc")
        if self.busy:
            return
        level = {"off": ANC_OFF, "transp": ANC_TRANSP}.get(mode)
        if level is None:
            level = ANC_LEVELS[self.anc_level.get_selected()][0]
        self.buds.send(SET_ANC, bytes([1, level, 0]))

    def on_eq(self, *_):
        if not self.busy:
            self.buds.send(SET_EQ, bytes([EQ_PRESETS[self.eq.get_selected()][0], 0]))

    def on_bass(self, *_):
        on = self.bass.get_active()
        self.bass_level.set_sensitive(on)
        if not self.busy:
            self.buds.send(SET_BASS, bytes([1 if on else 0, int(self.bass_level.get_value()) * 2]))

    def on_lowlat(self, *_):
        if not self.busy:
            self.buds.send(SET_LOWLAT, bytes([1 if self.lowlat.get_active() else 2, 0]))

    def on_gesture(self, row, _pspec, side, gtype):
        if not self.busy:
            act = ACTIONS[row.get_selected()][0]
            self.buds.send(SET_GESTURE, bytes([1, side, 1, gtype, act]))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.ytarmen.CmfBuds")

    def do_activate(self):
        win = self.get_active_window() or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv[:1]))
