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
#define POSTER_W 110
#define POSTER_H 160

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
bool downloadPoster(const char* url);
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
    
    tab_dash = lv_tabview_add_tab(tv, "Dashboard");
    tab_now_playing = lv_tabview_add_tab(tv, "Now Playing");
    tab_settings = lv_tabview_add_tab(tv, "Settings");

    buildDashboardTab(tab_dash);
    buildNowPlayingTab(tab_now_playing);
    buildSettingsTab(tab_settings);

    applyTheme();
}

void buildDashboardTab(lv_obj_t * parent) {
    lv_obj_set_flex_flow(parent, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(parent, 6, 0);
    lv_obj_set_style_pad_row(parent, 6, 0);

    lv_obj_t * top = lv_obj_create(parent);
    lv_obj_set_width(top, LV_PCT(100));
    lv_obj_set_style_bg_opa(top, 0, 0);
    lv_obj_set_style_border_width(top, 0, 0);
    lv_obj_set_style_pad_all(top, 0, 0);
    lv_obj_set_flex_flow(top, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(top, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    lv_obj_t * top_left = lv_obj_create(top);
    lv_obj_set_style_bg_opa(top_left, 0, 0);
    lv_obj_set_style_border_width(top_left, 0, 0);
    lv_obj_set_style_pad_all(top_left, 0, 0);
    lv_obj_set_flex_flow(top_left, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(top_left, 2, 0);
    lv_obj_set_width(top_left, LV_PCT(68));

    label_status = lv_label_create(top_left);
    lv_obj_set_width(label_status, LV_PCT(100));
    lv_obj_set_style_text_font(label_status, &lv_font_montserrat_18, 0);
    lv_label_set_long_mode(label_status, LV_LABEL_LONG_DOT);
    lv_label_set_text(label_status, "Nomad Pi: Disconnected");

    label_dash_server = lv_label_create(top_left);
    lv_obj_set_width(label_dash_server, LV_PCT(100));
    lv_obj_set_style_text_font(label_dash_server, &lv_font_montserrat_14, 0);
    lv_label_set_long_mode(label_dash_server, LV_LABEL_LONG_DOT);
    lv_label_set_text(label_dash_server, "Server: --");

    lv_obj_t * top_right = lv_obj_create(top);
    lv_obj_set_style_bg_opa(top_right, 0, 0);
    lv_obj_set_style_border_width(top_right, 0, 0);
    lv_obj_set_style_pad_all(top_right, 0, 0);
    lv_obj_set_flex_flow(top_right, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(top_right, 2, 0);
    lv_obj_set_width(top_right, LV_PCT(30));

    label_dash_users = lv_label_create(top_right);
    lv_obj_set_width(label_dash_users, LV_PCT(100));
    lv_obj_set_style_text_font(label_dash_users, &lv_font_montserrat_14, 0);
    lv_label_set_text(label_dash_users, "Users: --");

    label_dash_uptime = lv_label_create(top_right);
    lv_obj_set_width(label_dash_uptime, LV_PCT(100));
    lv_obj_set_style_text_font(label_dash_uptime, &lv_font_montserrat_14, 0);
    lv_label_set_text(label_dash_uptime, "Up: --:--");

    lv_obj_t * body = lv_obj_create(parent);
    lv_obj_set_size(body, LV_PCT(100), LV_PCT(100));
    lv_obj_set_flex_grow(body, 1);
    lv_obj_set_style_bg_opa(body, 0, 0);
    lv_obj_set_style_border_width(body, 0, 0);
    lv_obj_set_style_pad_all(body, 0, 0);
    lv_obj_set_flex_flow(body, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(body, 8, 0);

    lv_obj_t * arcs = lv_obj_create(body);
    lv_obj_set_width(arcs, 220);
    lv_obj_set_style_bg_opa(arcs, 0, 0);
    lv_obj_set_style_border_width(arcs, 0, 0);
    lv_obj_set_style_pad_all(arcs, 0, 0);
    lv_obj_set_flex_flow(arcs, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(arcs, LV_FLEX_ALIGN_SPACE_EVENLY, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    arc_cpu = lv_arc_create(arcs);
    lv_obj_set_size(arc_cpu, 100, 100);
    lv_arc_set_rotation(arc_cpu, 270);
    lv_arc_set_bg_angles(arc_cpu, 0, 360);
    lv_arc_set_value(arc_cpu, 0);
    
    label_cpu = lv_label_create(arc_cpu);
    lv_obj_center(label_cpu);
    lv_label_set_text(label_cpu, "CPU\n0%");
    lv_obj_set_style_text_align(label_cpu, LV_TEXT_ALIGN_CENTER, 0);

    arc_ram = lv_arc_create(arcs);
    lv_obj_set_size(arc_ram, 100, 100);
    lv_arc_set_rotation(arc_ram, 270);
    lv_arc_set_bg_angles(arc_ram, 0, 360);
    lv_arc_set_value(arc_ram, 0);
    
    label_ram = lv_label_create(arc_ram);
    lv_obj_center(label_ram);
    lv_label_set_text(label_ram, "RAM\n0%");
    lv_obj_set_style_text_align(label_ram, LV_TEXT_ALIGN_CENTER, 0);

    lv_obj_t * stats = lv_obj_create(body);
    lv_obj_set_flex_grow(stats, 1);
    lv_obj_set_height(stats, LV_PCT(100));
    lv_obj_set_style_bg_opa(stats, 0, 0);
    lv_obj_set_style_border_width(stats, 0, 0);
    lv_obj_set_style_pad_all(stats, 0, 0);
    lv_obj_set_flex_flow(stats, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(stats, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

    label_stats = lv_label_create(stats);
    lv_obj_set_width(label_stats, LV_PCT(100));
    lv_obj_set_style_text_font(label_stats, &lv_font_montserrat_14, 0);
    lv_label_set_long_mode(label_stats, LV_LABEL_LONG_WRAP);
    lv_label_set_text(label_stats, "Disk: --%  |  Users: --\nDown: --  |  Up: --");
}

void buildNowPlayingTab(lv_obj_t * parent) {
    cont_now_playing_list = lv_obj_create(parent);
    lv_obj_set_size(cont_now_playing_list, LV_PCT(100), LV_PCT(100));
    lv_obj_set_flex_flow(cont_now_playing_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(cont_now_playing_list, 10, 0);
    lv_obj_set_style_pad_row(cont_now_playing_list, 10, 0);
    
    np_empty_label = lv_label_create(cont_now_playing_list);
    lv_label_set_text(np_empty_label, "No active sessions");
    lv_obj_center(np_empty_label);

    np_card = lv_obj_create(cont_now_playing_list);
    lv_obj_set_size(np_card, LV_PCT(100), LV_PCT(100));
    lv_obj_set_flex_grow(np_card, 1);
    lv_obj_set_style_bg_opa(np_card, 0, 0);
    lv_obj_set_style_radius(np_card, 0, 0);
    lv_obj_set_style_border_width(np_card, 0, 0);
    lv_obj_set_style_pad_all(np_card, 0, 0);
    lv_obj_add_flag(np_card, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_flex_flow(np_card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(np_card, 10, 0);

    lv_obj_t * top = lv_obj_create(np_card);
    lv_obj_set_width(top, LV_PCT(100));
    lv_obj_set_style_bg_opa(top, 0, 0);
    lv_obj_set_style_border_width(top, 0, 0);
    lv_obj_set_style_pad_all(top, 0, 0);
    lv_obj_set_flex_flow(top, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(top, 12, 0);

    np_img = lv_img_create(top);
    lv_img_set_src(np_img, &img_poster_dsc);
    lv_obj_set_size(np_img, POSTER_W, POSTER_H);
    lv_obj_align(np_img, LV_ALIGN_TOP_LEFT, 0, 0);

    lv_obj_t * info = lv_obj_create(top);
    lv_obj_set_style_bg_opa(info, 0, 0);
    lv_obj_set_style_border_width(info, 0, 0);
    lv_obj_set_flex_flow(info, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(info, 6, 0);
    lv_obj_set_size(info, SCREEN_WIDTH - POSTER_W - 44, POSTER_H);

    np_title = lv_label_create(info);
    lv_obj_set_width(np_title, LV_PCT(100));
    lv_label_set_long_mode(np_title, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_style_text_font(np_title, &lv_font_montserrat_18, 0);
    lv_label_set_text(np_title, "");

    np_sub = lv_label_create(info);
    lv_obj_set_width(np_sub, LV_PCT(100));
    lv_obj_set_style_text_color(np_sub, lv_color_hex(0x94A3B8), 0);
    lv_label_set_text(np_sub, "");

    np_meta = lv_label_create(info);
    lv_obj_set_width(np_meta, LV_PCT(100));
    lv_obj_set_style_text_font(np_meta, &lv_font_montserrat_14, 0);
    lv_label_set_text(np_meta, "");

    np_bar = lv_bar_create(np_card);
    lv_obj_set_width(np_bar, LV_PCT(100));
    lv_obj_set_height(np_bar, 14);
    lv_bar_set_range(np_bar, 0, 100);
    lv_bar_set_value(np_bar, 0, LV_ANIM_OFF);
    lv_obj_set_style_bg_color(np_bar, lv_color_hex(0x1F2937), 0);
    lv_obj_set_style_bg_opa(np_bar, 255, 0);
    lv_obj_set_style_bg_color(np_bar, lv_color_hex(0x22C55E), LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(np_bar, 255, LV_PART_INDICATOR);
    lv_obj_set_style_radius(np_bar, 8, 0);
    lv_obj_set_style_radius(np_bar, 8, LV_PART_INDICATOR);

    lv_obj_t * ctrls = lv_obj_create(np_card);
    lv_obj_set_style_bg_opa(ctrls, 0, 0);
    lv_obj_set_style_border_width(ctrls, 0, 0);
    lv_obj_set_style_pad_all(ctrls, 0, 0);
    lv_obj_set_flex_flow(ctrls, LV_FLEX_FLOW_ROW);
    lv_obj_set_size(ctrls, LV_PCT(100), 40);
    lv_obj_set_style_pad_column(ctrls, 10, 0);

    np_btn_stop = lv_btn_create(ctrls);
    lv_obj_set_size(np_btn_stop, 100, 34);
    lv_obj_set_style_bg_color(np_btn_stop, lv_color_hex(0xEF4444), 0);
    lv_obj_t * lbl_stop = lv_label_create(np_btn_stop);
    lv_label_set_text(lbl_stop, "STOP");
    lv_obj_center(lbl_stop);

    np_btn_pause = lv_btn_create(ctrls);
    lv_obj_set_size(np_btn_pause, 120, 34);
    lv_obj_set_style_bg_color(np_btn_pause, lv_color_hex(0xF59E0B), 0);
    lv_obj_t * lbl_pause = lv_label_create(np_btn_pause);
    lv_label_set_text(lbl_pause, "PAUSE");
    lv_obj_center(lbl_pause);

    lv_obj_add_event_cb(np_btn_stop, [](lv_event_t* e){
        if (strlen(np_session_id) > 0) stopSession(np_session_id);
    }, LV_EVENT_CLICKED, NULL);

    lv_obj_add_event_cb(np_btn_pause, [](lv_event_t* e){
        if (strlen(np_session_id) > 0) pauseSession(np_session_id);
    }, LV_EVENT_CLICKED, NULL);
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
            last_http_success_ms = millis();
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
    last_http_success_ms = millis();
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
    // Update Stats
    float cpu = system["cpu_percent"].as<float>();
    float ram = system["ram_percent"].as<float>();
    float disk = system["disk_percent"].as<float>();
    int active_users = system["active_users"].as<int>();
    uint32_t uptime_seconds = (uint32_t)(system["uptime_seconds"].as<double>());
    
    lv_arc_set_value(arc_cpu, (int)cpu);
    int cpu10 = (int)(cpu * 10.0f + 0.5f);
    lv_label_set_text_fmt(label_cpu, "CPU\n%d.%d%%", cpu10 / 10, cpu10 % 10);
    
    lv_arc_set_value(arc_ram, (int)ram);
    int ram10 = (int)(ram * 10.0f + 0.5f);
    lv_label_set_text_fmt(label_ram, "RAM\n%d.%d%%", ram10 / 10, ram10 % 10);

    if (label_dash_users) {
        lv_label_set_text_fmt(label_dash_users, "Users: %d", active_users);
    }
    if (label_dash_uptime) {
        char up[16];
        formatClock(up, sizeof(up), uptime_seconds);
        lv_label_set_text_fmt(label_dash_uptime, "Up: %s", up);
    }
    
    // Format bytes for net speed
    uint32_t net_down_bps = (uint32_t)(system["network_down_bps"].as<double>());
    uint32_t net_up_bps = (uint32_t)(system["network_up_bps"].as<double>());

    int down10 = 0;
    const char* unit_d = "B/s";
    if (net_down_bps < 1024) {
        down10 = (int)net_down_bps * 10;
        unit_d = "B/s";
    } else if (net_down_bps < (1024UL * 1024UL)) {
        down10 = (int)((net_down_bps * 10UL) / 1024UL);
        unit_d = "KB/s";
    } else {
        down10 = (int)((net_down_bps * 10UL) / (1024UL * 1024UL));
        unit_d = "MB/s";
    }

    int up10 = 0;
    const char* unit_u = "B/s";
    if (net_up_bps < 1024) {
        up10 = (int)net_up_bps * 10;
        unit_u = "B/s";
    } else if (net_up_bps < (1024UL * 1024UL)) {
        up10 = (int)((net_up_bps * 10UL) / 1024UL);
        unit_u = "KB/s";
    } else {
        up10 = (int)((net_up_bps * 10UL) / (1024UL * 1024UL));
        unit_u = "MB/s";
    }

    int disk10 = (int)(disk * 10.0f + 0.5f);
    lv_label_set_text_fmt(
        label_stats,
        "Disk: %d.%d%%  |  Users: %d\nDown: %d.%d %s  |  Up: %d.%d %s",
        disk10 / 10, disk10 % 10,
        active_users,
        down10 / 10, down10 % 10, unit_d,
        up10 / 10, up10 % 10, unit_u
    );

    if (sessions.size() == 0) {
        lv_obj_add_flag(np_card, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(np_empty_label, LV_OBJ_FLAG_HIDDEN);
        strcpy(np_session_id, "");
        strcpy(current_poster_url, "");
        return;
    }

    lv_obj_add_flag(np_empty_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(np_card, LV_OBJ_FLAG_HIDDEN);

    JsonObject s = sessions[0];
    const char* sid_src = s["session_id"] | "";
    strncpy(np_session_id, sid_src, sizeof(np_session_id) - 1);
    np_session_id[sizeof(np_session_id) - 1] = '\0';

    lv_label_set_text(np_title, s["title"] | "Unknown");
    const char* user = s["username"] | "User";
    const char* type = s["media_type"] | "media";
    lv_label_set_text_fmt(np_sub, "%s • %s", user, type);

    const char* state = s["state"] | "unknown";
    double cur_f = (double)(s["current_time"] | 0.0);
    double dur_f = (double)(s["duration"] | 0.0);
    if (cur_f < 0) cur_f = 0;
    if (dur_f < 0) dur_f = 0;
    uint32_t cur = (uint32_t)(cur_f);
    uint32_t dur = (uint32_t)(dur_f);
    if (dur > 0 && cur > dur) cur = dur;
    if (np_bar) {
        if (dur > 0) {
            lv_bar_set_range(np_bar, 0, (int32_t)dur);
            lv_bar_set_value(np_bar, (int32_t)cur, LV_ANIM_OFF);
        } else {
            lv_bar_set_range(np_bar, 0, 100);
            lv_bar_set_value(np_bar, 0, LV_ANIM_OFF);
        }
    }
    if (np_meta) {
        char cur_s[16];
        char dur_s[16];
        formatClock(cur_s, sizeof(cur_s), cur);
        formatClock(dur_s, sizeof(dur_s), dur);
        if (dur > 0) {
            lv_label_set_text_fmt(np_meta, "%s • %s / %s", state, cur_s, dur_s);
        } else {
            lv_label_set_text_fmt(np_meta, "%s • %s", state, cur_s);
        }
    }

    np_is_paused = strcmp((const char*)(s["state"] | ""), "paused") == 0;
    lv_obj_set_style_bg_color(np_btn_pause, np_is_paused ? lv_color_hex(0x10B981) : lv_color_hex(0xF59E0B), 0);
    lv_label_set_text(lv_obj_get_child(np_btn_pause, 0), np_is_paused ? "PLAY" : "PAUSE");

    const char* poster_url = s["poster_thumb"];
    if (!poster_url) poster_url = s["poster_url"];
    if (poster_url) {
        bool url_changed = (strcmp(current_poster_url, poster_url) != 0);
        bool retry_due = (!url_changed) && (millis() - last_poster_fetch_ms > 30000);
        bool time_ok = (millis() - last_poster_fetch_ms > 15000);
        if (time_ok && (url_changed || retry_due)) {
            last_poster_fetch_ms = millis();
            String full_url;
            if (poster_url[0] == '/') {
                full_url = "http://" + server_ip + ":" + String(server_port) + String(poster_url);
            } else {
                full_url = String(poster_url);
            }
            if (downloadPoster(full_url.c_str())) {
                strncpy(current_poster_url, poster_url, 255);
                current_poster_url[255] = '\0';
                lv_img_set_src(np_img, &img_poster_dsc);
                lv_obj_invalidate(np_img);
            }
        }
    }
}

bool downloadPoster(const char* url) {
    if (WiFi.status() != WL_CONNECTED) return false;
    
    HTTPClient http;
    const char* hdr_keys[] = { "Content-Type", "Content-Length" };
    http.collectHeaders(hdr_keys, 2);
    http.begin(url);
    http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
    http.setUserAgent("NomadDisplay/1.0");
    http.setConnectTimeout(4000);
    http.setTimeout(8000);
    int httpCode = http.GET();
    
    if (httpCode == 200) {
        int len = http.getSize();
        String ct = http.header("Content-Type");
        if (ct.length() == 0) ct = "unknown";
        WiFiClient * stream = http.getStreamPtr();
        size_t cap = (len > 0) ? (size_t)len : 65536;
        if (cap > 500000) cap = 500000;
        uint8_t* jpg_buf = (uint8_t*)malloc(cap);
        if (jpg_buf) {
            size_t used = 0;
            while (stream && http.connected()) {
                int avail = stream->available();
                if (avail <= 0) {
                    delay(1);
                    if (!http.connected()) break;
                    continue;
                }
                size_t want = (size_t)avail;
                if (want > (cap - used)) {
                    size_t next_cap = cap;
                    while (want > (next_cap - used) && next_cap < 500000) {
                        size_t grow = next_cap / 2;
                        if (grow < 16384) grow = 16384;
                        next_cap += grow;
                        if (next_cap > 500000) next_cap = 500000;
                        if (next_cap == cap) break;
                    }
                    if (next_cap != cap) {
                        uint8_t* next_buf = (uint8_t*)realloc(jpg_buf, next_cap);
                        if (next_buf) {
                            jpg_buf = next_buf;
                            cap = next_cap;
                        }
                    }
                    if (want > (cap - used)) want = cap - used;
                }
                if (want == 0) break;
                int got = stream->readBytes(jpg_buf + used, want);
                if (got <= 0) break;
                used += (size_t)got;
                if (used >= cap) break;
            }
            if (used > 0) {
                bool ok = false;
                sprite_poster.fillSprite(TFT_BLACK);
                if (used >= 8 &&
                    jpg_buf[0] == 0x89 && jpg_buf[1] == 0x50 && jpg_buf[2] == 0x4E && jpg_buf[3] == 0x47 &&
                    jpg_buf[4] == 0x0D && jpg_buf[5] == 0x0A && jpg_buf[6] == 0x1A && jpg_buf[7] == 0x0A) {
                    ok = sprite_poster.drawPng(jpg_buf, used, 0, 0, POSTER_W, POSTER_H);
                } else if (used >= 2 && jpg_buf[0] == 0xFF && jpg_buf[1] == 0xD8) {
                    ok = sprite_poster.drawJpg(jpg_buf, used, 0, 0, POSTER_W, POSTER_H);
                } else {
                    ok = sprite_poster.drawJpg(jpg_buf, used, 0, 0, POSTER_W, POSTER_H);
                    if (!ok) ok = sprite_poster.drawPng(jpg_buf, used, 0, 0, POSTER_W, POSTER_H);
                }

                if (!ok) {
                    uint8_t b0 = jpg_buf[0];
                    uint8_t b1 = (used > 1) ? jpg_buf[1] : 0;
                    uint8_t b2 = (used > 2) ? jpg_buf[2] : 0;
                    uint8_t b3 = (used > 3) ? jpg_buf[3] : 0;
                    Serial.printf("Poster decode failed ct=%s bytes=%u hdr=%02X %02X %02X %02X url=%s\n", ct.c_str(), (unsigned)used, b0, b1, b2, b3, url);
                }
                free(jpg_buf);
                http.end();
                return ok;
            }
            free(jpg_buf);
        }
    } else {
        String ct = http.header("Content-Type");
        if (ct.length() == 0) ct = "unknown";
        Serial.printf("Poster HTTP %d ct=%s url=%s\n", httpCode, ct.c_str(), url);
    }
    http.end();
    return false;
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
    if (!is_connected && (millis() - last_http_success_ms > 30000)) return;
    
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
    if (!is_connected && (millis() - last_http_success_ms > 30000)) return;
    
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
