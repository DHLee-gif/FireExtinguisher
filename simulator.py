import argparse
import random
import struct
import sys
import threading
import time
import zlib

import requests


class ReturnHome(Exception):
    pass


def make_png(width, height, pixel):
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows += bytes(pixel(x, y))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + chunk(b"IEND", b""))


def fire_pixel(w, h):
    cx, cy = w / 2, h * 0.7
    def pixel(x, y):
        d = ((x - cx) ** 2 + ((y - cy) * 1.6) ** 2) ** 0.5 / (w / 2)
        heat = max(0.0, 1.0 - d)
        return (min(255, int(60 + 195 * heat * 1.4)), int(20 + 200 * heat * heat), int(10 + 40 * heat ** 4))
    return pixel


def after_pixel(w, h):
    def pixel(x, y):
        g = int(80 + 50 * (y / h) + random.randint(-8, 8))
        return (g, g + 5, g + 12)
    return pixel


W, H = 320, 240
BEFORE_PNG = make_png(W, H, fire_pixel(W, H))
AFTER_PNG = make_png(W, H, after_pixel(W, H))


class FireCar:
    def __init__(self, server, heartbeat_sec, step_sec):
        self.server = server.rstrip("/")
        self.heartbeat_sec = heartbeat_sec
        self.step_sec = step_sec
        self.action = "idle"
        self.water = 100.0
        self.http = requests.Session()
        self._hb_http = requests.Session()
        self._stop = threading.Event()

    def api(self, method, path, **kwargs):
        res = self.http.request(method, self.server + path, timeout=5, **kwargs)
        if res.status_code >= 400:
            raise RuntimeError(f"{method} {path} 실패 ({res.status_code}): {res.text}")
        return res.json()

    def send_heartbeat(self, http=None):
        (http or self.http).post(self.server + "/api/heartbeat",
                                 json={"action": self.action, "water_level": round(self.water, 1)}, timeout=5)

    def _heartbeat_loop(self):
        while not self._stop.wait(self.heartbeat_sec):
            try:
                self.send_heartbeat(self._hb_http)
            except requests.RequestException as e:
                log(f"heartbeat 실패: {e}")

    def start(self):
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def set_action(self, action):
        self.action = action
        log(f"동작 → {action}")
        self.send_heartbeat()

    def status(self, level, code, message):
        self.api("POST", "/api/status", json={"level": level, "code": code, "message": message})
        log(f"status [{level}] {code} - {message}")

    def water_log(self, action=None):
        self.api("POST", "/api/water", json={"water_level": round(self.water, 1), "action": action})
        log(f"water {self.water:.1f}% ({action or '-'})")

    def report_fire(self, temperature, score):
        res = self.api("POST", "/api/fire",
                       data={"temperature": temperature, "vision_score": score},
                       files={"image": ("before.png", BEFORE_PNG, "image/png")})
        log(f"화재 보고: event #{res['event_id']} (온도 {temperature}℃, 신뢰도 {score})")
        return res["event_id"]

    def spray(self, event_id, duration_ms, temp_after):
        time.sleep(duration_ms / 1000 / 2)
        self.water = max(0.0, self.water - duration_ms / 1000 * 8)
        self.api("POST", f"/api/fire/{event_id}/spray", json={"duration_ms": duration_ms, "temp_after": temp_after})
        log(f"분사 {duration_ms}ms → 온도 {temp_after}℃, 물 {self.water:.1f}%")
        self.send_heartbeat()

    def upload_after(self, event_id):
        self.api("POST", f"/api/fire/{event_id}/image", files={"image": ("after.png", AFTER_PNG, "image/png")})
        log("진화 후 사진 업로드")

    def close_fire(self, event_id, status):
        self.api("PUT", f"/api/fire/{event_id}", json={"status": status})
        log(f"event #{event_id} → {status}")

    def poll_command(self):
        return self.api("GET", "/api/command")["command"]

    def wait_command(self, wanted, timeout=None):
        deadline = time.time() + timeout if timeout else None
        while deadline is None or time.time() < deadline:
            cmd = self.poll_command()
            if cmd == "return" and "return" not in wanted:
                raise ReturnHome()
            if cmd in wanted:
                log(f"명령 수신: {cmd}")
                return cmd
            if cmd:
                log(f"명령 무시: {cmd}")
            time.sleep(1)
        return None

    def checkpoint(self):
        time.sleep(self.step_sec)
        cmd = self.poll_command()
        if cmd == "stop":
            log("명령 수신: stop")
            prev = self.action
            self.set_action("stopped")
            self.status("warning", "EMERGENCY_STOP", "관리자 긴급 정지")
            log("웹에서 [재개] 버튼을 누르면 계속합니다…")
            self.wait_command({"resume"})
            self.set_action(prev)
        elif cmd == "return":
            raise ReturnHome()
        elif cmd:
            log(f"명령 무시: {cmd}")


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def scenario(car, auto, resume_timeout):
    car.set_action("idle")
    if auto:
        while car.poll_command():
            pass
    else:
        log("웹 메인 화면에서 [출격] 버튼을 누르세요…")
        car.wait_command({"start"})

    car.set_action("patrol")
    car.status("normal", "PATROL_START", "순찰 시작")
    car.water_log()
    car.checkpoint()

    car.set_action("extinguish")
    event_id = car.report_fire(round(random.uniform(160, 240), 1), round(random.uniform(0.82, 0.97), 2))
    car.status("warning", "FIRE_DETECTED", f"화재 감지 (event #{event_id})")
    car.checkpoint()

    car.spray(event_id, 3000, 118.6)
    car.checkpoint()

    car.status("warning", "RESPRAY", "온도 미하강, 재분사")
    car.spray(event_id, 2000, 41.3)
    car.checkpoint()

    car.upload_after(event_id)
    car.close_fire(event_id, "extinguished")
    car.status("normal", "FIRE_EXTINGUISHED", f"진화 완료 (event #{event_id})")
    car.water_log()
    car.set_action("patrol")
    car.checkpoint()

    car.set_action("stopped")
    car.status("error", "MOTOR_STALL", "좌측 구동 모터 과부하 감지")
    if auto:
        log("(--auto) 재개 대기 없이 진행 - MOTOR_STALL 은 미해결로 남음")
        time.sleep(car.step_sec)
    else:
        log(f"웹에서 [재개] 버튼을 누르세요… (최대 {resume_timeout}초)")
        if car.wait_command({"resume"}, timeout=resume_timeout) is None:
            log("재개 명령이 없어 계속 진행합니다 (에러는 미해결 상태)")
    car.set_action("patrol")
    car.checkpoint()

    car.water = 14.0
    car.water_log("low")
    car.status("warning", "WATER_LOW", f"물 잔량 부족 ({car.water:.0f}%)")
    car.set_action("homing")
    car.water_log("homing")
    car.checkpoint()

    car.set_action("refill")
    time.sleep(car.step_sec)
    car.water = 100.0
    car.water_log("refilled")
    car.status("normal", "REFILL_DONE", "급수 완료, 순찰 재개")
    car.set_action("patrol")
    car.checkpoint()


def return_home(car):
    car.set_action("homing")
    car.status("normal", "RETURN_HOME", "기지로 복귀")
    time.sleep(car.step_sec)
    car.set_action("idle")
    car.status("normal", "DOCKED", "기지 도착, 대기")


def main():
    parser = argparse.ArgumentParser(description="FireCar RC카 시뮬레이터")
    parser.add_argument("--server", default="http://127.0.0.1:5000", help="관제 서버 주소")
    parser.add_argument("--auto", action="store_true", help="출격/재개 버튼 없이 자동 진행")
    parser.add_argument("--step", type=float, default=4.0, help="단계 사이 대기(초)")
    parser.add_argument("--heartbeat", type=float, default=2.0, help="heartbeat 주기(초)")
    parser.add_argument("--resume-timeout", type=int, default=120, help="에러 후 재개 대기 최대(초)")
    args = parser.parse_args()

    car = FireCar(args.server, args.heartbeat, args.step)
    try:
        car.send_heartbeat()
    except requests.RequestException as e:
        sys.exit(f"서버에 연결할 수 없습니다: {args.server} ({e})")

    car.start()
    try:
        try:
            scenario(car, args.auto, args.resume_timeout)
            log("시나리오 완료")
        except ReturnHome:
            log("명령 수신: return")
        return_home(car)
    except KeyboardInterrupt:
        log("중단")
    finally:
        car.stop()


if __name__ == "__main__":
    main()
