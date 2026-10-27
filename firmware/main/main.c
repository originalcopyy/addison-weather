/*
 * Addison Weather for ZecTrix Note 4C (ESP32-S3 + 4.2" BWRY SSD2683 e-paper)
 *
 * Wake -> Wi-Fi -> download 30,000-byte 2bpp frame (rendered on demand by the
 * web function, with this board's battery percent in the query) -> refresh the
 * panel -> deep sleep. The DOWN button wakes the board for a fetch right now.
 *
 * Pins and SSD2683 sequence taken from the ZecTrix wiki and the reference
 * firmware (LazyYoun/youn-ink-fourcolor-firmware, 2bp branch).
 */
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_crc.h"
#include "esp_bit_defs.h"
#include "driver/rtc_io.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_heap_caps.h"
#include "esp_crt_bundle.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_sleep.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

static const char *TAG = "weather";

/* ---- Board pins (Note 4C) ---- */
#define PIN_EPD_PWR   GPIO_NUM_6
#define PIN_EPD_BUSY  GPIO_NUM_8   /* low = busy */
#define PIN_EPD_RST   GPIO_NUM_9
#define PIN_EPD_DC    GPIO_NUM_10
#define PIN_EPD_CS    GPIO_NUM_11
#define PIN_EPD_SCK   GPIO_NUM_12
#define PIN_EPD_MOSI  GPIO_NUM_13
#define PIN_PWR_HOLD  GPIO_NUM_17  /* keeps the board powered on battery */
#define PIN_LED       GPIO_NUM_3   /* active-low */
#define PIN_DOWN      GPIO_NUM_18  /* side button; also the hardware power key */
#define PIN_CHG_DET   GPIO_NUM_2   /* low while the battery is charging */
#define PIN_CHG_FULL  GPIO_NUM_1   /* high when charged and still on USB */
#define BATT_ADC_CH   ADC_CHANNEL_3 /* GPIO4, battery through a 1:2 divider */

#define EPD_W 400
#define EPD_H 300
#define ROW_BYTES (EPD_W / 4)            /* 2bpp -> 100 bytes per row */
#define FRAME_BYTES (ROW_BYTES * EPD_H)  /* 30,000 */

/* Survives deep sleep: skip the 10+ s refresh when nothing changed */
RTC_DATA_ATTR static uint32_t s_last_crc = 0;

static spi_device_handle_t s_spi;
static EventGroupHandle_t s_wifi_ev;
static bool s_skip_usb_wake;   /* set after a USB-plug wake that had no USB behind it */
#define WIFI_OK   BIT0
#define WIFI_FAIL BIT1

/* ======================= power ======================= */
static void hold_level(gpio_num_t pin, int level)
{
    gpio_hold_dis(pin);
    gpio_set_direction(pin, GPIO_MODE_OUTPUT);
    gpio_set_level(pin, level);
    gpio_hold_en(pin);
}

static bool usb_power_present(void)
{
    return gpio_get_level(PIN_CHG_DET) == 0 || gpio_get_level(PIN_CHG_FULL) == 1;
}

/* The LED is lit only while USB power is present (it is active-low). */
static void led_show_power(void)
{
    hold_level(PIN_LED, usb_power_present() ? 0 : 1);
}

/* Battery percent (0-100) from a 10-sample ADC average, or -1 if the ADC is
 * unavailable. Divider and curve are the ones the vendor firmware uses:
 * about 3.3 V reads 0 % and 4.2 V reads 100 %. */
static int read_battery_percent(int *millivolts)
{
    adc_oneshot_unit_handle_t adc = NULL;
    adc_cali_handle_t cali = NULL;
    adc_oneshot_unit_init_cfg_t unit = { .unit_id = ADC_UNIT_1 };
    adc_oneshot_chan_cfg_t chan = { .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12 };
    adc_cali_curve_fitting_config_t fit = {
        .unit_id = ADC_UNIT_1, .chan = BATT_ADC_CH, .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12,
    };
    int sum = 0, samples = 0;
    if (adc_oneshot_new_unit(&unit, &adc) == ESP_OK &&
        adc_oneshot_config_channel(adc, BATT_ADC_CH, &chan) == ESP_OK &&
        adc_cali_create_scheme_curve_fitting(&fit, &cali) == ESP_OK) {
        for (int i = 0; i < 10; i++) {
            int raw, mv;
            if (adc_oneshot_read(adc, BATT_ADC_CH, &raw) == ESP_OK &&
                adc_cali_raw_to_voltage(cali, raw, &mv) == ESP_OK) {
                sum += mv * 2;
                samples++;
            }
        }
    }
    if (cali) adc_cali_delete_scheme_curve_fitting(cali);
    if (adc) adc_oneshot_del_unit(adc);
    if (samples == 0) return -1;
    int avg = sum / samples;
    int pct = (-avg * avg + 9016 * avg - 19189000) / 10000;
    *millivolts = avg;
    return pct < 0 ? 0 : pct > 100 ? 100 : pct;
}

/* ======================= SSD2683 ======================= */
static void spi_tx(const uint8_t *buf, size_t len)
{
    spi_transaction_t t = { .length = len * 8, .tx_buffer = buf };
    ESP_ERROR_CHECK(spi_device_polling_transmit(s_spi, &t));
}

static void epd_cmd(uint8_t c)
{
    gpio_set_level(PIN_EPD_DC, 0);
    gpio_set_level(PIN_EPD_CS, 0);
    spi_tx(&c, 1);
    gpio_set_level(PIN_EPD_CS, 1);
}

static void epd_data(const uint8_t *d, size_t n)
{
    gpio_set_level(PIN_EPD_DC, 1);
    gpio_set_level(PIN_EPD_CS, 0);
    spi_tx(d, n);
    gpio_set_level(PIN_EPD_CS, 1);
}

static void epd_data1(uint8_t b) { epd_data(&b, 1); }

static void epd_wait(void)
{
    int64_t ms = 0;
    while (gpio_get_level(PIN_EPD_BUSY) == 0) {
        vTaskDelay(pdMS_TO_TICKS(10));
        if ((ms += 10) > 120000) { ESP_LOGW(TAG, "busy timeout"); return; }
    }
}

static void epd_bus_init(void)
{
    gpio_config_t out = {
        .pin_bit_mask = (1ULL << PIN_EPD_RST) | (1ULL << PIN_EPD_DC) | (1ULL << PIN_EPD_CS),
        .mode = GPIO_MODE_OUTPUT, .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&out);
    gpio_config_t in = { .pin_bit_mask = 1ULL << PIN_EPD_BUSY, .mode = GPIO_MODE_INPUT };
    gpio_config(&in);
    gpio_set_level(PIN_EPD_CS, 1);
    gpio_set_level(PIN_EPD_RST, 1);

    spi_bus_config_t bus = {
        .mosi_io_num = PIN_EPD_MOSI, .miso_io_num = -1, .sclk_io_num = PIN_EPD_SCK,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = 4096,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO));
    spi_device_interface_config_t dev = {
        .clock_speed_hz = 20 * 1000 * 1000, .mode = 0, .spics_io_num = -1, .queue_size = 1,
    };
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST, &dev, &s_spi));
}

static void epd_show(const uint8_t *frame)
{
    hold_level(PIN_EPD_PWR, 1);
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(PIN_EPD_RST, 1); vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(PIN_EPD_RST, 0); vTaskDelay(pdMS_TO_TICKS(20));
    gpio_set_level(PIN_EPD_RST, 1); vTaskDelay(pdMS_TO_TICKS(10));
    epd_wait();

    epd_cmd(0xE9); epd_data1(0x01);          /* 4-color init */

    epd_cmd(0x10);                            /* DTM1: raw 2bpp stream */
    epd_wait();
    for (int y = 0; y < EPD_H; y++) {
        epd_data(frame + y * ROW_BYTES, ROW_BYTES);
    }

    epd_cmd(0x04); epd_wait(); vTaskDelay(pdMS_TO_TICKS(10));   /* power on */
    epd_cmd(0x12); epd_data1(0x00);                              /* refresh  */
    vTaskDelay(pdMS_TO_TICKS(10)); epd_wait();
    epd_cmd(0x02); epd_data1(0x00); epd_wait();                  /* power off */
    vTaskDelay(pdMS_TO_TICKS(20));
    epd_cmd(0x07); epd_data1(0xA5);                              /* deep sleep */
    hold_level(PIN_EPD_PWR, 0);
}

/* ======================= Wi-Fi ======================= */
static void wifi_evt(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    static int retries = 0;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        if (++retries <= 5) esp_wifi_connect();
        else xEventGroupSetBits(s_wifi_ev, WIFI_FAIL);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_wifi_ev, WIFI_OK);
    }
}

static bool wifi_up(void)
{
    s_wifi_ev = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_evt, NULL);
    esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_evt, NULL);

    wifi_config_t wc = { 0 };
    strlcpy((char *)wc.sta.ssid, CONFIG_WEATHER_WIFI_SSID, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, CONFIG_WEATHER_WIFI_PASSWORD, sizeof(wc.sta.password));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());

    EventBits_t b = xEventGroupWaitBits(s_wifi_ev, WIFI_OK | WIFI_FAIL, pdFALSE, pdFALSE,
                                        pdMS_TO_TICKS(20000));
    return b & WIFI_OK;
}

/* ======================= download ======================= */
static bool fetch_frame(uint8_t *buf, int battery)
{
    /* The server draws the battery gauge, so the reading rides along in the query. */
    char url[256];
    if (battery >= 0) {
        snprintf(url, sizeof url, "%s%cbatt=%d", CONFIG_WEATHER_IMAGE_URL,
                 strchr(CONFIG_WEATHER_IMAGE_URL, '?') ? '&' : '?', battery);
    } else {
        strlcpy(url, CONFIG_WEATHER_IMAGE_URL, sizeof url);
    }
    esp_http_client_config_t c = {
        .url = url,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = 20000,   /* the frame is rendered on demand; allow for a cold start */
    };
    esp_http_client_handle_t h = esp_http_client_init(&c);
    bool ok = false;
    if (esp_http_client_open(h, 0) == ESP_OK) {
        esp_http_client_fetch_headers(h);
        int status = esp_http_client_get_status_code(h);
        int got = 0, n;
        while (got < FRAME_BYTES &&
               (n = esp_http_client_read(h, (char *)buf + got, FRAME_BYTES - got)) > 0) {
            got += n;
        }
        ok = (status == 200 && got == FRAME_BYTES);
        ESP_LOGI(TAG, "HTTP %d, %d bytes", status, got);
    }
    esp_http_client_cleanup(h);
    return ok;
}

/* ======================= main ======================= */
static void sleep_for(uint32_t minutes)
{
    esp_wifi_stop();
    hold_level(PIN_PWR_HOLD, 1);
    led_show_power();
    esp_sleep_enable_timer_wakeup((uint64_t)minutes * 60ULL * 1000000ULL);
    /* DOWN wakes for a forced refresh. BOOT (GPIO0) is a strapping pin and a
     * wake on it can land in download mode, so it is not used. Plugging in
     * USB wakes too, so the LED comes on promptly; that pin is armed only
     * while it is high, or it would retrigger at once while charging. */
    uint64_t wake_mask = BIT64(PIN_DOWN);
    rtc_gpio_pullup_en(PIN_DOWN);
    rtc_gpio_pulldown_dis(PIN_DOWN);
    if (!s_skip_usb_wake && gpio_get_level(PIN_CHG_DET) == 1) wake_mask |= BIT64(PIN_CHG_DET);
    esp_sleep_enable_ext1_wakeup_io(wake_mask, ESP_EXT1_WAKEUP_ANY_LOW);
    /* Without this the held pads (battery latch, LED, panel power) are
     * released on deep sleep and the board powers off on battery. */
    gpio_deep_sleep_hold_en();
    ESP_LOGI(TAG, "sleeping %lu min", (unsigned long)minutes);
    vTaskDelay(pdMS_TO_TICKS(50));   /* let the USB console drain */
    esp_deep_sleep_start();
}

void app_main(void)
{
    hold_level(PIN_PWR_HOLD, 1);   /* latch power first */
    gpio_config_t chg = { .pin_bit_mask = (1ULL << PIN_CHG_DET) | (1ULL << PIN_CHG_FULL),
                          .mode = GPIO_MODE_INPUT };
    gpio_config(&chg);
    led_show_power();

    uint64_t ext1 = (esp_sleep_get_wakeup_causes() & BIT(ESP_SLEEP_WAKEUP_EXT1))
                        ? esp_sleep_get_ext1_wakeup_status() : 0;
    bool forced = (ext1 & BIT64(PIN_DOWN)) != 0;   /* DOWN pressed: fetch now, refresh even if unchanged */
    bool plugged = (ext1 & BIT64(PIN_CHG_DET)) != 0;
    bool usb = usb_power_present();
    ESP_LOGI(TAG, "wake: %s, usb %s", forced ? "DOWN button" : plugged ? "USB plug" : "timer or power-on",
             usb ? "present" : "absent");
    if (plugged && !forced && !usb) {
        /* The charge-detect line dipped with no USB behind it. Do not spend a
         * Wi-Fi session and a 22 s refresh on noise, and leave that pin
         * un-armed for this sleep so a bouncing line cannot drain the battery. */
        ESP_LOGW(TAG, "spurious USB wake, back to sleep");
        s_skip_usb_wake = true;
        sleep_for(CONFIG_WEATHER_REFRESH_MINUTES);
    }

    esp_err_t e = nvs_flash_init();
    if (e == ESP_ERR_NVS_NO_FREE_PAGES || e == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    int mv = 0, battery = read_battery_percent(&mv);
    if (battery >= 0) ESP_LOGI(TAG, "battery %d%% (%d mV)", battery, mv);
    else ESP_LOGW(TAG, "battery reading unavailable");

    uint8_t *frame = heap_caps_malloc(FRAME_BYTES, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!frame || !wifi_up() || !fetch_frame(frame, battery)) {
        ESP_LOGW(TAG, "update failed, keeping current screen");
        sleep_for(CONFIG_WEATHER_RETRY_MINUTES);
    }

    uint32_t crc = esp_crc32_le(0, frame, FRAME_BYTES);
    if (crc != s_last_crc || forced) {
        epd_bus_init();
        epd_show(frame);
        s_last_crc = crc;
        ESP_LOGI(TAG, "screen updated");
    } else {
        ESP_LOGI(TAG, "unchanged, skipping refresh");
    }
    sleep_for(CONFIG_WEATHER_REFRESH_MINUTES);
}
