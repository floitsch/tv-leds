idf_component_register(SRCS "main.c" "protocol.c" INCLUDE_DIRS "."
    REQUIRES esp_driver_rmt esp_driver_usb_serial_jtag esp_timer app_update)
if(TV_LEDS_REPEAT_TEST)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE TV_LEDS_REPEAT_TEST=1)
endif()
