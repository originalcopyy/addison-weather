# Addison Weather — ZecTrix Note 4C

A four-color (black/white/red/yellow) weather board for Addison, IL, styled after the Note 4C product shot, with a battery gauge in the banner.

```
Note 4C                                        Vercel function (api/weather.py)
wake ──HTTPS GET /weather.bin?batt=82──►  renderer/render.py ── Open-Meteo ──► fresh 30,000-byte frame
     ◄───────────────────────────────────  (drawn at the moment of the request)
refresh panel → deep sleep
```

- **Renderer** (`renderer/`): Python + Pillow. Pulls Open-Meteo (no API key), draws a 400×300 frame using only the four panel colors, and packs it as the SSD2683's native 2bpp stream (30,000 bytes). `serve.py` wraps it as an HTTP response; `api/weather.py` is the Vercel entry point.
- **Firmware** (`firmware/`): ESP-IDF 6.0. Reads the battery, downloads the frame with `?batt=<percent>` so the server can draw the gauge, refreshes the panel, deep-sleeps for `WEATHER_REFRESH_MINUTES`.

## Using it

- Every wake fetches a frame rendered **at that moment**, so the clock in the banner is the time of the last update.
- Press **DOWN** (the side button) to fetch the latest weather now. Hold it to power the board on.
- Battery gauge: white fill at 50 % and up, yellow from 20 to 49 %, red with a red number under 20 % (time to charge).
- The front LED lights only while on USB power.

## 1. Host the renderer (Vercel, free)

```bash
npm i -g vercel
vercel login
vercel deploy --prod          # from this folder; creates the project on first run
```

Open `https://<project>.vercel.app/weather.png?batt=82` in a browser to see the frame the board would get. Each request renders fresh (`Cache-Control: no-store`).

Local test: `pip install -r renderer/requirements.txt && python renderer/render.py --battery 82` → `renderer/out/`. Tests: `python -m unittest renderer/test_render.py renderer/test_serve.py`.

Fallback: the GitHub Actions workflow still publishes a static frame to GitHub Pages when run by hand (Actions → *Render Addison weather* → *Run workflow*). Its hourly schedule was removed because GitHub skipped most of the runs, which left the board showing hours-old data.

## 2. Back up the factory firmware (do this once)

Enter download mode: hold BOOT, tap RESET (pinhole), release BOOT.

```bash
python3 -m esptool --chip esp32s3 --port /dev/cu.usbmodemXXXX read-flash 0 0x1000000 note4c-factory-backup.bin
```

Restore later with `write-flash 0x0 note4c-factory-backup.bin`.

## 3. Build and flash

```bash
cd firmware
idf.py set-target esp32s3
idf.py menuconfig        # Addison Weather → Wi-Fi SSID/password (2.4 GHz), image URL, refresh minutes
idf.py build
idf.py -p /dev/cu.usbmodemXXXX flash monitor
```

The board's USB port only exists while it is awake (about 30 s per update, or after a DOWN press), so start the flash and then press DOWN.

Expected log: `battery 82% (3990 mV)` → `HTTP 200, 30000 bytes` → `screen updated` → `sleeping 30 min`.

## Customizing

| What | Where |
|---|---|
| Location / label | `LAT`, `LON`, `PLACE` at the top of `render.py` |
| Update cadence | `WEATHER_REFRESH_MINUTES` in menuconfig |
| Banner rules (umbrella, snow, frost, heat) | `banner()` in `render.py` |
| Gauge thresholds | `battery_color()` in `render.py` |
| Colors | 2-bit codes: `00` black, `01` white, `10` yellow, `11` red, 4 px/byte, MSB = leftmost |

## Notes

- Pins and the SSD2683 command sequence come from the ZecTrix wiki and the reference firmware (`LazyYoun/youn-ink-fourcolor-firmware`, `2bp` branch).
- Battery percent uses the vendor divider (×2) and voltage curve; 3.3 V reads 0 %, 4.2 V reads 100 %.
- This replaces the stock Note 4C firmware. Do not flash the Note 4C image onto the monochrome Note 4.
- Fonts: Barlow Condensed (SIL Open Font License).
