"""Проверка кодеков на примерах из протоколов (запуск: python3 -m pytest tests или python3 tests/test_codecs.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buds_codecs import SamsungCodec, SonyCodec, crc16_xmodem  # noqa: E402

H = bytes.fromhex


def test_crc_xmodem():
    assert crc16_xmodem(b"123456789") == 0x31C3  # контрольное значение XMODEM


def test_samsung_anc_on_frame():
    sent = []
    c = SamsungCodec({}, sent.append)
    c.set_noise("anc")
    assert sent[0] == H("FD04007801D191DD")


def test_samsung_status_parse():
    sent = []
    c = SamsungCodec({}, sent.append)
    # ревизия, L=80, R=75, связаны, главный, L в ухе (1) / R в кейсе (3), кейс 40, заряжается кейс
    body = bytes([0x60, 0x01, 80, 75, 1, 1, 0x13, 40, 0x01])
    crc = crc16_xmodem(body)
    size = len(body) + 2
    pkt = bytes([0xFD, size, 0x10]) + body + bytes([crc & 0xFF, crc >> 8, 0xDD])
    out = c.feed(pkt[:5])  # пакет может прийти кусками
    out.update(c.feed(pkt[5:] + H("FD")))
    assert out == {"left": 80, "right": 75, "case": 40, "ears": "one",
                   "left_ch": False, "right_ch": False, "case_ch": True}
    assert sent and sent[0][3] == 0x88  # приветствие менеджера


def test_samsung_noise_update():
    c = SamsungCodec({}, lambda b: None)
    body = bytes([0x77, 0x02])
    crc = crc16_xmodem(body)
    assert c.feed(bytes([0xFD, 4, 0]) + body + bytes([crc & 0xFF, crc >> 8, 0xDD])) == {"noise": "transparency"}


def test_sony_frames():
    assert SonyCodec.frame(0x0C, 0, [0, 0]) == H("3E0C00000000020000 0E3C".replace(" ", ""))
    assert SonyCodec.frame(0x01, 0) == H("3E0100000000000 13C".replace(" ", ""))
    raw = bytes([0x3C, 0x3D, 0x3E, 0x41])
    assert SonyCodec.unescape(SonyCodec.escape(raw)) == raw
    assert SonyCodec.escape(raw) == H("3D2C3D2D3D2E41")


class FakeSony:
    """Имитация наушников Sony V2: отвечает ACK и данными."""

    def __init__(self):
        self.codec = None
        self.seen = []

    def on_send(self, data):
        raw = SonyCodec.unescape(data[1:-1])
        mtype, seq, payload = raw[0], raw[1], raw[6:-1]
        self.seen.append((mtype, payload.hex()))
        if mtype == 0x01:
            return
        replies = [SonyCodec.frame(0x01, 1 - seq)]
        if payload == b"\x00\x00":
            replies.append(SonyCodec.frame(0x0C, 0, H("0100010000000000")))
        elif payload[:1] == b"\x22" and payload[1] == 0x09:
            replies.append(SonyCodec.frame(0x0C, 0, bytes([0x23, 0x09, 90, 0, 85, 1])))
        elif payload[:1] == b"\x22" and payload[1] == 0x0A:
            replies.append(SonyCodec.frame(0x0C, 0, bytes([0x23, 0x0A, 60, 1])))
        elif payload == b"\x66\x17":
            replies.append(SonyCodec.frame(0x0C, 0, bytes([0x67, 0x17, 0x01, 0x01, 0x00, 0x02, 0x00, 0x00])))
        self.pending = getattr(self, "pending", []) + replies


def test_sony_session():
    dev = FakeSony()
    state = {}
    c = SonyCodec({}, dev.on_send)
    dev.codec = c
    c.start()
    for _ in range(20):
        p, dev.pending = getattr(dev, "pending", []), []
        if not p:
            break
        for r in p:
            state.update(c.feed(r))
    assert c.version == 2
    assert state["left"] == 90 and state["right"] == 85 and state["right_ch"] is True
    assert state["case"] == 60 and state["case_ch"] is True
    assert state["noise"] == "anc"
    c.set_noise("transparency")
    for r in dev.pending:
        c.feed(r)
    sets = [p for t, p in dev.seen if p.startswith("68")]
    assert sets and sets[0].startswith("681701010102"), sets


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
