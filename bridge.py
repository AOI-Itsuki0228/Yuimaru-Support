"""
USB接続用の橋渡しスクリプト

StackChan --USB--> bridge.py --HTTP--> server.py(/talk) --> bridge.py --USB--> StackChan

使い方:
    pip install pyserial requests
    python bridge.py
先に server.py を起動しておくこと。StackChan は env:usb で書き込んでおくこと。
PlatformIO のシリアルモニターは閉じておくこと(COMポートを同時に使えない)。
"""
import struct
import sys
import time

import requests
import serial
from serial.tools import list_ports

# ===== 設定 =====
SERVER_URL = "http://127.0.0.1:8000/talk"   # 別PCのサーバーなら、そのIPに変更
PORT = None            # None=自動検出(Espressif製USB)。固定するなら "COM10" など
BAUD = 115200
HTTP_TIMEOUT = 180     # 秒
DTR_RTS = False        # つながらないときは True にしてみる
BLOCK = 1024           # main.cpp の RX_BLOCK と同じ値にすること
DEVICE_ID = "usb"       # サーバーに伝える台のID(devices.toml の [devices.usb] で性格を割り当てられる)
# =================

REQ_MAGIC = b"WAV!"
RES_MAGIC = b"RES!"
NO_REPLY = 0
ERROR_LEN = 0xFFFFFFFF
MIN_IN, MAX_IN = 44, 1_000_000


def find_port():
    if PORT:
        return PORT
    for p in list_ports.comports():
        if p.vid == 0x303A:            # Espressif
            return p.device
    return None


def open_port(port):
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = BAUD
    ser.timeout = 1
    ser.write_timeout = 10
    ser.dtr = DTR_RTS                  # 開くときにボードがリセットされるのを防ぐ
    ser.rts = DTR_RTS
    ser.open()
    return ser


def read_exact(ser, n, timeout=15):
    buf = bytearray()
    deadline = time.time() + timeout
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if chunk:
            buf += chunk
            deadline = time.time() + timeout
        elif time.time() > deadline:
            raise TimeoutError(f"{len(buf)}/{n} bytes で受信が止まりました")
    return bytes(buf)


def wait_request(ser):
    """先頭の合図 'WAV!' が来るまで読み捨てる"""
    window = b""
    while True:
        b = ser.read(1)
        if not b:
            continue                    # 1秒タイムアウト(Ctrl+C を効かせるため)
        window = (window + b)[-4:]
        if window == REQ_MAGIC:
            return


def wait_ack(ser, idx, total, timeout=10):
    """StackChan が1ブロック受け取ったら 'A' を1バイト返す"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        b = ser.read(1)
        if b == b"A":
            return
    raise TimeoutError(
        f"StackChan からの受信確認(ACK)が来ません: ブロック {idx + 1}/{total} "
        f"(ここまでに {idx * BLOCK} bytes 送信済み)")


def send_response(ser, length, body=b""):
    ser.write(RES_MAGIC + struct.pack("<I", length))
    ser.flush()
    total = (len(body) + BLOCK - 1) // BLOCK
    for idx in range(total):
        ser.write(body[idx * BLOCK:(idx + 1) * BLOCK])
        ser.flush()
        wait_ack(ser, idx, total)       # 取りこぼし防止: 受け取り確認が来るまで次を送らない


def handle(ser):
    wait_request(ser)
    n = struct.unpack("<I", read_exact(ser, 4, 5))[0]
    if not (MIN_IN <= n <= MAX_IN):
        print(f"不正な長さ {n}、読み捨てます")
        ser.reset_input_buffer()
        return
    wav = read_exact(ser, n)
    print(f"受信 {n} bytes -> サーバーへ送信")

    t = time.time()
    try:
        r = requests.post(SERVER_URL, data=wav,
                          headers={"Content-Type": "audio/wav",
                                   "X-Device-Id": DEVICE_ID},
                          timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        print("サーバーに接続できません:", e)
        send_response(ser, ERROR_LEN)
        return

    dt = time.time() - t
    if r.status_code == 200 and r.content:
        print(f"返事 {len(r.content)} bytes [{dt:.1f}s] -> StackChanへ")
        send_response(ser, len(r.content), r.content)
    elif r.status_code == 204:
        print(f"返事なし(無視) [{dt:.1f}s]")
        send_response(ser, NO_REPLY)
    else:
        print(f"サーバーエラー HTTP {r.status_code} [{dt:.1f}s]")
        send_response(ser, ERROR_LEN)


def main():
    while True:
        port = find_port()
        if not port:
            print("StackChan のUSBが見つかりません。接続を確認(再試行中)...")
            time.sleep(2)
            continue

        ser = None
        try:
            ser = open_port(port)
            print(f"接続: {port}  (Ctrl+C で終了)")
            time.sleep(2)               # 開いた直後のリセットが入る場合の待ち
            ser.reset_input_buffer()
            while True:
                try:
                    handle(ser)
                except TimeoutError as e:
                    print("タイムアウト:", e)
                    ser.reset_input_buffer()
        except (serial.SerialException, OSError) as e:
            print("シリアルエラー(ケーブルが抜けた?):", e)
            time.sleep(2)
        except KeyboardInterrupt:
            print("終了します")
            return
        finally:
            if ser and ser.is_open:
                ser.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
