#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
주소/거리/API Key 입력 팝업창(GUI).

기준 주소, 기준거리(km), TMAP APP KEY 를 입력받아 tmap_filter 의 2단계 처리
  1) 직선거리 x 우회계수(기본 1.2)로 1차 스크리닝
  2) 통과분만 TMAP 화물차 경로 API로 실제 거리/시간 조회
를 실행하고 결과 CSV(콘크리트_50km이내.csv 등)를 같은 폴더에 저장한다.

APP KEY 는 입력란에 직접 입력한다.
추가 설치 불필요(파이썬 기본 내장 Tkinter 사용).
실행:  python tmap_gui.py
"""

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import requests

import tmap_filter as tf

try:
    import config
except ImportError:
    config = None

HERE = os.path.dirname(os.path.abspath(__file__))


def _cfg(name, default=""):
    val = getattr(config, name, default) if config else default
    return val if val else default


class _QueueWriter:
    """print 출력을 GUI 로그창으로 흘려보내기 위한 stdout 대체."""
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        root.title("업체 거리 필터 (TMAP)")
        root.resizable(False, False)

        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(root, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        r = 0
        ttk.Label(frm, text="APP KEY").grid(row=r, column=0, sticky="w", **pad)
        self.appkey = ttk.Entry(frm, width=44, show="*")
        self.appkey.grid(row=r, column=1, columnspan=2, sticky="we", **pad)
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="표시", variable=self.show_key,
                        command=self._toggle_key).grid(row=r, column=3, sticky="w")

        r += 1
        ttk.Label(frm, text="기준 주소").grid(row=r, column=0, sticky="w", **pad)
        self.addr = ttk.Entry(frm, width=44)
        self.addr.grid(row=r, column=1, columnspan=2, sticky="we", **pad)
        oa = _cfg("ORIGIN_ADDRESS")
        if oa and not oa.startswith("여기에"):
            self.addr.insert(0, oa)

        r += 1
        ttk.Label(frm, text="또는 좌표(위도,경도)").grid(row=r, column=0, sticky="w", **pad)
        self.latlon = ttk.Entry(frm, width=44)
        self.latlon.grid(row=r, column=1, columnspan=2, sticky="we", **pad)
        ttk.Label(frm, text="(입력 시 주소 무시)", foreground="#888").grid(row=r, column=3, sticky="w")

        r += 1
        ttk.Label(frm, text="기준 거리 (km)").grid(row=r, column=0, sticky="w", **pad)
        self.maxkm = ttk.Entry(frm, width=10)
        self.maxkm.insert(0, "50")
        self.maxkm.grid(row=r, column=1, sticky="w", **pad)

        ttk.Label(frm, text="우회계수").grid(row=r, column=2, sticky="e", **pad)
        self.buffer = ttk.Entry(frm, width=8)
        self.buffer.insert(0, "1.2")
        self.buffer.grid(row=r, column=3, sticky="w", **pad)

        r += 1
        ttk.Label(frm, text="대상 파일").grid(row=r, column=0, sticky="w", **pad)
        self.use_con = tk.BooleanVar(value=True)
        self.use_asc = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="콘크리트", variable=self.use_con).grid(row=r, column=1, sticky="w")
        ttk.Checkbutton(frm, text="아스콘", variable=self.use_asc).grid(row=r, column=2, sticky="w")

        r += 1
        self.run_btn = ttk.Button(frm, text="실행", command=self.on_run)
        self.run_btn.grid(row=r, column=1, sticky="we", **pad)
        ttk.Button(frm, text="결과 폴더 열기", command=self.open_folder).grid(row=r, column=2, sticky="we", **pad)

        r += 1
        self.prog = ttk.Progressbar(frm, mode="indeterminate", length=420)
        self.prog.grid(row=r, column=0, columnspan=4, sticky="we", **pad)

        r += 1
        self.log = tk.Text(frm, width=64, height=16, wrap="word")
        self.log.grid(row=r, column=0, columnspan=4, sticky="nsew", **pad)
        self.log.configure(state="disabled")

    # ---------------- 동작 ----------------
    def _toggle_key(self):
        self.appkey.configure(show="" if self.show_key.get() else "*")

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def open_folder(self):
        try:
            os.startfile(HERE)  # Windows
        except AttributeError:
            import subprocess
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, HERE])

    def on_run(self):
        if self.worker and self.worker.is_alive():
            return
        app_key = self.appkey.get().strip()
        if not app_key or app_key.startswith("여기에"):
            messagebox.showwarning("입력 필요", "TMAP APP KEY 를 입력하세요.")
            return
        addr = self.addr.get().strip()
        latlon = self.latlon.get().strip()
        if not addr and not latlon:
            messagebox.showwarning("입력 필요", "기준 주소 또는 좌표를 입력하세요.")
            return
        try:
            max_km = float(self.maxkm.get())
            buf = float(self.buffer.get())
            if max_km <= 0 or buf <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("입력 오류", "거리와 우회계수는 0보다 큰 숫자여야 합니다.")
            return

        inputs = []
        if self.use_con.get():
            inputs.append("콘크리트_업체_좌표.csv")
        if self.use_asc.get():
            inputs.append("아스콘_업체_좌표.csv")
        if not inputs:
            messagebox.showwarning("입력 필요", "대상 파일을 하나 이상 선택하세요.")
            return

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self.prog.start(12)

        self.worker = threading.Thread(
            target=self._work, args=(app_key, addr, latlon, max_km, buf, inputs), daemon=True
        )
        self.worker.start()
        self.root.after(100, self._poll)

    def _work(self, app_key, addr, latlon, max_km, buf, inputs):
        old = sys.stdout
        sys.stdout = _QueueWriter(self.q)
        try:
            session = requests.Session()

            if latlon:
                try:
                    la, lo = [float(x) for x in latlon.replace(" ", "").split(",")]
                except ValueError:
                    print("[오류] 좌표 형식은 '위도,경도' 입니다. 예: 35.16,128.99")
                    return
                origin = (la, lo)
                print(f"기준점(좌표): 위도 {la}, 경도 {lo}")
            else:
                print(f"기준 주소 좌표 변환 중: {addr}")
                origin = tf.geocode(addr, app_key, session)
                print(f"기준점: 위도 {origin[0]}, 경도 {origin[1]}")

            for path in inputs:
                full = os.path.join(HERE, path)
                if not os.path.exists(full):
                    print(f"[건너뜀] 파일 없음: {path}")
                    continue
                tf.process_file(full, origin, max_km, app_key, session, buf)

            print("\n=== 완료 ===")
        except tf.TmapError as exc:
            print(f"[오류] {exc}")
        except Exception as exc:  # noqa
            print(f"[오류] {type(exc).__name__}: {exc}")
        finally:
            sys.stdout = old
            self.q.put("__DONE__")

    def _poll(self):
        done = False
        try:
            while True:
                item = self.q.get_nowait()
                if item == "__DONE__":
                    done = True
                else:
                    self._log(item)
        except queue.Empty:
            pass
        if done:
            self.prog.stop()
            self.run_btn.configure(state="normal")
        else:
            self.root.after(100, self._poll)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
