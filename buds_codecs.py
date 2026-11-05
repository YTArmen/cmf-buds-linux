"""Кодеки наушников разных марок: как упаковать команду в байты и разобрать ответ.

Кодеки — это код, они встроены в программу. Профили (profiles/*.json) — только данные:
какие наушники каким кодеком говорят и какие у них режимы.

Источники (протоколы разобраны сообществом):
  Samsung — github.com/timschneeb/GalaxyBudsClient, Gadgetbridge (galaxy_buds)
  Sony    — Gadgetbridge (service/devices/sony/headphones)
Не проверено на настоящих наушниках этих марок.

Каждый кодек:
  codec = Codec(profile, send)        # send(bytes) — отправить в сокет
  codec.start()                       # первые пакеты после подключения
  codec.feed(data) -> dict            # разобрать пришедшие байты, вернуть изменения
  codec.set_noise("off" | "transparency" | "anc" | "adaptive")
  codec.poll()                        # периодический запрос заряда (если нужен)
Изменения: left/right/case (%), left_ch/right_ch/case_ch (bool), noise (строка),
ears ("both" | "one" | "none" | "case").
"""


def crc16_xmodem(data):
    c = 0
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) if c & 0x8000 else (c << 1)
            c &= 0xFFFF
    return c


class Codec:
    def __init__(self, profile, send):
        self.profile, self.send = profile, send
        self.buf = b""

    def start(self):
        pass

    def poll(self):
        pass

    def feed(self, data):
        return {}

    def set_noise(self, mode):
        pass


# --- Samsung Galaxy Buds -------------------------------------------------------
SAMSUNG_NOISE = {"off": 0, "anc": 1, "transparency": 2, "adaptive": 3}
SAMSUNG_NOISE_BACK = {v: k for k, v in SAMSUNG_NOISE.items()}


class SamsungCodec(Codec):
    """FD | заголовок LE (размер & 0x3FF) | id | данные | CRC16-XMODEM LE | DD.
    Первые Galaxy Buds (legacy): FE | тип | размер | id | данные | CRC | EE."""

    STATUS, EXT_STATUS, NOISE_UPDATE, NOISE_SET = 0x60, 0x61, 0x77, 0x78
    LIVE_ANC_SET, AMBIENT_SET, MANAGER_INFO = 0x98, 0x80, 0x88

    def __init__(self, profile, send):
        super().__init__(profile, send)
        self.legacy = bool(profile.get("legacy"))
        self.variant = profile.get("noise_variant", "modern")  # modern | live | ambient
        self.greeted = False

    def frame(self, msg_id, payload=b""):
        body = bytes([msg_id]) + bytes(payload)
        crc = crc16_xmodem(body)
        size = len(body) + 2
        if self.legacy:
            head = bytes([0xFE, 0x00, size])
            tail = 0xEE
        else:
            head = bytes([0xFD, size & 0xFF, (size >> 8) & 0x03])  # запрос: старший байт без флагов
            tail = 0xDD
        return head + body + bytes([crc & 0xFF, crc >> 8, tail])

    def frames(self):
        som, eom = (0xFE, 0xEE) if self.legacy else (0xFD, 0xDD)
        while True:
            i = self.buf.find(bytes([som]))
            if i < 0:
                self.buf = b""
                return
            self.buf = self.buf[i:]
            if len(self.buf) < 3:
                return
            size = self.buf[2] if self.legacy else (self.buf[1] | (self.buf[2] << 8)) & 0x3FF
            total = 3 + size + 1
            if size < 3 or size > 1000:
                self.buf = self.buf[1:]
                continue
            if len(self.buf) < total:
                return
            pkt = self.buf[:total]
            self.buf = self.buf[total:]
            body, crc = pkt[3:3 + size - 2], pkt[3 + size - 2:3 + size]
            if pkt[-1] != eom or crc16_xmodem(body) != (crc[0] | (crc[1] << 8)):
                continue  # битый пакет — пропустить
            yield body[0], body[1:]

    def feed(self, data):
        self.buf += data
        out = {}
        for msg_id, p in self.frames():
            if msg_id == self.STATUS and len(p) >= 7:
                if self.legacy:
                    out.update(left=p[1], right=p[2])
                    wear = p[5] if len(p) > 5 else 0
                    out["ears"] = {17: "both", 1: "one", 16: "one"}.get(wear, "none")
                else:
                    out.update(left=p[1], right=p[2], case=p[6])
                    out["ears"] = self._ears(p[5])
                    if len(p) >= 8:
                        out.update(left_ch=bool(p[7] & 0x10), right_ch=bool(p[7] & 0x04),
                                   case_ch=bool(p[7] & 0x01))
                if not self.greeted:
                    self.greeted = True
                    # как приложение Samsung: «я менеджер» — открывает часть функций
                    self.send(self.frame(self.MANAGER_INFO, [0x01, 0x01, 34]))
            elif msg_id == self.EXT_STATUS and len(p) >= 8:
                out.update(left=p[2], right=p[3], case=p[7])
                out["ears"] = self._ears(p[6])
                if len(p) > 12 and self.variant == "modern":
                    out["noise"] = SAMSUNG_NOISE_BACK.get(p[12])
                elif len(p) > 12 and self.variant == "live":
                    out["noise"] = "anc" if p[12] == 1 else "off"
            elif msg_id == self.NOISE_UPDATE and p:
                out["noise"] = SAMSUNG_NOISE_BACK.get(p[0])
        for k in ("left", "right", "case"):
            if out.get(k) == 0:
                out.pop(k)  # 0 у Samsung значит «неизвестно»
        return {k: v for k, v in out.items() if v is not None}

    @staticmethod
    def _ears(placement):
        l, r = placement >> 4, placement & 0x0F
        worn = [l, r].count(1)
        if worn:
            return "both" if worn == 2 else "one"
        return "case" if l in (3, 4) and r in (3, 4) else "none"

    def set_noise(self, mode):
        if self.variant == "live":
            self.send(self.frame(self.LIVE_ANC_SET, [1 if mode == "anc" else 0]))
        elif self.variant == "ambient":
            self.send(self.frame(self.AMBIENT_SET, [1 if mode == "transparency" else 0]))
        elif mode in SAMSUNG_NOISE:
            self.send(self.frame(self.NOISE_SET, [SAMSUNG_NOISE[mode]]))


# --- Sony ------------------------------------------------------------------------
class SonyCodec(Codec):
    """3E | тип | seq | длина (4 байта BE) | данные | сумма | 3C, с экранированием 3C/3D/3E.
    На каждую команду наушников отвечаем ACK, свои команды шлём по одной после их ACK."""

    ACK, CMD1 = 0x01, 0x0C

    def __init__(self, profile, send):
        super().__init__(profile, send)
        self.seq = 0
        self.queue = []
        self.waiting = False
        self.version = None  # 1 или 2 — узнаём из ответа на приветствие
        self.t2 = None       # тип блока шумоподавления у V2: 0x15 / 0x17
        self.wind = False
        self.level = 10      # уровень прозрачности, чтобы не сбрасывать

    @staticmethod
    def escape(b):
        out = bytearray()
        for x in b:
            if x in (0x3C, 0x3D, 0x3E):
                out += bytes([0x3D, x & 0xEF])
            else:
                out.append(x)
        return bytes(out)

    @staticmethod
    def unescape(b):
        out, i = bytearray(), 0
        while i < len(b):
            if b[i] == 0x3D and i + 1 < len(b):
                out.append(b[i + 1] | 0x10)
                i += 2
            else:
                out.append(b[i])
                i += 1
        return bytes(out)

    @classmethod
    def frame(cls, mtype, seq, payload=b""):
        n = len(payload)
        inner = bytes([mtype, seq, n >> 24 & 0xFF, n >> 16 & 0xFF, n >> 8 & 0xFF, n & 0xFF]) + bytes(payload)
        inner += bytes([sum(inner) & 0xFF])
        return b"\x3E" + cls.escape(inner) + b"\x3C"

    def command(self, payload):
        self.queue.append(bytes(payload))
        self._pump()

    def _pump(self):
        if not self.waiting and self.queue:
            self.waiting = True
            self.send(self.frame(self.CMD1, self.seq, self.queue.pop(0)))

    def start(self):
        self.command([0x00, 0x00])  # приветствие: наушники скажут версию протокола

    def poll(self):
        if self.version:
            self._ask_battery()

    def _ask_battery(self):
        if self.version == 1:
            self.command([0x10, 0x01])  # оба наушника
            self.command([0x10, 0x02])  # кейс
        else:
            self.command([0x22, 0x09])
            self.command([0x22, 0x0A])

    def feed(self, data):
        self.buf += data
        out = {}
        while True:
            i = self.buf.find(b"\x3E")
            if i < 0:
                self.buf = b""
                break
            j = self.buf.find(b"\x3C", i + 1)
            if j < 0:
                self.buf = self.buf[i:]
                break
            raw = self.unescape(self.buf[i + 1:j])
            self.buf = self.buf[j + 1:]
            if len(raw) < 7 or (sum(raw[:-1]) & 0xFF) != raw[-1]:
                continue
            mtype, seq = raw[0], raw[1]
            payload = raw[6:-1]
            if mtype == self.ACK:
                self.seq = seq
                self.waiting = False
                self._pump()
                continue
            self.send(self.frame(self.ACK, 1 - seq if seq in (0, 1) else 0))
            out.update(self._handle(payload))
        return out

    def _handle(self, p):
        if not p:
            return {}
        code = p[0]
        if code == 0x01 and self.version is None:  # ответ на приветствие
            self.version = 1 if len(p) <= 4 else 2
            self._ask_battery()
            if self.version == 1:
                self.command([0x66, 0x02])
            else:
                self.command([0x66, 0x17])
                self.command([0x66, 0x15])
            return {}
        if code in (0x11, 0x13, 0x23, 0x25) and len(p) >= 4:
            kind = p[1]
            if kind in (0x01, 0x09) and len(p) >= 6:
                out = {"left_ch": p[3] == 1, "right_ch": p[5] == 1}
                if p[2]:
                    out["left"] = p[2]
                if p[4]:
                    out["right"] = p[4]
                return out
            if kind in (0x02, 0x0A) and p[2]:
                return {"case": p[2], "case_ch": p[3] == 1}
            if kind == 0x00 and p[2]:
                return {"left": p[2], "right": p[2]}
            return {}
        if code in (0x67, 0x69):
            return self._noise_v1(p) if self.version == 1 else self._noise_v2(p)
        return {}

    def _noise_v1(self, p):
        if len(p) != 8:
            return {}
        self.wind = p[3] == 0x02
        self.level = p[7] or self.level
        if p[2] == 0x00:
            return {"noise": "off"}
        anc = p[4] == (0x02 if self.wind else 0x01)
        return {"noise": "anc" if anc else "transparency"}

    def _noise_v2(self, p):
        if len(p) < 6 or p[1] not in (0x15, 0x17, 0x22):
            return {}
        self.t2 = p[1] if p[1] != 0x22 else self.t2
        self.wind = p[1] == 0x17 and len(p) > 7
        self.level = p[-1] or self.level
        if p[3] == 0x00:
            return {"noise": "off"}
        if p[1] == 0x22:
            return {"noise": "transparency"}
        return {"noise": "transparency" if p[4] == 0x01 else "anc"}

    def set_noise(self, mode):
        if self.version is None:
            return
        on = mode != "off"
        amb = mode == "transparency"
        if self.version == 1:
            if self.wind:
                m = 2 if mode == "anc" else 0
                self.command([0x68, 0x02, 0x11 if on else 0x00, 0x02, m, 0x01, 0x00, self.level if amb else 0])
            else:
                self.command([0x68, 0x02, 0x11 if on else 0x00, 0x00, 1 if mode == "anc" else 0, 0x01, 0x00,
                              self.level if amb else 0])
        else:
            t = self.t2 or 0x15
            body = [0x68, t, 0x01, 0x01 if on else 0x00, 0x01 if amb else 0x00]
            if t == 0x17 and self.wind:
                body.append(0x02)
            body += [0x00, self.level if amb else 0]
            self.command(body)
        self.command([0x66, 0x02] if self.version == 1 else [0x66, self.t2 or 0x15])


CODECS = {"samsung": SamsungCodec, "sony": SonyCodec}
