#!/usr/bin/env python3
"""Pi-hole v6 dashboard for the monochrome Waveshare 2.13-inch V4 HAT."""

import argparse
import importlib.util
import ipaddress
import json
import logging
import math
import random
import signal
import subprocess
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont

LOG = logging.getLogger("pihole-eink")
WIDTH, HEIGHT = 250, 122
DEFAULT_CONFIG = "/etc/pihole-eink.json"
THEME_DIR = Path(__file__).resolve().parent / "assets" / "hologram"
RICK_VOICE_PATH = Path(__file__).resolve().parent / "rick_voice.py"
TEXT_CONFIG_PATH = Path("/etc/pihole-eink-text.json")


@lru_cache(maxsize=16)
def theme_face(filename):
    """Place the upstream 75 x 75 artwork on white without resizing its pixels."""
    with Image.open(THEME_DIR / filename) as source:
        rgba = source.convert("RGBA")
    if rgba.size != (75, 75):
        raise ValueError("Hologram face must be 75 x 75 pixels")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, rgba).convert("1", dither=Image.Dither.NONE)



def load_text_config():
    """Load user-editable labels and quote banks; fall back safely on bad/missing JSON."""
    defaults = {
        "title": "RICK-HOLE",
        "status": {
            "enabled": "BLOCKING",
            "disabled": "PAUSED",
            "failed": "DNS FAILED",
            "unknown": "UNKNOWN",
            "error": "API ERROR"
        },
        "quote_font_size": 10,
        "quotes": {}
    }
    try:
        data = json.loads(TEXT_CONFIG_PATH.read_text())
        if not isinstance(data, dict):
            return defaults
        title = data.get("title")
        if isinstance(title, str) and title.strip():
            defaults["title"] = title.strip()[:18]
        status = data.get("status")
        if isinstance(status, dict):
            for key in defaults["status"]:
                value = status.get(key)
                if isinstance(value, str) and value.strip():
                    defaults["status"][key] = value.strip()[:18]
        quote_font_size = data.get("quote_font_size")
        if isinstance(quote_font_size, int) and 8 <= quote_font_size <= 12:
            defaults["quote_font_size"] = quote_font_size
        quotes = data.get("quotes")
        if isinstance(quotes, dict):
            cleaned = {}
            for category, lines in quotes.items():
                if isinstance(category, str) and isinstance(lines, list):
                    cleaned[category] = [
                        str(line).strip() for line in lines
                        if isinstance(line, str) and line.strip()
                    ]
            defaults["quotes"] = cleaned
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return defaults


@lru_cache(maxsize=1)
def rick_style():
    """Load Rickgotchi's own standalone phrase bank if installed."""
    if not RICK_VOICE_PATH.is_file():
        return {}
    spec = importlib.util.spec_from_file_location("rickgotchi_voice", RICK_VOICE_PATH)
    if spec is None or spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    style = getattr(module, "STYLE", {})
    english = style.get("en", {}) if isinstance(style, dict) else {}
    return english if isinstance(english, dict) else {}


def speech_category(face_name, state="enabled"):
    if state == "disabled":
        return "sleep"
    if state in {"failed", "unknown", "error"}:
        return "failure"
    return {
        "BORED.png": "idle",
        "HAPPY.png": "success",
        "SMART.png": "tech",
        "EXCITED.png": "exclaim",
        "INTENSE.png": "tech",
        "ANGRY.png": "angry",
        "SLEEP.png": "sleep",
        "BROKEN.png": "failure",
    }.get(face_name, "idle")


def random_rick_line(face_name=None, state="enabled"):
    category = speech_category(face_name, state)
    custom = load_text_config().get("quotes", {}).get(category, [])
    if custom:
        return str(random.choice(custom))
    style = rick_style()
    choices = style.get(category, []) if style else []
    if choices:
        return str(random.choice(choices))
    return "Science mode."




def wrap_pixels(draw, text, selected_font, max_width, max_lines=2):
    """Wrap/ellipsize a short speech line to fit the tiny e-ink panel."""
    words = str(text).replace("\n", " ").split()
    if not words:
        return []
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if draw.textlength(candidate, font=selected_font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
        else:
            # One very long token: trim it pixel-by-pixel.
            current = word
        if len(lines) >= max_lines - 1:
            break
    if len(lines) < max_lines and current:
        lines.append(current)
    # If words remain or final line is too wide, add an ellipsis.
    consumed = " ".join(lines)
    original = " ".join(words)
    if consumed != original or (lines and draw.textlength(lines[-1], font=selected_font) > max_width):
        if not lines:
            lines = [""]
        last = lines[-1]
        while last and draw.textlength(last + "...", font=selected_font) > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "..."
    return lines[:max_lines]


class APIError(Exception):
    """An error safe to display or log without revealing credentials."""


class PiHoleAPI:
    def __init__(self, url, password):
        parsed = urlparse(url)
        if (parsed.scheme != "http" or parsed.hostname not in
                {"127.0.0.1", "localhost", "::1"} or parsed.username or
                parsed.password or parsed.query or parsed.fragment or
                parsed.path.rstrip("/") != "/api"):
            raise APIError("Use a local HTTP API address, e.g. http://127.0.0.1/api")
        self.url = url.rstrip("/")
        self.password = password
        self.sid = None
        self.session = requests.Session()
        # The password is sent only over loopback, never through a proxy.
        self.session.trust_env = False

    def _request(self, method, endpoint, **kwargs):
        headers = {"X-FTL-SID": self.sid} if self.sid else {}
        self.session.cookies.clear()
        try:
            return self.session.request(
                method, self.url + endpoint, headers=headers,
                timeout=(3, 8), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise APIError("Cannot reach the local Pi-hole API") from None

    @staticmethod
    def _json(response):
        if not 200 <= response.status_code < 300:
            raise APIError("Pi-hole API returned HTTP %s" % response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise APIError("Pi-hole API did not return JSON") from None
        if not isinstance(data, dict) or "error" in data:
            raise APIError("Pi-hole API returned an error or unexpected data")
        return data

    def _login(self):
        self.sid = None
        response = self._request("POST", "/auth", json={"password": self.password})
        if response.status_code in (401, 403):
            raise APIError("Authentication failed; check the Pi-hole application password")
        data = self._json(response)
        session = data.get("session", {})
        if not session.get("valid") or not session.get("sid"):
            raise APIError("Authentication failed; use an application password if 2FA is on")
        self.sid = session["sid"]

    def get(self, endpoint):
        response = self._request("GET", endpoint)
        if response.status_code == 401:
            self._login()
            response = self._request("GET", endpoint)
        return self._json(response)

    def snapshot(self):
        summary = self.get("/stats/summary")
        state = self.get("/dns/blocking").get("blocking")
        # v6 uses strings; tolerate early API versions that used booleans.
        if state is True:
            state = "enabled"
        elif state is False:
            state = "disabled"
        if state not in {"enabled", "disabled", "failed", "unknown"}:
            raise APIError("Unrecognised Pi-hole blocking status")
        try:
            queries = summary["queries"]
            total, blocked = queries["total"], queries["blocked"]
            percent = float(queries["percent_blocked"])
            if (type(total) is not int or type(blocked) is not int or
                    total < 0 or blocked < 0 or blocked > total or
                    not math.isfinite(percent) or not 0 <= percent <= 100):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise APIError("Unexpected statistics; this display requires Pi-hole v6") from None
        return {"total": total, "blocked": blocked, "percent": percent,
                "state": state}

    def close(self):
        if self.sid:
            try:
                self._request("DELETE", "/auth")
            except APIError:
                pass
        self.sid = None
        self.session.close()


def load_config(path):
    config = json.loads(Path(path).read_text())
    if not isinstance(config.get("password", ""), str):
        raise ValueError("password must be a string")
    config.setdefault("password", "")
    config.setdefault("api_url", "http://127.0.0.1/api")
    config.setdefault("refresh_seconds", 180)
    config.setdefault("rotation", 0)
    config.setdefault("animation_seconds", 15)
    config.setdefault("full_refresh_every", 5)
    config.setdefault("web_preview_path", "")
    if type(config["refresh_seconds"]) is not int or config["refresh_seconds"] < 180:
        raise ValueError("refresh_seconds must be an integer of at least 180")
    if config["rotation"] not in (0, 180):
        raise ValueError("rotation must be 0 or 180")
    if type(config["animation_seconds"]) is not int or config["animation_seconds"] < 5:
        raise ValueError("animation_seconds must be an integer of at least 5")
    if type(config["full_refresh_every"]) is not int or not 1 <= config["full_refresh_every"] <= 10:
        raise ValueError("full_refresh_every must be an integer from 1 to 10")
    if not isinstance(config["web_preview_path"], str):
        raise ValueError("web_preview_path must be a string")
    return config


def font(size, bold=False, mono=False):
    name = "DejaVuSansMono" if mono else "DejaVuSans"
    name += "-Bold.ttf" if bold else ".ttf"
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/" + name, size)


def fit(draw, text, max_width, size=16, bold=False):
    for current in range(size, 6, -1):
        selected = font(current, bold)
        if draw.textlength(text, font=selected) <= max_width:
            return selected
    return font(7, bold)


def local_details():
    ip = "No LAN address"
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True,
                                text=True, check=True, timeout=2)
        for address in result.stdout.split():
            candidate = ipaddress.ip_address(address)
            if candidate.version == 4 and not candidate.is_loopback:
                ip = str(candidate)
                break
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        temperature = float(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
        temp = "%dC" % round(temperature)
    except (OSError, ValueError):
        temp = "--C"
    return ip, temp


def render(snapshot, ip="No LAN address", temperature="--C", updated=None, error=None, face_override=None, speech=None):
    """Render a layout with a dedicated, readable two-line Rick quote area."""
    image = Image.new("1", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    text_cfg = load_text_config()

    # Header: 20 px high.
    draw.rectangle((0, 0, 249, 19), fill=0)
    draw.text((6, 2), text_cfg["title"], font=font(13, True), fill=255)
    state = snapshot["state"] if snapshot else "error"
    label = text_cfg["status"].get(state, state.upper())
    label_font = fit(draw, label, 104, 10, True)
    draw.text((244 - draw.textlength(label, font=label_font), 4), label,
              font=label_font, fill=255)

    # Rick: native 75 x 75 artwork.
    face_file = face_override or {"enabled": "HAPPY.png", "disabled": "SLEEP.png"}.get(state, "BROKEN.png")
    image.paste(theme_face(face_file), (4, 24))
    draw.line((84, 23, 84, 101), fill=0)

    # Right-side stats block.
    if snapshot:
        draw.text((92, 24), "BLOCKED REQUESTS", font=font(9, True), fill=0)
        number = format(snapshot["blocked"], ",")
        draw.text((91, 35), number, font=fit(draw, number, 153, 24, True), fill=0)

        statline = "%.1f%% blocked   Q:%s" % (
            snapshot["percent"], format(snapshot["total"], ","))
        draw.text((92, 63), statline, font=fit(draw, statline, 153, 9, False), fill=0)
    else:
        draw.text((92, 26), "STATS UNAVAILABLE", font=font(10, True), fill=0)
        draw.text((92, 43), "Check Pi-hole/API", font=font(9), fill=0)
        draw.text((92, 58), "Retrying...", font=font(9), fill=0)

    # Dedicated quote area. This is deliberately separated from the stats so
    # speech can be larger without colliding with query numbers or the footer.
    draw.line((91, 76, 244, 76), fill=0)
    if speech:
        requested = int(text_cfg.get("quote_font_size", 10))
        chosen_font = font(requested, True)
        lines = wrap_pixels(draw, speech, chosen_font, 149, 2)

        # If the quote still truncates too aggressively at the requested size,
        # try one size smaller automatically.
        if lines and lines[-1].endswith("...") and requested > 8:
            smaller = font(requested - 1, True)
            smaller_lines = wrap_pixels(draw, speech, smaller, 149, 2)
            if not smaller_lines[-1].endswith("..."):
                chosen_font, lines = smaller, smaller_lines

        for row, speech_line in enumerate(lines):
            draw.text((93, 79 + row * 11), speech_line,
                      font=chosen_font, fill=0)
    else:
        draw.text((93, 84), "...", font=font(10, True), fill=0)

    # Footer: full width, kept visually separate from Rick's speech.
    draw.line((5, 104, 244, 104), fill=0)
    stamp = updated or datetime.now().strftime("%H:%M")
    footer = "%s  %s  %s" % (ip, temperature, stamp)
    draw.text((6, 107), footer, font=fit(draw, footer, 238, 9), fill=0)
    return image




def mood_face(snapshot):
    """Pick a Rickgotchi expression from Pi-hole's blocked-query percentage."""
    if not snapshot or snapshot.get("state") != "enabled":
        return None
    percent = float(snapshot["percent"])
    if percent < 5:
        return "BORED.png"
    if percent < 15:
        return "HAPPY.png"
    if percent < 25:
        return "SMART.png"
    if percent < 40:
        return "EXCITED.png"
    if percent < 50:
        return "INTENSE.png"
    return "ANGRY.png"


def make_display():
    # Imported only when touching hardware, so previews/API checks work on a PC.
    from waveshare_epd import epd2in13_V4, epdconfig

    class BoundedDisplay(epd2in13_V4.EPD):
        def ReadBusy(self):
            deadline = time.monotonic() + 15
            while epdconfig.digital_read(self.busy_pin) == 1:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Screen BUSY timeout: check V4 model, header and SPI")
                time.sleep(0.01)

    return BoundedDisplay(), epdconfig


def run(config):
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    api = PiHoleAPI(config["api_url"], config["password"])
    display, hardware = make_display()

    snapshot = None
    error = None
    ip, temperature = local_details()
    face_cycle = ["HAPPY.png", "LOOK_L.png", "HAPPY.png", "LOOK_R.png"]
    current_mood = "HAPPY.png"
    current_speech = ""
    face_index = 0
    partial_count = 0
    next_stats = 0.0
    next_animation = 0.0
    display_awake = False

    def prepared_frame(face_override=None):
        frame = render(snapshot, ip, temperature, error=error,
                       face_override=face_override, speech=current_speech)

        # Save the upright frame for the optional Pi-hole web dashboard card.
        # The physical panel may be rotated independently below.
        web_preview_path = config.get("web_preview_path", "").strip()
        if web_preview_path:
            try:
                frame.save(web_preview_path)
            except OSError as exc:
                LOG.warning("Could not update dashboard image: %s", exc)

        if config["rotation"]:
            frame = frame.rotate(180)
        return frame

    def full_base_refresh(face_override=None):
        nonlocal display_awake, partial_count
        if not display_awake:
            if display.init() != 0:
                raise RuntimeError("Display initialisation failed")
            display_awake = True
        frame = prepared_frame(face_override)
        display.displayPartBaseImage(display.getbuffer(frame))
        partial_count = 0

    try:
        for name in {"HAPPY.png", "LOOK_L.png", "LOOK_R.png", "BORED.png", "SMART.png", "EXCITED.png", "INTENSE.png", "ANGRY.png", "SLEEP.png", "BROKEN.png"}:
            if not (THEME_DIR / name).is_file():
                raise RuntimeError("Missing Rick face: %s" % name)

        while not stop.is_set():
            now = time.monotonic()

            # Re-read Pi-hole stats on the normal, conservative interval.
            if now >= next_stats:
                snapshot, error = None, None
                try:
                    snapshot = api.snapshot()
                except APIError as exc:
                    error = str(exc)
                    LOG.warning("%s", error)
                ip, temperature = local_details()

                if snapshot and snapshot["state"] == "enabled":
                    current_mood = mood_face(snapshot)
                    face_cycle = [current_mood, "LOOK_L.png", current_mood, "LOOK_R.png"]
                    face_index = 0
                    current_speech = random_rick_line(current_mood, "enabled")
                    full_base_refresh(face_cycle[face_index])
                    LOG.info("Rick mood: %s at %.1f%% blocked", current_mood, snapshot["percent"])
                    next_animation = time.monotonic() + config["animation_seconds"]
                else:
                    # Paused/error states stay static until the next stats poll.
                    state = snapshot["state"] if snapshot else "error"
                    static_face = "SLEEP.png" if state == "disabled" else "BROKEN.png"
                    current_speech = random_rick_line(static_face, state)
                    full_base_refresh(None)
                    next_animation = float("inf")

                LOG.info("Stats refreshed: %s", snapshot["state"] if snapshot else "API error")
                next_stats = time.monotonic() + config["refresh_seconds"]

            now = time.monotonic()
            if (snapshot and snapshot["state"] == "enabled" and
                    now >= next_animation):
                face_index = (face_index + 1) % len(face_cycle)
                # Change the speech together with the existing animation update,
                # so quotes do not cause additional e-ink refreshes.
                current_speech = random_rick_line(current_mood, "enabled")
                frame = prepared_frame(face_cycle[face_index])

                # Waveshare recommends periodically doing a normal/full refresh
                # after partial updates to clean up ghosting.
                if partial_count >= config["full_refresh_every"]:
                    full_base_refresh(face_cycle[face_index])
                    LOG.info("Rick full refresh: %s", face_cycle[face_index])
                else:
                    display.displayPartial(display.getbuffer(frame))
                    partial_count += 1
                    LOG.info("Rick partial frame %d/%d: %s",
                             partial_count, config["full_refresh_every"],
                             face_cycle[face_index])
                next_animation = time.monotonic() + config["animation_seconds"]

            deadline = min(next_stats, next_animation)
            wait_for = max(0.1, min(1.0, deadline - time.monotonic()))
            stop.wait(wait_for)
    finally:
        # Sleep/disable the panel when the service stops. Continuous animation
        # intentionally keeps the controller awake while the service is active.
        try:
            if display_awake:
                try:
                    display.sleep()
                except Exception:
                    pass
            hardware.module_exit(cleanup=True)
        finally:
            api.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Test API without touching screen")
    group.add_argument("--preview", metavar="PNG", help="Render clearly synthetic example data")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.preview:
        render({"state": "enabled", "blocked": 1234, "total": 8452, "percent": 14.6},
               "192.168.1.50", "42C", "21:30").save(args.preview)
        print("Saved sample screen with example data:", args.preview)
        return
    config = load_config(args.config)
    if args.check:
        api = PiHoleAPI(config["api_url"], config["password"])
        try:
            stats = api.snapshot()
            print("API OK: %s; %s blocked requests; %.1f%% blocked" %
                  (stats["state"], stats["blocked"], stats["percent"]))
        finally:
            api.close()
    else:
        run(config)


if __name__ == "__main__":
    try:
        main()
    except (APIError, ValueError, OSError, RuntimeError) as exc:
        LOG.error("%s", exc)
        raise SystemExit(1)
