#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h> // UDP Support
#include <ESPmDNS.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <lvgl.h>
#include <Preferences.h>
#include <HTTPClient.h>
#include <TJpg_Decoder.h>
#include "LGFX_Setup.h"

// --- DEFINITIONS ---
#define SCREEN_WIDTH 480
#define SCREEN_HEIGHT 320
#define POSTER_W 150
#define POSTER_H 225

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

// History buffers for sparklines (keep last 60 samples)
#define HISTORY_SIZE 60
uint8_t cpu_history[HISTORY_SIZE] = {0};
uint8_t ram_history[HISTORY_SIZE] = {0};
uint16_t net_down_history[HISTORY_SIZE] = {0};  // KB/s
uint16_t net_up_history[HISTORY_SIZE] = {0};    // KB/s
uint8_t history_idx = 0;
unsigned long last_history_update = 0;

// Screensaver
bool screensaver_active = false;
unsigned long last_user_activity = 0;
#define SCREENSAVER_TIMEOUT 300000  // 5 minutes

// Multiple sessions
int current_session_index = 0;
int total_sessions = 0;

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
lv_obj_t * canvas_cpu_graph;
lv_obj_t * canvas_ram_graph;
lv_obj_t * canvas_net_graph;
lv_draw_rect_dsc_t sparkline_dsc;

// Screensaver widgets
lv_obj_t * screensaver_cont;
lv_obj_t * screensaver_clock;
lv_obj_t * screensaver_date;

// Now Playing Widgets
lv_obj_t * cont_now_playing_list;
lv_obj_t * np_card;
lv_obj_t * np_img;
lv_obj_t * np_title;
lv_obj_t * np_sub;
lv_obj_t * np_meta;
lv_obj_t * np_quality;
lv_obj_t * np_time_remain;
lv_obj_t * np_bar;
lv_obj_t * np_btn_stop;
lv_obj_t * np_btn_pause;
lv_obj_t * np_empty_label;
lv_obj_t * np_loading_spinner;
char np_session_id[64] = "";
bool np_is_paused = false;
bool np_poster_loading = false;

// Settings Widgets
lv_obj_t * label_wifi_status;
lv_obj_t * label_wifi_signal;
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
void updateWifiSignal();
void updateHistoryBuffers(float cpu, float ram, uint32_t net_down, uint32_t net_up);
void drawSparkline(lv_obj_t* canvas, uint8_t* data, uint16_t len, lv_color_t color);
void drawSparklineU16(lv_obj_t* canvas, uint16_t* data, uint16_t len, lv_color_t color, uint16_t max_val);
void updateSparklines();
void checkScreensaver();
void activateScreensaver();
void deactivateScreensaver();
void updateScreensaverClock();
void buildScreensaver();
void resetUserActivity();

static bool posterJpgOutput(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap) {
    if (!bitmap) return false;
    if (x < 0 || y < 0) return true;
    if (x >= POSTER_W || y >= POSTER_H) return false;
    if ((x + (int)w) > POSTER_W || (y + (int)h) > POSTER_H) {
        return true;
    }
    sprite_poster.pushImage(x, y, w, h, bitmap);
    return true;
}

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
    TJpgDec.setCallback(posterJpgOutput);
    TJpgDec.setJpgScale(1);
    TJpgDec.setSwapBytes(true);

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

    // Initialize user activity timer
    last_user_activity = millis();

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
    updateWifiSignal();
    updateSparklines();
    checkScreensaver();

    if (screensaver_active) {
        updateScreensaverClock();
    }

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
        resetUserActivity();  // Reset screensaver timer on touch
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

void updateHistoryBuffers(float cpu, float ram, uint32_t net_down, uint32_t net_up) {
    if (millis() - last_history_update < 2000) return;  // Update every 2 seconds
    last_history_update = millis();

    cpu_history[history_idx] = (uint8_t)(cpu > 100 ? 100 : cpu);
    ram_history[history_idx] = (uint8_t)(ram > 100 ? 100 : ram);
    net_down_history[history_idx] = (uint16_t)(net_down / 1024);  // Convert to KB/s
    net_up_history[history_idx] = (uint16_t)(net_up / 1024);      // Convert to KB/s

    history_idx = (history_idx + 1) % HISTORY_SIZE;
}

void drawSparkline(lv_obj_t* canvas, uint8_t* data, uint16_t len, lv_color_t color) {
    if (!canvas || !data || len == 0) return;

    lv_canvas_fill_bg(canvas, lv_color_hex(0x0B1220), LV_OPA_0);

    lv_draw_line_dsc_t line_dsc;
    lv_draw_line_dsc_init(&line_dsc);
    line_dsc.color = color;
    line_dsc.width = 1;
    line_dsc.opa = LV_OPA_COVER;

    uint16_t w = lv_obj_get_width(canvas);
    uint16_t h = lv_obj_get_height(canvas);

    for (uint16_t i = 1; i < len && i < w; i++) {
        uint16_t idx1 = (history_idx + i - 1) % len;
        uint16_t idx2 = (history_idx + i) % len;

        int16_t y1 = h - (data[idx1] * h / 100);
        int16_t y2 = h - (data[idx2] * h / 100);
        int16_t x1 = i - 1;
        int16_t x2 = i;

        lv_point_t p[2] = {{x1, y1}, {x2, y2}};
        lv_canvas_draw_line(canvas, p, 2, &line_dsc);
    }
}

void drawSparklineU16(lv_obj_t* canvas, uint16_t* data, uint16_t len, lv_color_t color, uint16_t max_val) {
    if (!canvas || !data || len == 0 || max_val == 0) return;

    lv_canvas_fill_bg(canvas, lv_color_hex(0x0B1220), LV_OPA_0);

    lv_draw_line_dsc_t line_dsc;
    lv_draw_line_dsc_init(&line_dsc);
    line_dsc.color = color;
    line_dsc.width = 1;
    line_dsc.opa = LV_OPA_COVER;

    uint16_t w = lv_obj_get_width(canvas);
    uint16_t h = lv_obj_get_height(canvas);

    for (uint16_t i = 1; i < len && i < w; i++) {
        uint16_t idx1 = (history_idx + i - 1) % len;
        uint16_t idx2 = (history_idx + i) % len;

        uint16_t val1 = data[idx1] > max_val ? max_val : data[idx1];
        uint16_t val2 = data[idx2] > max_val ? max_val : data[idx2];

        int16_t y1 = h - (val1 * h / max_val);
        int16_t y2 = h - (val2 * h / max_val);
        int16_t x1 = i - 1;
        int16_t x2 = i;

        lv_point_t p[2] = {{x1, y1}, {x2, y2}};
        lv_canvas_draw_line(canvas, p, 2, &line_dsc);
    }
}

void updateSparklines() {
    if (!canvas_cpu_graph || !canvas_ram_graph || !canvas_net_graph) return;

    drawSparkline(canvas_cpu_graph, cpu_history, HISTORY_SIZE, lv_color_hex(0x3B82F6));
    drawSparkline(canvas_ram_graph, ram_history, HISTORY_SIZE, lv_color_hex(0x8B5CF6));

    // Find max for network scale
    uint16_t max_net = 100;  // Minimum 100 KB/s scale
    for (int i = 0; i < HISTORY_SIZE; i++) {
        if (net_down_history[i] > max_net) max_net = net_down_history[i];
        if (net_up_history[i] > max_net) max_net = net_up_history[i];
    }
    drawSparklineU16(canvas_net_graph, net_down_history, HISTORY_SIZE, lv_color_hex(0x10B981), max_net);
}

void resetUserActivity() {
    last_user_activity = millis();
    if (screensaver_active) {
        deactivateScreensaver();
    }
}

void checkScreensaver() {
    if (screensaver_active) return;

    if (millis() - last_user_activity > SCREENSAVER_TIMEOUT) {
        activateScreensaver();
    }
}

void activateScreensaver() {
    if (screensaver_active) return;
    screensaver_active = true;

    Serial.println("Activating screensaver");

    // Hide main UI
    if (tv) lv_obj_add_flag(tv, LV_OBJ_FLAG_HIDDEN);

    // Show screensaver
    if (screensaver_cont) {
        lv_obj_clear_flag(screensaver_cont, LV_OBJ_FLAG_HIDDEN);
    } else {
        buildScreensaver();
    }

    // Dim display
    tft.setBrightness(brightness / 4);  // 25% brightness
}

void deactivateScreensaver() {
    if (!screensaver_active) return;
    screensaver_active = false;

    Serial.println("Deactivating screensaver");

    // Restore brightness
    tft.setBrightness(brightness);

    // Hide screensaver
    if (screensaver_cont) lv_obj_add_flag(screensaver_cont, LV_OBJ_FLAG_HIDDEN);

    // Show main UI
    if (tv) lv_obj_clear_flag(tv, LV_OBJ_FLAG_HIDDEN);
}

void updateScreensaverClock() {
    static unsigned long last_clock_update = 0;
    if (millis() - last_clock_update < 1000) return;  // Update every second
    last_clock_update = millis();

    if (!screensaver_active || !screensaver_clock || !screensaver_date) return;

    time_t now = millis() / 1000;
    struct tm timeinfo;
    localtime_r(&now, &timeinfo);

    char time_str[16];
    char date_str[32];

    // Format time (HH:MM:SS)
    snprintf(time_str, sizeof(time_str), "%02d:%02d:%02d", timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);

    // Format date
    const char* days[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
    const char* months[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
    snprintf(date_str, sizeof(date_str), "%s, %s %d",
             days[timeinfo.tm_wday], months[timeinfo.tm_mon], timeinfo.tm_mday);

    lv_label_set_text(screensaver_clock, time_str);
    lv_label_set_text(screensaver_date, date_str);
}

void buildScreensaver() {
    screensaver_cont = lv_obj_create(lv_scr_act());
    lv_obj_set_size(screensaver_cont, SCREEN_WIDTH, SCREEN_HEIGHT);
    lv_obj_set_style_bg_color(screensaver_cont, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(screensaver_cont, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(screensaver_cont, 0, 0);
    lv_obj_set_style_pad_all(screensaver_cont, 0, 0);
    lv_obj_add_flag(screensaver_cont, LV_OBJ_FLAG_HIDDEN);

    // Clock
    screensaver_clock = lv_label_create(screensaver_cont);
    lv_obj_set_style_text_font(screensaver_clock, &lv_font_montserrat_48, 0);
    lv_obj_set_style_text_color(screensaver_clock, lv_color_hex(0xFFFFFF), 0);
    lv_label_set_text(screensaver_clock, "00:00:00");
    lv_obj_center(screensaver_clock);

    // Date
    screensaver_date = lv_label_create(screensaver_cont);
    lv_obj_set_style_text_font(screensaver_date, &lv_font_montserrat_20, 0);
    lv_obj_set_style_text_color(screensaver_date, lv_color_hex(0x94A3B8), 0);
    lv_label_set_text(screensaver_date, "");
    lv_obj_align_to(screensaver_date, screensaver_clock, LV_ALIGN_OUT_BOTTOM_MID, 0, 20);
}

void applyTheme() {
    lv_color_t bg = theme_dark ? lv_color_hex(0x0B1220) : lv_color_hex(0xF5F7FB);
    lv_color_t text = theme_dark ? lv_color_hex(0xE5E7EB) : lv_color_hex(0x0F172A);
    lv_color_t card = theme_dark ? lv_color_hex(0x1E293B) : lv_color_hex(0xFFFFFF);
    lv_color_t muted = theme_dark ? lv_color_hex(0x94A3B8) : lv_color_hex(0x475569);
    lv_color_t shadow = theme_dark ? lv_color_hex(0x000000) : lv_color_hex(0x64748B);

    lv_obj_set_style_bg_color(lv_scr_act(), bg, 0);
    lv_obj_set_style_text_color(lv_scr_act(), text, 0);

    if (tv) {
        lv_obj_set_style_bg_color(tv, bg, 0);
        lv_obj_set_style_text_color(tv, text, 0);
    }

    if (np_card) {
        lv_obj_set_style_bg_color(np_card, card, 0);
        lv_obj_set_style_shadow_color(np_card, shadow, 0);
    }
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

    // Add sparkline graphs
    static lv_color_t cbuf_cpu[LV_CANVAS_BUF_SIZE_TRUE_COLOR(60, 40)];
    static lv_color_t cbuf_ram[LV_CANVAS_BUF_SIZE_TRUE_COLOR(60, 40)];
    static lv_color_t cbuf_net[LV_CANVAS_BUF_SIZE_TRUE_COLOR(60, 40)];

    canvas_cpu_graph = lv_canvas_create(stats);
    lv_canvas_set_buffer(canvas_cpu_graph, cbuf_cpu, 60, 40, LV_IMG_CF_TRUE_COLOR);
    lv_obj_set_size(canvas_cpu_graph, 60, 40);

    canvas_ram_graph = lv_canvas_create(stats);
    lv_canvas_set_buffer(canvas_ram_graph, cbuf_ram, 60, 40, LV_IMG_CF_TRUE_COLOR);
    lv_obj_set_size(canvas_ram_graph, 60, 40);

    canvas_net_graph = lv_canvas_create(stats);
    lv_canvas_set_buffer(canvas_net_graph, cbuf_net, 60, 40, LV_IMG_CF_TRUE_COLOR);
    lv_obj_set_size(canvas_net_graph, 60, 40);
}

void buildNowPlayingTab(lv_obj_t * parent) {
    cont_now_playing_list = lv_obj_create(parent);
    lv_obj_set_size(cont_now_playing_list, LV_PCT(100), LV_PCT(100));
    lv_obj_set_flex_flow(cont_now_playing_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(cont_now_playing_list, 12, 0);
    lv_obj_set_style_pad_row(cont_now_playing_list, 12, 0);

    np_empty_label = lv_label_create(cont_now_playing_list);
    lv_label_set_text(np_empty_label, "No active sessions");
    lv_obj_set_style_text_font(np_empty_label, &lv_font_montserrat_18, 0);
    lv_obj_center(np_empty_label);

    np_card = lv_obj_create(cont_now_playing_list);
    lv_obj_set_size(np_card, LV_PCT(100), LV_PCT(100));
    lv_obj_set_flex_grow(np_card, 1);
    lv_obj_set_style_bg_opa(np_card, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(np_card, 16, 0);
    lv_obj_set_style_border_width(np_card, 0, 0);
    lv_obj_set_style_pad_all(np_card, 16, 0);
    lv_obj_set_style_shadow_width(np_card, 12, 0);
    lv_obj_set_style_shadow_opa(np_card, LV_OPA_20, 0);
    lv_obj_set_style_shadow_ofs_y(np_card, 4, 0);
    lv_obj_set_style_shadow_spread(np_card, 2, 0);
    lv_obj_add_flag(np_card, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_flex_flow(np_card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(np_card, 12, 0);

    lv_obj_t * top = lv_obj_create(np_card);
    lv_obj_set_width(top, LV_PCT(100));
    lv_obj_set_style_bg_opa(top, 0, 0);
    lv_obj_set_style_border_width(top, 0, 0);
    lv_obj_set_style_pad_all(top, 0, 0);
    lv_obj_set_flex_flow(top, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(top, 16, 0);

    // Poster container with rounded corners and border
    lv_obj_t * poster_cont = lv_obj_create(top);
    lv_obj_set_size(poster_cont, POSTER_W, POSTER_H);
    lv_obj_set_style_bg_opa(poster_cont, 0, 0);
    lv_obj_set_style_border_width(poster_cont, 2, 0);
    lv_obj_set_style_border_color(poster_cont, lv_color_hex(0x475569), 0);
    lv_obj_set_style_border_opa(poster_cont, LV_OPA_40, 0);
    lv_obj_set_style_radius(poster_cont, 12, 0);
    lv_obj_set_style_pad_all(poster_cont, 0, 0);
    lv_obj_set_style_clip_corner(poster_cont, true, 0);

    np_img = lv_img_create(poster_cont);
    lv_img_set_src(np_img, &img_poster_dsc);
    lv_obj_set_size(np_img, POSTER_W, POSTER_H);
    lv_obj_align(np_img, LV_ALIGN_CENTER, 0, 0);

    // Loading spinner (hidden by default)
    np_loading_spinner = lv_spinner_create(poster_cont, 1000, 60);
    lv_obj_set_size(np_loading_spinner, 50, 50);
    lv_obj_center(np_loading_spinner);
    lv_obj_add_flag(np_loading_spinner, LV_OBJ_FLAG_HIDDEN);

    lv_obj_t * info = lv_obj_create(top);
    lv_obj_set_style_bg_opa(info, 0, 0);
    lv_obj_set_style_border_width(info, 0, 0);
    lv_obj_set_flex_flow(info, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(info, 0, 0);
    lv_obj_set_style_pad_row(info, 8, 0);
    lv_obj_set_size(info, SCREEN_WIDTH - POSTER_W - 60, POSTER_H);
    lv_obj_set_flex_align(info, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

    np_title = lv_label_create(info);
    lv_obj_set_width(np_title, LV_PCT(100));
    lv_label_set_long_mode(np_title, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_style_text_font(np_title, &lv_font_montserrat_20, 0);
    lv_label_set_text(np_title, "");

    np_sub = lv_label_create(info);
    lv_obj_set_width(np_sub, LV_PCT(100));
    lv_obj_set_style_text_color(np_sub, lv_color_hex(0x94A3B8), 0);
    lv_obj_set_style_text_font(np_sub, &lv_font_montserrat_14, 0);
    lv_label_set_text(np_sub, "");

    // Add spacer
    lv_obj_t * spacer = lv_obj_create(info);
    lv_obj_set_flex_grow(spacer, 1);
    lv_obj_set_style_bg_opa(spacer, 0, 0);
    lv_obj_set_style_border_width(spacer, 0, 0);

    np_meta = lv_label_create(info);
    lv_obj_set_width(np_meta, LV_PCT(100));
    lv_obj_set_style_text_font(np_meta, &lv_font_montserrat_14, 0);
    lv_label_set_text(np_meta, "");

    np_quality = lv_label_create(info);
    lv_obj_set_width(np_quality, LV_PCT(100));
    lv_obj_set_style_text_font(np_quality, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_color(np_quality, lv_color_hex(0x64748B), 0);
    lv_label_set_text(np_quality, "");

    np_time_remain = lv_label_create(info);
    lv_obj_set_width(np_time_remain, LV_PCT(100));
    lv_obj_set_style_text_font(np_time_remain, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(np_time_remain, lv_color_hex(0x10B981), 0);
    lv_label_set_text(np_time_remain, "");

    np_bar = lv_bar_create(np_card);
    lv_obj_set_width(np_bar, LV_PCT(100));
    lv_obj_set_height(np_bar, 8);
    lv_bar_set_range(np_bar, 0, 100);
    lv_bar_set_value(np_bar, 0, LV_ANIM_OFF);
    lv_obj_set_style_bg_color(np_bar, lv_color_hex(0x1F2937), 0);
    lv_obj_set_style_bg_opa(np_bar, 255, 0);
    lv_obj_set_style_bg_color(np_bar, lv_color_hex(0x22C55E), LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(np_bar, 255, LV_PART_INDICATOR);
    lv_obj_set_style_radius(np_bar, 4, 0);
    lv_obj_set_style_radius(np_bar, 4, LV_PART_INDICATOR);

    lv_obj_t * ctrls = lv_obj_create(np_card);
    lv_obj_set_style_bg_opa(ctrls, 0, 0);
    lv_obj_set_style_border_width(ctrls, 0, 0);
    lv_obj_set_style_pad_all(ctrls, 0, 0);
    lv_obj_set_flex_flow(ctrls, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(ctrls, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_size(ctrls, LV_PCT(100), 50);
    lv_obj_set_style_pad_column(ctrls, 12, 0);

    np_btn_stop = lv_btn_create(ctrls);
    lv_obj_set_size(np_btn_stop, 120, 44);
    lv_obj_set_style_bg_color(np_btn_stop, lv_color_hex(0xEF4444), 0);
    lv_obj_set_style_radius(np_btn_stop, 10, 0);
    lv_obj_set_style_shadow_width(np_btn_stop, 8, 0);
    lv_obj_set_style_shadow_opa(np_btn_stop, LV_OPA_30, 0);
    lv_obj_set_style_shadow_ofs_y(np_btn_stop, 2, 0);
    lv_obj_t * lbl_stop = lv_label_create(np_btn_stop);
    lv_label_set_text(lbl_stop, "STOP");
    lv_obj_set_style_text_font(lbl_stop, &lv_font_montserrat_14, 0);
    lv_obj_center(lbl_stop);

    np_btn_pause = lv_btn_create(ctrls);
    lv_obj_set_size(np_btn_pause, 140, 44);
    lv_obj_set_style_bg_color(np_btn_pause, lv_color_hex(0xF59E0B), 0);
    lv_obj_set_style_radius(np_btn_pause, 10, 0);
    lv_obj_set_style_shadow_width(np_btn_pause, 8, 0);
    lv_obj_set_style_shadow_opa(np_btn_pause, LV_OPA_30, 0);
    lv_obj_set_style_shadow_ofs_y(np_btn_pause, 2, 0);
    lv_obj_t * lbl_pause = lv_label_create(np_btn_pause);
    lv_label_set_text(lbl_pause, "PAUSE");
    lv_obj_set_style_text_font(lbl_pause, &lv_font_montserrat_14, 0);
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

    label_wifi_signal = lv_label_create(parent);
    lv_label_set_text(label_wifi_signal, "Signal: --");
    lv_obj_set_style_text_font(label_wifi_signal, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_color(label_wifi_signal, lv_color_hex(0x64748B), 0);

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

void updateWifiSignal() {
    static unsigned long last_signal_update = 0;
    if (millis() - last_signal_update < 2000) return;  // Update every 2 seconds
    last_signal_update = millis();

    if (!label_wifi_signal) return;

    if (WiFi.status() == WL_CONNECTED) {
        int rssi = WiFi.RSSI();  // Get signal strength in dBm
        const char* quality;
        lv_color_t color;

        if (rssi >= -50) {
            quality = "Excellent";
            color = lv_color_hex(0x10B981);  // Green
        } else if (rssi >= -60) {
            quality = "Good";
            color = lv_color_hex(0x22C55E);  // Light green
        } else if (rssi >= -70) {
            quality = "Fair";
            color = lv_color_hex(0xF59E0B);  // Orange
        } else {
            quality = "Poor";
            color = lv_color_hex(0xEF4444);  // Red
        }

        lv_label_set_text_fmt(label_wifi_signal, "Signal: %d dBm (%s)", rssi, quality);
        lv_obj_set_style_text_color(label_wifi_signal, color, 0);
    } else {
        lv_label_set_text(label_wifi_signal, "Signal: --");
        lv_obj_set_style_text_color(label_wifi_signal, lv_color_hex(0x64748B), 0);
    }
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
    uint32_t net_down_bps = (uint32_t)(system["network_down_bps"].as<double>());
    uint32_t net_up_bps = (uint32_t)(system["network_up_bps"].as<double>());

    // Update history buffers for sparklines
    updateHistoryBuffers(cpu, ram, net_down_bps, net_up_bps);
    total_sessions = sessions.size();

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

    // Update quality/bitrate info
    if (np_quality) {
        uint32_t bitrate = s["bitrate"] | 0;
        if (bitrate > 0) {
            if (bitrate >= 1000000) {
                int mbps10 = (int)((bitrate * 10UL) / 1000000UL);
                lv_label_set_text_fmt(np_quality, "Quality: %d.%d Mbps", mbps10 / 10, mbps10 % 10);
            } else if (bitrate >= 1000) {
                int kbps = (int)(bitrate / 1000);
                lv_label_set_text_fmt(np_quality, "Quality: %d Kbps", kbps);
            } else {
                lv_label_set_text(np_quality, "");
            }
        } else {
            lv_label_set_text(np_quality, "");
        }
    }

    // Update time remaining
    if (np_time_remain && dur > 0 && cur < dur) {
        uint32_t remain = dur - cur;
        char remain_s[16];
        formatClock(remain_s, sizeof(remain_s), remain);
        lv_label_set_text_fmt(np_time_remain, "-%s remaining", remain_s);
    } else if (np_time_remain) {
        lv_label_set_text(np_time_remain, "");
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

            // Show loading spinner
            if (np_loading_spinner && url_changed) {
                lv_obj_clear_flag(np_loading_spinner, LV_OBJ_FLAG_HIDDEN);
                np_poster_loading = true;
            }

            if (downloadPoster(full_url.c_str())) {
                strncpy(current_poster_url, poster_url, 255);
                current_poster_url[255] = '\0';
                // Update image descriptor data pointer to current sprite buffer
                img_poster_dsc.data = (const uint8_t*)sprite_poster.getBuffer();
                img_poster_dsc.data_size = POSTER_W * POSTER_H * 2;
                lv_img_set_src(np_img, &img_poster_dsc);
                lv_obj_invalidate(np_img);
                Serial.printf("Poster updated: %s\n", poster_url);
            } else {
                Serial.printf("Poster download failed: %s\n", full_url.c_str());
            }

            // Hide loading spinner
            if (np_loading_spinner) {
                lv_obj_add_flag(np_loading_spinner, LV_OBJ_FLAG_HIDDEN);
                np_poster_loading = false;
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
                    JRESULT r = TJpgDec.drawJpg(0, 0, jpg_buf, (uint32_t)used);
                    ok = (r == JDR_OK);
                    if (!ok) ok = sprite_poster.drawJpg(jpg_buf, used, 0, 0, POSTER_W, POSTER_H);
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
