# Addison Weather — ZecTrix Note 4C

A four-color (black/white/red/yellow) weather board for Addison, IL, styled after the Note 4C product shot.

```
GitHub Actions (hourly)                         Note 4C
renderer/render.py ── Open-Meteo ──► weather.bin ──HTTPS──► wake → download → refresh if changed → deep sleep
                                    weather.png (preview)
```

- **Renderer** (`renderer/`): Python + Pillow. Pulls Open-Meteo (no API key), draws a 400×300 frame using only the four panel colors, and packs it as the SSD2683's native 2bpp stream (30,000 bytes).
- **Firmware** (`firmware/`): ESP-IDF 6.0. Downloads the frame, skips the 10+ s refresh if the CRC is unchanged, deep-sleeps. Press **BOOT** to force a refresh.

## 1. Host the image (GitHub Pages, free)

1. Push this folder to a new GitHub repo named `addison-weather`.
2. Actions tab → **Render Addison weather** → *Run workflow*. This creates the `gh-pages` branch.
3. Settings → Pages → Source: *Deploy from branch* → `gh-pages` / root.
4. Check `https://<you>.github.io/addison-weather/weather.png` in a browser.

Local test: `pip install -r renderer/requirements.txt && python renderer/render.py` → `renderer/out/`.

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

Expected log: `HTTP 200, 30000 bytes` → `screen updated` → `sleeping 60 min`.

## Customizing

| What | Where |
|---|---|
| Location / label | `LAT`, `LON`, `PLACE` at the top of `render.py` |
| Update cadence | workflow `cron` + `WEATHER_REFRESH_MINUTES` in menuconfig |
| Banner rules (umbrella, snow, frost, heat) | `banner()` in `render.py` |
| Colors | 2-bit codes: `00` black, `01` white, `10` yellow, `11` red, 4 px/byte, MSB = leftmost |

## Notes

- Pins and the SSD2683 command sequence come from the ZecTrix wiki and the reference firmware (`LazyYoun/youn-ink-fourcolor-firmware`, `2bp` branch).
- This replaces the stock Note 4C firmware. Do not flash the Note 4C image onto the monochrome Note 4.
- Fonts: Barlow Condensed (SIL Open Font License).
