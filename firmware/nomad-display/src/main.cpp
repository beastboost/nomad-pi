#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h> // UDP Support
#include <ESPmDNS.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <lvgl.h>
#include <Preferences.h>
#include <HTTPClient.h>
#include "LGFX_Setup.h"

// --- DEFINITIONS ---
#define SCREEN_WIDTH 480
#define SCREEN_HEIGHT 320
#define POSTER_W 80
#define POSTER_H 120

// --- OBJECTS ---
LGFX tft;
WebSocketsClient webSocket;
Preferences preferences;
WiFiUDP udp; // UDP Object

// --- VARIABLES ---
static lv_disp_draw_buf_t draw_buf;
static lv_color_t buf[SCREEN_WIDTH * 10];

// Poster Buffer (approx 20KB for 80x120 RGB565)
// We use a sprite to handle JPG decoding
LGFX_Sprite sprite_poster(&tft);
static lv_img_dsc_t img_poster_dsc;
char current_poster_url[256] = "";

char wifi_ssid[64] = "";
char wifi_pass[64] = "";
String server_ip = "";
int server_port = 8000;
bool is_connected = false;
bool ws_configured = false;
unsigned long last_ws_begin_ms = 0;
char ws_host[64] = "";
int ws_port = 8000;
bool mdns_started = false;

char discovered_server_ip[64] = "";
int discovered_server_port = 8000;
char last_server_ip[64] = "";

bool wifi_connecting = false;
unsigned long wifi_connect_start_ms = 0;
unsigned long last_http_poll_ms = 0;
bool discovery_dirty = false;
unsigned long last_http_success_ms = 0;
bool theme_dark = true;
int brightness = 128;

volatile bool ws_payload_ready = false;
static char ws_payload_buf[20001];
static size_t ws_payload_len = 0;
unsigned long last_ws_process_ms = 0;
unsigned long last_poster_fetch_ms = 0;

// --- UI OBJECTS ---
lv_obj_t * tv;
lv_obj_t * tab_dash;
lv_obj_t * tab_now_playing;
lv_obj_t * tab_settings;

// Dashboard Widgets
lv_obj_t * label_status;
lv_obj_t * label_dash_server;
lv_obj_t * label_dash_uptime;
lv_obj_t * label_dash_users;
lv_obj_t * label_cpu;
lv_obj_t * label_ram;
lv_obj_t * label_stats;
lv_obj_t * arc_cpu;
lv_obj_t * arc_ram;

// Now Playing Widgets
lv_obj_t * cont_now_playing_list;
lv_obj_t * np_card;
lv_obj_t * np_img;
lv_obj_t * np_title;
lv_obj_t * np_sub;
lv_obj_t * np_meta;
lv_obj_t * np_bar;
lv_obj_t * np_btn_stop;
lv_obj_t * np_btn_pause;
lv_obj_t * np_empty_label;
char np_session_id[64] = "";
bool np_is_paused = false;

// Settings Widgets
lv_obj_t * label_wifi_status;
lv_obj_t * label_connection_info;
lv_obj_t * btn_scan_wifi;
lv_obj_t * btn_theme;
lv_obj_t * slider_brightness;
lv_obj_t * label_brightness;
lv_obj_t * list_wifi; 
lv_obj_t * win_wifi;  
lv_obj_t * kb;
lv_obj_t * ta_pass;

volatile bool ui_conn_dirty = false;
char ui_conn_line1[64] = "";
char ui_conn_line2[64] = "";
lv_color_t ui_status_color = lv_color_hex(0xEF4444);

// --- PROTOTYPES ---
void initDisplay();
void initLVGL();
void loadPreferences();
void savePreferences();
void buildUI();
void buildDashboardTab(lv_obj_t * parent);
void buildNowPlayingTab(lv_obj_t * parent);
void buildSettingsTab(lv_obj_t * parent);
void showWifiScanWindow();
void scanNetworks();
void connectToWifi(const char* ssid, const char* pass);
void handleWifiConnection();
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length);
void updateDashboardUI(JsonArray sessions, JsonObject system);
void stopSession(const char* session_id);
void pauseSession(const char* session_id);
void tryConnectWebSocket();
void checkUDP();
void downloadPoster(const char* url);
void processWsMessage();
void pollDashboardHttp();
bool isIpAddress(const String& s);
void applyConnectionUi();
void applyTheme();
void formatClock(char* out, size_t out_len, uint32_t seconds);

// --- SETUP ---
void setup() {
    Serial.begin(115200);
    
    // Init Display & LVGL
    initDisplay();
    initLVGL();

    // Init Poster Sprite
    sprite_poster.setColorDepth(16);
    sprite_poster.createSprite(POSTER_W, POSTER_H);
    sprite_poster.fillSprite(TFT_BLACK);

    // Init Poster DSC
    img_poster_dsc.header.always_zero = 0;
    img_poster_dsc.header.w = POSTER_W;
    img_poster_dsc.header.h = POSTER_H;
    img_poster_dsc.data_size = POSTER_W * POSTER_H * 2;
    img_poster_dsc.header.cf = LV_IMG_CF_TRUE_COLOR;
    img_poster_dsc.data = (const uint8_t*)sprite_poster.getBuffer();

    // Load WiFi Creds
    loadPreferences();

    // Build Main UI
    buildUI();

    // Connect if creds exist
    if (strlen(wifi_ssid) > 0) {
        connectToWifi(wifi_ssid, wifi_pass);
    } else {
        lv_tabview_set_act(tv, 2, LV_ANIM_ON); // Go to settings
    }
}

// --- LOOP ---
void loop() {
    if (ws_configured) webSocket.loop();

    processWsMessage();

    lv_timer_handler();
    applyConnectionUi();

    handleWifiConnection();
    
    if (WiFi.status() == WL_CONNECTED) {
        checkUDP();
    }

    if (WiFi.status() == WL_CONNECTED && !is_connected) {
        pollDashboardHttp();
    }

    if (WiFi.status() == WL_CONNECTED) {
        if (!is_connected && (millis() - last_http_success_ms < 30000)) {
            if (ws_configured) {
                webSocket.disconnect();
                ws_configured = false;
                ws_host[0] = '\0';
            }
        }

        if ((!ws_configured || discovery_dirty) && (millis() - last_ws_begin_ms > 15000)) {
            discovery_dirty = false;
            if (millis() - last_http_success_ms >= 30000) {
                tryConnectWebSocket();
            }
        }
    }
    
    delay(5);
}

// --- LVGL FLUSH ---
void my_disp_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p) {
    uint32_t w = (area->x2 - area->x1 + 1);
    uint32_t h = (area->y2 - area->y1 + 1);

    tft.startWrite();
    tft.setAddrWindow(area->x1, area->y1, w, h);
    tft.pushPixels((uint16_t *)&color_p->full, w * h, true);
    tft.endWrite();

    lv_disp_flush_ready(disp);
}

// --- TOUCH READ ---
void my_touchpad_read(lv_indev_drv_t * indev_driver, lv_indev_data_t * data) {
    uint16_t touchX, touchY;
    bool touched = tft.getTouch(&touchX, &touchY);

    if (touched) {
        data->state = LV_INDEV_STATE_PR;
        data->point.x = touchX;
        data->point.y = touchY;
    } else {
        data->state = LV_INDEV_STATE_REL;
    }
}

// --- INITIALIZATION ---
void initDisplay() {
    tft.init();
    tft.setRotation(1); // Landscape
    tft.setBrightness(brightness);
}

void initLVGL() {
    lv_init();
    lv_disp_draw_buf_init(&draw_buf, buf, NULL, SCREEN_WIDTH * 10);

    static lv_disp_drv_t disp_drv;
    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res = SCREEN_WIDTH;
    disp_drv.ver_res = SCREEN_HEIGHT;
    disp_drv.flush_cb = my_disp_flush;
    disp_drv.draw_buf = &draw_buf;
    lv_disp_drv_register(&disp_drv);

    static lv_indev_drv_t indev_drv;
    lv_indev_drv_init(&indev_drv);
    indev_drv.type = LV_INDEV_TYPE_POINTER;
    indev_drv.read_cb = my_touchpad_read;
    lv_indev_drv_register(&indev_drv);
}

void loadPreferences() {
    preferences.begin("nomad-display", true);
    String s = preferences.getString("ssid", "");
    String p = preferences.getString("pass", "");
    String lastIp = preferences.getString("last_server_ip", "");
    theme_dark = preferences.getBool("theme_dark", true);
    brightness = preferences.getInt("brightness", 128);
    preferences.end();
    
    strncpy(wifi_ssid, s.c_str(), 63);
    strncpy(wifi_pass, p.c_str(), 63);
    strncpy(last_server_ip, lastIp.c_str(), 63);
    last_server_ip[63] = '\0';

    if (strlen(last_server_ip) > 0) {
        strncpy(discovered_server_ip, last_server_ip, sizeof(discovered_server_ip) - 1);
        discovered_server_ip[sizeof(discovered_server_ip) - 1] = '\0';
    }
}

void savePreferences() {
    preferences.begin("nomad-display", false);
    preferences.putString("ssid", wifi_ssid);
    preferences.putString("pass", wifi_pass);
    preferences.putBool("theme_dark", theme_dark);
    preferences.putInt("brightness", brightness);
    preferences.end();
}

static void saveLastServerIp(const char* ip) {
    Preferences p;
    p.begin("nomad-display", false);
    p.putString("last_server_ip", ip);
    p.end();
}

bool isIpAddress(const String& s) {
    if (s.length() < 7) return false;
    for (size_t i = 0; i < s.length(); i++) {
        char c = s[i];
        if ((c >= '0' && c <= '9') || c == '.') continue;
        return false;
    }
    return true;
}

void formatClock(char* out, size_t out_len, uint32_t seconds) {
    if (!out || out_len == 0) return;
    uint32_t h = seconds / 3600;
    uint32_t m = (seconds % 3600) / 60;
    uint32_t s = seconds % 60;
    if (h > 0) {
        snprintf(out, out_len, "%lu:%02lu:%02lu", (unsigned long)h, (unsigned long)m, (unsigned long)s);
    } else {
        snprintf(out, out_len, "%lu:%02lu", (unsigned long)m, (unsigned long)s);
    }
}

void applyTheme() {
    lv_color_t bg = theme_dark ? lv_color_hex(0x0B1220) : lv_color_hex(0xF5F7FB);
    lv_color_t text = theme_dark ? lv_color_hex(0xE5E7EB) : lv_color_hex(0x0F172A);
    lv_color_t card = theme_dark ? lv_color_hex(0x334155) : lv_color_hex(0xFFFFFF);
    lv_color_t muted = theme_dark ? lv_color_hex(0x94A3B8) : lv_color_hex(0x475569);

    lv_obj_set_style_bg_color(lv_scr_act(), bg, 0);
    lv_obj_set_style_text_color(lv_scr_act(), text, 0);

    if (tv) {
        lv_obj_set_style_bg_color(tv, bg, 0);
        lv_obj_set_style_text_color(tv, text, 0);
    }

    if (np_card) lv_obj_set_style_bg_color(np_card, card, 0);
    if (np_title) lv_obj_set_style_text_color(np_title, text, 0);
    if (np_sub) lv_obj_set_style_text_color(np_sub, muted, 0);
    if (np_meta) lv_obj_set_style_text_color(np_meta, muted, 0);
    if (np_empty_label) lv_obj_set_style_text_color(np_empty_label, muted, 0);
    if (label_cpu) lv_obj_set_style_text_color(label_cpu, text, 0);
    if (label_ram) lv_obj_set_style_text_color(label_ram, text, 0);
    if (label_stats) lv_obj_set_style_text_color(label_stats, muted, 0);
    if (label_wifi_status) lv_obj_set_style_text_color(label_wifi_status, text, 0);
    if (label_connection_info) lv_obj_set_style_text_color(label_connection_info, muted, 0);
    if (label_dash_server) lv_obj_set_style_text_color(label_dash_server, muted, 0);
    if (label_dash_uptime) lv_obj_set_style_text_color(label_dash_uptime, muted, 0);
    if (label_dash_users) lv_obj_set_style_text_color(label_dash_users, muted, 0);
    if (label_brightness) lv_obj_set_style_text_color(label_brightness, text, 0);

    if (btn_scan_wifi) lv_obj_set_style_bg_color(btn_scan_wifi, theme_dark ? lv_color_hex(0x1F2937) : lv_color_hex(0xE2E8F0), 0);
    if (btn_theme) lv_obj_set_style_bg_color(btn_theme, theme_dark ? lv_color_hex(0x1F2937) : lv_color_hex(0xE2E8F0), 0);
    if (btn_scan_wifi) lv_obj_set_style_text_color(btn_scan_wifi, text, 0);
    if (btn_theme) lv_obj_set_style_text_color(btn_theme, text, 0);
    if (slider_brightness) lv_obj_set_style_bg_color(slider_brightness, theme_dark ? lv_color_hex(0x1F2937) : lv_color_hex(0xE2E8F0), 0);
}

// --- UI BUILDERS ---
void buildUI() {
    tv = lv_tabview_create(lv_scr_act(), LV_DIR_TOP, 40);
    
    tab_dash = lv_tabview_add_tab(tv, "Home");
    tab_settings = lv_tabview_add_tab(tv, "Settings");

    buildDashboardTab(tab_dash);
    buildSettingsTab(tab_settings);

    applyTheme();
}

void buildDashboardTab(lv_obj_t * parent) {
    lv_obj_set_flex_flow(parent, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(parent, 0, 0);
    
    // --- IDLE PANEL ---
    panel_idle = lv_obj_create(parent);
    lv_obj_set_size(panel_idle, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_opa(panel_idle, 0, 0);
    lv_obj_set_style_border_width(panel_idle, 0, 0);
    lv_obj_set_flex_flow(panel_idle, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(panel_idle, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    
    label_clock_huge = lv_label_create(panel_idle);
    lv_obj_set_style_text_font(label_clock_huge, &lv_font_montserrat_48, 0);
    lv_label_set_text(label_clock_huge, "00:00");
    
    label_date = lv_label_create(panel_idle);
    lv_obj_set_style_text_font(label_date, &lv_font_montserrat_18, 0);
    lv_label_set_text(label_date, "Nomad Media Server");
    lv_obj_set_style_pad_bottom(label_date, 20, 0);

    label_status_pill = lv_label_create(panel_idle);
    lv_obj_set_style_bg_color(label_status_pill, lv_color_hex(0x1F2937), 0);
    lv_obj_set_style_bg_opa(label_status_pill, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(label_status_pill, 10, 0);
    lv_obj_set_style_radius(label_status_pill, 20, 0);
    lv_label_set_text(label_status_pill, "Ready to Cast");

    // --- PLAYING PANEL ---
    panel_playing = lv_obj_create(parent);
    lv_obj_set_size(panel_playing, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_color(panel_playing, lv_color_hex(0x334155), 0);
    lv_obj_set_style_radius(panel_playing, 0, 0);
    lv_obj_set_style_border_width(panel_playing, 0, 0);
    lv_obj_set_style_pad_all(panel_playing, 15, 0);
    lv_obj_add_flag(panel_playing, LV_OBJ_FLAG_HIDDEN); // Hidden by default

    // Poster (Left)
    np_img = lv_img_create(panel_playing);
    lv_img_set_src(np_img, &img_poster_dsc);
    lv_obj_set_size(np_img, POSTER_W, POSTER_H);
    lv_obj_align(np_img, LV_ALIGN_LEFT_MID, 0, -10);

    // Info (Right)
    lv_obj_t * info = lv_obj_create(panel_playing);
    lv_obj_set_style_bg_opa(info, 0, 0);
    lv_obj_set_style_border_width(info, 0, 0);
    lv_obj_set_flex_flow(info, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(info, 5, 0);
    lv_obj_set_size(info, SCREEN_WIDTH - POSTER_W - 40, 200);
    lv_obj_align(info, LV_ALIGN_LEFT_MID, POSTER_W + 15, -10);

    np_title = lv_label_create(info);
    lv_obj_set_width(np_title, LV_PCT(100));
    lv_label_set_long_mode(np_title, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_style_text_font(np_title, &lv_font_montserrat_24, 0); // Bigger font
    lv_label_set_text(np_title, "Nothing Playing");

    np_sub = lv_label_create(info);
    lv_obj_set_width(np_sub, LV_PCT(100));
    lv_obj_set_style_text_color(np_sub, lv_color_hex(0x94A3B8), 0);
    lv_label_set_text(np_sub, "--");
    
    np_meta = lv_label_create(info);
    lv_obj_set_width(np_meta, LV_PCT(100));
    lv_label_set_text(np_meta, "00:00 / 00:00");

    np_bar = lv_bar_create(info);
    lv_obj_set_width(np_bar, LV_PCT(100));
    lv_obj_set_height(np_bar, 8);
    lv_bar_set_range(np_bar, 0, 100);
    lv_bar_set_value(np_bar, 0, LV_ANIM_OFF);
    lv_obj_set_style_bg_color(np_bar, lv_color_hex(0x475569), 0);
    lv_obj_set_style_bg_color(np_bar, lv_color_hex(0x3B82F6), LV_PART_INDICATOR);

    // Controls
    lv_obj_t * ctrls = lv_obj_create(info);
    lv_obj_set_style_bg_opa(ctrls, 0, 0);
    lv_obj_set_style_border_width(ctrls, 0, 0);
    lv_obj_set_style_pad_all(ctrls, 0, 0);
    lv_obj_set_flex_flow(ctrls, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(ctrls, 15, 0);
    lv_obj_set_size(ctrls, LV_PCT(100), 50);
    lv_obj_set_style_pad_top(ctrls, 10, 0);

    np_btn_pause = lv_btn_create(ctrls);
    lv_obj_set_size(np_btn_pause, 100, 40);
    lv_obj_set_style_bg_color(np_btn_pause, lv_color_hex(0xF59E0B), 0);
    lv_obj_t * lbl_pause = lv_label_create(np_btn_pause);
    lv_label_set_text(lbl_pause, "PAUSE");
    lv_obj_center(lbl_pause);

    np_btn_stop = lv_btn_create(ctrls);
    lv_obj_set_size(np_btn_stop, 100, 40);
    lv_obj_set_style_bg_color(np_btn_stop, lv_color_hex(0xEF4444), 0);
    lv_obj_t * lbl_stop = lv_label_create(np_btn_stop);
    lv_label_set_text(lbl_stop, "STOP");
    lv_obj_center(lbl_stop);

    lv_obj_add_event_cb(np_btn_stop, [](lv_event_t* e){
        if (strlen(np_session_id) > 0) stopSession(np_session_id);
    }, LV_EVENT_CLICKED, NULL);

    lv_obj_add_event_cb(np_btn_pause, [](lv_event_t* e){
        if (strlen(np_session_id) > 0) pauseSession(np_session_id);
    }, LV_EVENT_CLICKED, NULL);
}

void buildNowPlayingTab(lv_obj_t * parent) {
    // Deprecated - merged into Dashboard
}

void buildSettingsTab(lv_obj_t * parent) {
    lv_obj_set_flex_flow(parent, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(parent, 10, 0);
    lv_obj_set_style_pad_row(parent, 10, 0);
    
    // Status Labels
    label_wifi_status = lv_label_create(parent);
    lv_label_set_text(label_wifi_status, "Wi-Fi: Not Connected");
    lv_obj_set_style_text_font(label_wifi_status, &lv_font_montserrat_14, 0);
    
    label_connection_info = lv_label_create(parent);
    lv_label_set_text(label_connection_info, "Server: Auto-discovery");
    lv_obj_set_style_text_font(label_connection_info, &lv_font_montserrat_14, 0);
    
    lv_obj_t * bright_wrap = lv_obj_create(parent);
    lv_obj_set_width(bright_wrap, LV_PCT(100));
    lv_obj_set_style_bg_opa(bright_wrap, 0, 0);
    lv_obj_set_style_border_width(bright_wrap, 0, 0);
    lv_obj_set_style_pad_all(bright_wrap, 0, 0);
    lv_obj_set_flex_flow(bright_wrap, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(bright_wrap, 6, 0);

    label_brightness = lv_label_create(bright_wrap);
    lv_obj_set_width(label_brightness, LV_PCT(100));
    lv_label_set_text_fmt(label_brightness, "Brightness: %d", brightness);

    slider_brightness = lv_slider_create(bright_wrap);
    lv_obj_set_width(slider_brightness, LV_PCT(100));
    lv_slider_set_range(slider_brightness, 8, 255);
    lv_slider_set_value(slider_brightness, brightness, LV_ANIM_OFF);
    lv_obj_add_event_cb(slider_brightness, [](lv_event_t* e){
        lv_obj_t * sld = lv_event_get_target(e);
        brightness = (int)lv_slider_get_value(sld);
        tft.setBrightness(brightness);
        savePreferences();
        if (label_brightness) lv_label_set_text_fmt(label_brightness, "Brightness: %d", brightness);
    }, LV_EVENT_VALUE_CHANGED, NULL);

    // Scan Button
    btn_scan_wifi = lv_btn_create(parent);
    lv_obj_set_width(btn_scan_wifi, LV_PCT(100));
    lv_obj_t * lbl_scan = lv_label_create(btn_scan_wifi);
    lv_label_set_text(lbl_scan, "Scan & Connect Wi-Fi");
    lv_obj_add_event_cb(btn_scan_wifi, [](lv_event_t* e){ showWifiScanWindow(); }, LV_EVENT_CLICKED, NULL);

    btn_theme = lv_btn_create(parent);
    lv_obj_set_width(btn_theme, LV_PCT(100));
    lv_obj_t * lbl_theme = lv_label_create(btn_theme);
    lv_label_set_text(lbl_theme, theme_dark ? "Theme: Dark" : "Theme: Light");
    lv_obj_center(lbl_theme);
    lv_obj_add_event_cb(btn_theme, [](lv_event_t* e){
        theme_dark = !theme_dark;
        savePreferences();
        applyTheme();
        lv_obj_t * btn = lv_event_get_target(e);
        lv_obj_t * lbl = lv_obj_get_child(btn, 0);
        if (lbl) lv_label_set_text(lbl, theme_dark ? "Theme: Dark" : "Theme: Light");
    }, LV_EVENT_CLICKED, NULL);
}

void showWifiScanWindow() {
    if (win_wifi) return;

    win_wifi = lv_win_create(lv_scr_act(), 40);
    lv_win_add_title(win_wifi, "Wi-Fi Networks");
    lv_obj_t * btn_close = lv_win_add_btn(win_wifi, LV_SYMBOL_CLOSE, 40);
    lv_obj_add_event_cb(btn_close, [](lv_event_t* e){
        lv_obj_del(win_wifi);
        win_wifi = NULL;
    }, LV_EVENT_CLICKED, NULL);

    lv_obj_t * cont = lv_win_get_content(win_wifi);
    
    list_wifi = lv_list_create(cont);
    lv_obj_set_size(list_wifi, LV_PCT(100), 180);

    ta_pass = lv_textarea_create(cont);
    lv_textarea_set_password_mode(ta_pass, true);
    lv_textarea_set_one_line(ta_pass, true);
    lv_textarea_set_placeholder_text(ta_pass, "Password...");
    lv_obj_set_width(ta_pass, LV_PCT(100));
    lv_obj_add_flag(ta_pass, LV_OBJ_FLAG_HIDDEN);

    kb = lv_keyboard_create(win_wifi);
    lv_obj_add_flag(kb, LV_OBJ_FLAG_HIDDEN);
    
    lv_obj_add_event_cb(kb, [](lv_event_t* e){
        const char * pass = lv_textarea_get_text(ta_pass);
        strcpy(wifi_pass, pass);
        savePreferences();
        
        lv_obj_add_flag(kb, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(ta_pass, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(list_wifi, LV_OBJ_FLAG_HIDDEN);
        
        lv_obj_clean(list_wifi);
        lv_list_add_btn(list_wifi, LV_SYMBOL_SETTINGS, "Connecting...");
        
        connectToWifi(wifi_ssid, wifi_pass);
    }, LV_EVENT_READY, NULL);

    lv_obj_add_event_cb(kb, [](lv_event_t* e){
        lv_obj_add_flag(kb, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(ta_pass, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(list_wifi, LV_OBJ_FLAG_HIDDEN);
    }, LV_EVENT_CANCEL, NULL);

    scanNetworks();
}

void scanNetworks() {
    if (!list_wifi) return;
    
    lv_obj_clean(list_wifi);
    lv_list_add_btn(list_wifi, LV_SYMBOL_REFRESH, "Scanning...");
    lv_timer_handler(); 

    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    int n = WiFi.scanNetworks();

    lv_obj_clean(list_wifi);
    if (n == 0) {
        lv_list_add_btn(list_wifi, NULL, "No networks found");
    } else {
        for (int i = 0; i < n; ++i) {
            char ssid_buff[33];
            strncpy(ssid_buff, WiFi.SSID(i).c_str(), 32);
            ssid_buff[32] = '\0';
            
            lv_obj_t * btn = lv_list_add_btn(list_wifi, LV_SYMBOL_WIFI, ssid_buff);
            lv_obj_add_event_cb(btn, [](lv_event_t* e){
                lv_obj_t * btn = lv_event_get_target(e);
                const char * ssid = lv_list_get_btn_text(list_wifi, btn);
                strcpy(wifi_ssid, ssid);
                
                lv_obj_add_flag(list_wifi, LV_OBJ_FLAG_HIDDEN);
                lv_obj_clear_flag(ta_pass, LV_OBJ_FLAG_HIDDEN);
                lv_obj_clear_flag(kb, LV_OBJ_FLAG_HIDDEN);
                lv_keyboard_set_textarea(kb, ta_pass);
            }, LV_EVENT_CLICKED, NULL);
        }
    }
}

void connectToWifi(const char* ssid, const char* pass) {
    lv_label_set_text(label_wifi_status, "Connecting...");
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, pass);
    wifi_connecting = true;
    wifi_connect_start_ms = millis();
}

void handleWifiConnection() {
    if (!wifi_connecting) return;

    wl_status_t st = WiFi.status();
    if (st == WL_CONNECTED) {
        wifi_connecting = false;
        WiFi.setSleep(false);
        String ip = WiFi.localIP().toString();
        Serial.print("WiFi connected. IP=");
        Serial.println(ip);
        lv_label_set_text_fmt(label_wifi_status, "Connected: %s\nIP: %s", wifi_ssid, ip.c_str());
        udp.begin(8001);
        if (win_wifi) {
            lv_obj_del(win_wifi);
            win_wifi = NULL;
        }
        tryConnectWebSocket();
        return;
    }

    if (millis() - wifi_connect_start_ms > 15000) {
        wifi_connecting = false;
        lv_label_set_text(label_wifi_status, "Connection Failed");
        if (win_wifi) {
            lv_obj_clean(list_wifi);
            lv_list_add_btn(list_wifi, LV_SYMBOL_WARNING, "Failed. Try again.");
            lv_obj_clear_flag(list_wifi, LV_OBJ_FLAG_HIDDEN);
        }
    }
}

void tryConnectWebSocket() {
    if (WiFi.status() != WL_CONNECTED) return;

    if (discovery_dirty) discovery_dirty = false;
    
    // Determine Server IP
    if (strcmp(wifi_ssid, "NomadPi") == 0) {
        server_ip = "10.42.0.1";
    } else if (strlen(discovered_server_ip) > 0) {
        server_ip = String(discovered_server_ip);
        server_port = discovered_server_port;
    } else {
        if (!mdns_started) {
            mdns_started = MDNS.begin("nomad-display");
        }

        if (mdns_started) {
            IPAddress hostIp = MDNS.queryHost("nomadpi");
            String resolved = hostIp.toString();
            if (resolved != "0.0.0.0") {
                strncpy(discovered_server_ip, resolved.c_str(), sizeof(discovered_server_ip) - 1);
                discovered_server_ip[sizeof(discovered_server_ip) - 1] = '\0';
                discovered_server_port = server_port;
                strncpy(last_server_ip, discovered_server_ip, sizeof(last_server_ip) - 1);
                last_server_ip[sizeof(last_server_ip) - 1] = '\0';
                saveLastServerIp(discovered_server_ip);
                server_ip = resolved;
            } else {
                server_ip = "";
            }
        } else {
            server_ip = "";
        }
    }
    
    if (server_ip.length() == 0) {
        strncpy(ui_conn_line1, "Server: Waiting discovery", sizeof(ui_conn_line1) - 1);
        ui_conn_line1[sizeof(ui_conn_line1) - 1] = '\0';
        ui_conn_line2[0] = '\0';
        ui_conn_dirty = true;
        return;
    }

    Serial.print("Attempt WS to ");
    Serial.print(server_ip);
    Serial.print(":");
    Serial.println(server_port);

    if (server_ip.length() < sizeof(ws_host)) {
        if (strcmp(ws_host, server_ip.c_str()) == 0 && ws_port == server_port && ws_configured) {
            return;
        }
        strncpy(ws_host, server_ip.c_str(), sizeof(ws_host) - 1);
        ws_host[sizeof(ws_host) - 1] = '\0';
        ws_port = server_port;
    } else {
        return;
    }

    strncpy(ui_conn_line1, "Connecting...", sizeof(ui_conn_line1) - 1);
    ui_conn_line1[sizeof(ui_conn_line1) - 1] = '\0';
    snprintf(ui_conn_line2, sizeof(ui_conn_line2), "%s:%d", ws_host, ws_port);
    ui_conn_dirty = true;

    last_ws_begin_ms = millis();
    if (ws_configured) {
        webSocket.disconnect();
        delay(10);
    }
    webSocket.begin(ws_host, ws_port, "/api/dashboard/ws");
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(15000);
    ws_configured = true;
}

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
    switch(type) {
        case WStype_CONNECTED:
            Serial.println("WS: connected");
            strncpy(ui_conn_line1, "Nomad Pi: Online", sizeof(ui_conn_line1) - 1);
            ui_conn_line1[sizeof(ui_conn_line1) - 1] = '\0';
            snprintf(ui_conn_line2, sizeof(ui_conn_line2), "%s:%d", ws_host, ws_port);
            ui_status_color = lv_color_hex(0x10B981);
            ui_conn_dirty = true;
            is_connected = true;
            break;
        case WStype_DISCONNECTED:
            Serial.println("WS: disconnected");
            if (millis() - last_http_success_ms > 20000) {
                strncpy(ui_conn_line1, "Nomad Pi: Disconnected", sizeof(ui_conn_line1) - 1);
                ui_conn_line1[sizeof(ui_conn_line1) - 1] = '\0';
                strncpy(ui_conn_line2, "Retrying...", sizeof(ui_conn_line2) - 1);
                ui_conn_line2[sizeof(ui_conn_line2) - 1] = '\0';
                ui_status_color = lv_color_hex(0xEF4444);
                ui_conn_dirty = true;
            }
            is_connected = false;
            break;
        case WStype_ERROR:
            Serial.println("WS: error");
            strncpy(ui_conn_line1, "Nomad Pi: WS Error", sizeof(ui_conn_line1) - 1);
            ui_conn_line1[sizeof(ui_conn_line1) - 1] = '\0';
            strncpy(ui_conn_line2, "Retrying...", sizeof(ui_conn_line2) - 1);
            ui_conn_line2[sizeof(ui_conn_line2) - 1] = '\0';
            ui_status_color = lv_color_hex(0xEF4444);
            ui_conn_dirty = true;
            is_connected = false;
            break;
        case WStype_TEXT: {
            if (length == 0 || length > 20000) break;
            memcpy(ws_payload_buf, payload, length);
            ws_payload_buf[length] = '\0';
            ws_payload_len = length;
            ws_payload_ready = true;
            break;
        }
    }
}

void applyConnectionUi() {
    if (!ui_conn_dirty) return;
    ui_conn_dirty = false;

    if (label_status) {
        lv_label_set_text(label_status, ui_conn_line1);
        lv_obj_set_style_text_color(label_status, ui_status_color, 0);
    }

    if (label_dash_server) {
        if (ui_conn_line2[0] != '\0') {
            lv_label_set_text(label_dash_server, ui_conn_line2);
        } else {
            lv_label_set_text(label_dash_server, "Server: --");
        }
    }

    if (label_connection_info) {
        if (ui_conn_line2[0] != '\0') {
            lv_label_set_text_fmt(label_connection_info, "%s\n%s", ui_conn_line1, ui_conn_line2);
        } else {
            lv_label_set_text(label_connection_info, ui_conn_line1);
        }
    }
}

void processWsMessage() {
    if (!ws_payload_ready) return;
    if (millis() - last_ws_process_ms < 250) return;

    ws_payload_ready = false;
    last_ws_process_ms = millis();

    DynamicJsonDocument doc(8192);
    DeserializationError error = deserializeJson(doc, ws_payload_buf, ws_payload_len);

    if (error) return;
    updateDashboardUI(doc["sessions"], doc["system"]);
}

void pollDashboardHttp() {
    if (millis() - last_http_poll_ms < 5000) return;
    last_http_poll_ms = millis();

    if (server_ip.length() == 0) return;
    if (!isIpAddress(server_ip) && server_ip != "10.42.0.1") return;

    HTTPClient http;
    String url = "http://" + server_ip + ":" + String(server_port) + "/api/dashboard/public";
    http.begin(url);
    http.setConnectTimeout(800);
    http.setTimeout(800);
    int code = http.GET();

    if (code == 200) {
        DynamicJsonDocument doc(12288);
        WiFiClient* stream = http.getStreamPtr();
        DeserializationError error = deserializeJson(doc, *stream);
        http.end();
        if (!error) {
            last_http_success_ms = millis();
            strncpy(ui_conn_line1, "Nomad Pi: Online", sizeof(ui_conn_line1) - 1);
            ui_conn_line1[sizeof(ui_conn_line1) - 1] = '\0';
            snprintf(ui_conn_line2, sizeof(ui_conn_line2), "HTTP %s:%d", server_ip.c_str(), server_port);
            ui_status_color = lv_color_hex(0x10B981);
            ui_conn_dirty = true;
            updateDashboardUI(doc["sessions"], doc["system"]);
        }
        return;
    }

    if (millis() - last_http_success_ms > 20000) {
        strncpy(ui_conn_line1, "Nomad Pi: Disconnected", sizeof(ui_conn_line1) - 1);
        ui_conn_line1[sizeof(ui_conn_line1) - 1] = '\0';
        snprintf(ui_conn_line2, sizeof(ui_conn_line2), "HTTP err %d", code);
        ui_status_color = lv_color_hex(0xEF4444);
        ui_conn_dirty = true;
    }
    http.end();
}

void updateDashboardUI(JsonArray sessions, JsonObject system) {
    // 1. Determine State (Playing vs Idle)
    bool is_playing = sessions.size() > 0;
    
    // 2. Update Toggle Visibility
    if (is_playing) {
        if (lv_obj_has_flag(panel_playing, LV_OBJ_FLAG_HIDDEN)) {
             lv_obj_clear_flag(panel_playing, LV_OBJ_FLAG_HIDDEN);
             lv_obj_add_flag(panel_idle, LV_OBJ_FLAG_HIDDEN);
        }
    } else {
        if (lv_obj_has_flag(panel_idle, LV_OBJ_FLAG_HIDDEN)) {
             lv_obj_clear_flag(panel_idle, LV_OBJ_FLAG_HIDDEN);
             lv_obj_add_flag(panel_playing, LV_OBJ_FLAG_HIDDEN);
        }
    }

    // 3. Update Idle Panel
    if (!is_playing) {
        // Update Clock from Server Timestamp (local time approximation)
        // We receive unix timestamp.
        long long ts = system.containsKey("timestamp") ? system["timestamp"].as<long long>() : 0;
        if (ts == 0 && sessions.size() == 0) {
             // Fallback if system object is from stats only
             // But updateDashboardUI is called with doc["sessions"] and doc["system"]
             // doc["timestamp"] is at root usually?
             // Actually in dashboard.py: { "sessions": ..., "system": ..., "timestamp": ... }
             // We are passing doc["system"] which is inside.
             // We need to pass the root timestamp if we want it.
             // But we can just use uptime for now or "--:--"
             lv_label_set_text(label_clock_huge, "Nomad");
        } else {
             // We don't have the timestamp passed in updateDashboardUI signature easily
             // unless we change the signature.
             // Let's just show "Nomad" or uptime.
             lv_label_set_text(label_clock_huge, "Nomad");
        }
        
        // Show server status
        if (is_connected) {
             lv_label_set_text(label_status_pill, "Ready to Cast");
             lv_obj_set_style_text_color(label_status_pill, lv_color_hex(0x10B981), 0); // Green
        } else {
             lv_label_set_text(label_status_pill, "Connecting...");
             lv_obj_set_style_text_color(label_status_pill, lv_color_hex(0xF59E0B), 0); // Orange
        }
        return;
    }

    // 4. Update Playing Panel
    JsonObject session = sessions[0];
    const char* title = session["title"];
    const char* state = session["state"];
    const char* user = session["username"];
    const char* poster = session["poster_thumb"]; // Use thumb for speed
    const char* sid = session["session_id"];
    
    double current = session["current_time"];
    double duration = session["duration"];
    
    strncpy(np_session_id, sid, sizeof(np_session_id)-1);
    
    lv_label_set_text(np_title, title ? title : "Unknown");
    lv_label_set_text_fmt(np_sub, "User: %s", user ? user : "Unknown");
    
    char cur_fmt[16];
    char dur_fmt[16];
    formatClock(cur_fmt, sizeof(cur_fmt), (uint32_t)current);
    formatClock(dur_fmt, sizeof(dur_fmt), (uint32_t)duration);
    lv_label_set_text_fmt(np_meta, "%s / %s", cur_fmt, dur_fmt);
    
    if (duration > 0) {
        int pct = (int)((current / duration) * 100.0);
        if (pct > 100) pct = 100;
        lv_bar_set_value(np_bar, pct, LV_ANIM_ON);
    }

    // Handle Poster
    if (poster) {
        char full_url[256];
        if (strncmp(poster, "http", 4) == 0) {
            strncpy(full_url, poster, sizeof(full_url)-1);
        } else {
            snprintf(full_url, sizeof(full_url), "http://%s:%d%s", server_ip.c_str(), server_port, poster);
        }
        
        if (strcmp(full_url, current_poster_url) != 0) {
             // New poster
             strncpy(current_poster_url, full_url, sizeof(current_poster_url)-1);
             downloadPoster(full_url);
        }
    }
}

void downloadPoster(const char* url) {
    if (WiFi.status() != WL_CONNECTED) return;
    
    HTTPClient http;
    http.begin(url);
    http.setConnectTimeout(1500);
    http.setTimeout(1500);
    int httpCode = http.GET();
    
    if (httpCode == 200) {
        // Allocate buffer for JPG
        int len = http.getSize();
        if (len > 0 && len < 500000) {
            uint8_t* jpg_buf = (uint8_t*)malloc(len);
            if (jpg_buf) {
                WiFiClient * stream = http.getStreamPtr();
                int readBytes = stream->readBytes(jpg_buf, len);
                
                // Draw to sprite
                sprite_poster.drawJpg(jpg_buf, readBytes, 0, 0, POSTER_W, POSTER_H);
                
                free(jpg_buf);
            }
        }
    }
    http.end();
}

void checkUDP() {
    int packetSize = udp.parsePacket();
    if (packetSize) {
        char packetBuffer[255];
        int len = udp.read(packetBuffer, 255);
        if (len > 0) packetBuffer[len] = 0;
        
        StaticJsonDocument<512> doc;
        DeserializationError error = deserializeJson(doc, packetBuffer);
        
        if (!error && doc["type"] == "discovery") {
            int port = doc["port"];
            String ip = udp.remoteIP().toString();
            
            if (ip != "0.0.0.0") {
                bool changed = (strncmp(discovered_server_ip, ip.c_str(), sizeof(discovered_server_ip) - 1) != 0) || (discovered_server_port != port);
                strncpy(discovered_server_ip, ip.c_str(), sizeof(discovered_server_ip) - 1);
                discovered_server_ip[sizeof(discovered_server_ip) - 1] = '\0';
                discovered_server_port = port;
                strncpy(last_server_ip, discovered_server_ip, sizeof(last_server_ip) - 1);
                last_server_ip[sizeof(last_server_ip) - 1] = '\0';
                saveLastServerIp(discovered_server_ip);
                Serial.print("UDP discovery from ");
                Serial.print(discovered_server_ip);
                Serial.print(":");
                Serial.println(discovered_server_port);
                if (changed) discovery_dirty = true;
            }
        }
    }
}

void stopSession(const char* session_id) {
    if (WiFi.status() != WL_CONNECTED) return;
    if (server_ip.length() == 0) return;
    if (millis() - last_http_success_ms > 30000) return;
    
    HTTPClient http;
    String url = "http://" + server_ip + ":" + String(server_port) + "/api/dashboard/session/" + String(session_id) + "/command";
    
    http.begin(url);
    http.setConnectTimeout(1500);
    http.setTimeout(1500);
    http.addHeader("Content-Type", "application/json");
    http.POST("{\"action\":\"stop\"}");
    http.end();
}

void pauseSession(const char* session_id) {
    if (WiFi.status() != WL_CONNECTED) return;
    if (server_ip.length() == 0) return;
    if (millis() - last_http_success_ms > 30000) return;
    
    HTTPClient http;
    String action = np_is_paused ? "resume" : "pause";
    String url = "http://" + server_ip + ":" + String(server_port) + "/api/dashboard/session/" + String(session_id) + "/command";
    http.begin(url);
    http.setConnectTimeout(1500);
    http.setTimeout(1500);
    http.addHeader("Content-Type", "application/json");
    http.POST(String("{\"action\":\"") + action + "\"}");
    http.end();
}
