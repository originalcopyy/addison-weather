idf_component_register(SRCS "main.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_gpio esp_driver_spi esp_wifi esp_netif
                                     esp_event esp_http_client esp-tls mbedtls nvs_flash
                                     esp_hw_support esp_rom log)
