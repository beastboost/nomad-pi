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
bool ws_started = false;
bool mdns_started = false;

char discovered_server_ip[64] = "";
int discovered_server_port = 8000;

bool wifi_connecting = false;
unsigned long wifi_connect_start_ms = 0;
unsigned long last_http_poll_ms = 0;

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
lv_obj_t * list_wifi; 
lv_obj_t * win_wifi;  
lv_obj_t * kb;
lv_obj_t * ta_pass;

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
    if (ws_started) {
        webSocket.loop();
    }

    processWsMessage();

    lv_timer_handler();

    handleWifiConnection();
    
    if (WiFi.status() == WL_CONNECTED) {
        checkUDP();
    }

    if (WiFi.status() == WL_CONNECTED && !is_connected) {
        pollDashboardHttp();
    }

    if (!is_connected) {
        // Retry connection logic
        static unsigned long last_connect_attempt = 0;
        if (millis() - last_connect_attempt > 5000) {
            last_connect_attempt = millis();
            if (WiFi.status() == WL_CONNECTED) {
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
    tft.setBrightness(128);
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
    preferences.end();
    
    strncpy(wifi_ssid, s.c_str(), 63);
    strncpy(wifi_pass, p.c_str(), 63);
}

void savePreferences() {
    preferences.begin("nomad-display", false);
    preferences.putString("ssid", wifi_ssid);
    preferences.putString("pass", wifi_pass);
    preferences.end();
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
}

void buildDashboardTab(lv_obj_t * parent) {
    // Top Row: Arcs
    lv_obj_t * row_arcs = lv_obj_create(parent);
    lv_obj_set_size(row_arcs, LV_PCT(100), 120);
    lv_obj_set_flex_flow(row_arcs, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row_arcs, LV_FLEX_ALIGN_SPACE_EVENLY, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_bg_opa(row_arcs, 0, 0);
    lv_obj_set_style_border_width(row_arcs, 0, 0);
    lv_obj_set_style_pad_all(row_arcs, 0, 0);

    // CPU
    arc_cpu = lv_arc_create(row_arcs);
    lv_obj_set_size(arc_cpu, 100, 100);
    lv_arc_set_rotation(arc_cpu, 270);
    lv_arc_set_bg_angles(arc_cpu, 0, 360);
    lv_arc_set_value(arc_cpu, 0);
    
    label_cpu = lv_label_create(arc_cpu);
    lv_obj_center(label_cpu);
    lv_label_set_text(label_cpu, "CPU\n0%");
    lv_obj_set_style_text_align(label_cpu, LV_TEXT_ALIGN_CENTER, 0);

    // RAM
    arc_ram = lv_arc_create(row_arcs);
    lv_obj_set_size(arc_ram, 100, 100);
    lv_arc_set_rotation(arc_ram, 270);
    lv_arc_set_bg_angles(arc_ram, 0, 360);
    lv_arc_set_value(arc_ram, 0);
    
    label_ram = lv_label_create(arc_ram);
    lv_obj_center(label_ram);
    lv_label_set_text(label_ram, "RAM\n0%");
    lv_obj_set_style_text_align(label_ram, LV_TEXT_ALIGN_CENTER, 0);

    // Bottom Row: Stats Text
    lv_obj_t * row_stats = lv_obj_create(parent);
    lv_obj_set_size(row_stats, LV_PCT(100), LV_SIZE_CONTENT);
    lv_obj_align(row_stats, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_set_flex_flow(row_stats, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(row_stats, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_bg_opa(row_stats, 0, 0);
    lv_obj_set_style_border_width(row_stats, 0, 0);

    label_stats = lv_label_create(row_stats);
    lv_label_set_text(label_stats, "Disk: --% | Net: 0 KB/s");
    lv_obj_set_style_text_font(label_stats, &lv_font_montserrat_14, 0);
    
    label_status = lv_label_create(row_stats);
    lv_label_set_text(label_status, "Status: Disconnected");
    lv_obj_set_style_text_color(label_status, lv_color_hex(0xEF4444), 0);
}

void buildNowPlayingTab(lv_obj_t * parent) {
    cont_now_playing_list = lv_obj_create(parent);
    lv_obj_set_size(cont_now_playing_list, LV_PCT(100), LV_PCT(100));
    lv_obj_set_flex_flow(cont_now_playing_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(cont_now_playing_list, 10, 0);
    
    np_empty_label = lv_label_create(cont_now_playing_list);
    lv_label_set_text(np_empty_label, "No active sessions");
    lv_obj_center(np_empty_label);

    np_card = lv_obj_create(cont_now_playing_list);
    lv_obj_set_size(np_card, LV_PCT(100), 170);
    lv_obj_set_style_bg_color(np_card, lv_color_hex(0x334155), 0);
    lv_obj_set_style_pad_all(np_card, 8, 0);
    lv_obj_add_flag(np_card, LV_OBJ_FLAG_HIDDEN);

    np_img = lv_img_create(np_card);
    lv_img_set_src(np_img, &img_poster_dsc);
    lv_obj_set_size(np_img, POSTER_W, POSTER_H);
    lv_obj_align(np_img, LV_ALIGN_LEFT_MID, 0, 0);

    lv_obj_t * info = lv_obj_create(np_card);
    lv_obj_set_style_bg_opa(info, 0, 0);
    lv_obj_set_style_border_width(info, 0, 0);
    lv_obj_set_flex_flow(info, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(info, 6, 0);
    lv_obj_set_pos(info, POSTER_W + 10, 10);
    lv_obj_set_size(info, SCREEN_WIDTH - POSTER_W - 40, 150);

    np_title = lv_label_create(info);
    lv_obj_set_width(np_title, LV_PCT(100));
    lv_label_set_long_mode(np_title, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_style_text_font(np_title, &lv_font_montserrat_14, 0);
    lv_label_set_text(np_title, "");

    np_sub = lv_label_create(info);
    lv_obj_set_width(np_sub, LV_PCT(100));
    lv_obj_set_style_text_color(np_sub, lv_color_hex(0x94A3B8), 0);
    lv_label_set_text(np_sub, "");

    np_bar = lv_bar_create(info);
    lv_obj_set_width(np_bar, LV_PCT(100));
    lv_obj_set_height(np_bar, 10);
    lv_bar_set_range(np_bar, 0, 100);
    lv_bar_set_value(np_bar, 0, LV_ANIM_OFF);

    lv_obj_t * ctrls = lv_obj_create(info);
    lv_obj_set_style_bg_opa(ctrls, 0, 0);
    lv_obj_set_style_border_width(ctrls, 0, 0);
    lv_obj_set_style_pad_all(ctrls, 0, 0);
    lv_obj_set_flex_flow(ctrls, LV_FLEX_FLOW_ROW);
    lv_obj_set_size(ctrls, LV_PCT(100), 40);

    np_btn_stop = lv_btn_create(ctrls);
    lv_obj_set_size(np_btn_stop, 70, 30);
    lv_obj_set_style_bg_color(np_btn_stop, lv_color_hex(0xEF4444), 0);
    lv_obj_t * lbl_stop = lv_label_create(np_btn_stop);
    lv_label_set_text(lbl_stop, "STOP");
    lv_obj_center(lbl_stop);

    np_btn_pause = lv_btn_create(ctrls);
    lv_obj_set_size(np_btn_pause, 70, 30);
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
    
    // Status Labels
    label_wifi_status = lv_label_create(parent);
    lv_label_set_text(label_wifi_status, "Wi-Fi: Not Connected");
    lv_obj_set_style_text_font(label_wifi_status, &lv_font_montserrat_14, 0);
    
    label_connection_info = lv_label_create(parent);
    lv_label_set_text(label_connection_info, "Server: Auto-discovery");
    lv_obj_set_style_text_font(label_connection_info, &lv_font_montserrat_14, 0);
    
    // Scan Button
    btn_scan_wifi = lv_btn_create(parent);
    lv_obj_set_width(btn_scan_wifi, LV_PCT(100));
    lv_obj_t * lbl_scan = lv_label_create(btn_scan_wifi);
    lv_label_set_text(lbl_scan, "Scan & Connect Wi-Fi");
    lv_obj_add_event_cb(btn_scan_wifi, [](lv_event_t* e){ showWifiScanWindow(); }, LV_EVENT_CLICKED, NULL);
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
            if (resolved == "0.0.0.0") {
                server_ip = "nomadpi.local";
            } else {
                server_ip = resolved;
            }
        } else {
            server_ip = "nomadpi.local";
        }
    }
    
    lv_label_set_text_fmt(label_connection_info, "Connecting to %s...", server_ip.c_str());
    Serial.print("Attempt WS to ");
    Serial.print(server_ip);
    Serial.print(":");
    Serial.println(server_port);

    webSocket.disconnect();
    webSocket.begin(server_ip.c_str(), server_port, "/api/dashboard/ws");
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(5000);
    webSocket.enableHeartbeat(15000, 5000, 2);
    ws_started = true;
}

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
    switch(type) {
        case WStype_CONNECTED:
            Serial.println("WS: connected");
            lv_label_set_text(label_status, "Nomad Pi: Online");
            lv_label_set_text_fmt(label_connection_info, "Connected to %s", server_ip.c_str());
            lv_obj_set_style_text_color(label_status, lv_color_hex(0x10B981), 0);
            is_connected = true;
            break;
        case WStype_DISCONNECTED:
            Serial.println("WS: disconnected");
            lv_label_set_text(label_status, "Nomad Pi: Disconnected");
            lv_label_set_text_fmt(label_connection_info, "WS Disconnected\nRetrying...");
            lv_obj_set_style_text_color(label_status, lv_color_hex(0xEF4444), 0);
            is_connected = false;
            break;
        case WStype_ERROR:
            Serial.println("WS: error");
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
    if (millis() - last_http_poll_ms < 10000) return;
    last_http_poll_ms = millis();

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
            lv_label_set_text_fmt(label_connection_info, "HTTP fallback OK\n%s:%d", server_ip.c_str(), server_port);
            updateDashboardUI(doc["sessions"], doc["system"]);
        }
        return;
    }

    lv_label_set_text_fmt(label_connection_info, "HTTP Poll Error: %d\nServer: %s", code, server_ip.c_str());
    http.end();
}

void updateDashboardUI(JsonArray sessions, JsonObject system) {
    // Update Stats
    float cpu = system["cpu_percent"].as<float>();
    float ram = system["ram_percent"].as<float>();
    float disk = system["disk_percent"].as<float>();
    int active_users = system["active_users"].as<int>();
    
    lv_arc_set_value(arc_cpu, (int)cpu);
    lv_label_set_text_fmt(label_cpu, "CPU\n%.1f%%", cpu);
    
    lv_arc_set_value(arc_ram, (int)ram);
    lv_label_set_text_fmt(label_ram, "RAM\n%.1f%%", ram);
    
    // Format bytes for net speed
    float net_down = system["network_down_bps"].as<float>();
    float net_up = system["network_up_bps"].as<float>();
    
    // Format Down
    const char* unit_d = "B/s";
    if(net_down > 1024) { net_down /= 1024; unit_d = "KB/s"; }
    if(net_down > 1024) { net_down /= 1024; unit_d = "MB/s"; }

    // Format Up
    const char* unit_u = "B/s";
    if(net_up > 1024) { net_up /= 1024; unit_u = "KB/s"; }
    if(net_up > 1024) { net_up /= 1024; unit_u = "MB/s"; }
    
    lv_label_set_text_fmt(label_stats, "Disk: %.1f%%  |  Users: %d\nDown: %.1f %s  |  Up: %.1f %s", 
        disk, active_users, net_down, unit_d, net_up, unit_u);

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
    lv_bar_set_value(np_bar, (int)(s["progress_percent"] | 0), LV_ANIM_OFF);

    np_is_paused = strcmp((const char*)(s["state"] | ""), "paused") == 0;
    lv_obj_set_style_bg_color(np_btn_pause, np_is_paused ? lv_color_hex(0x10B981) : lv_color_hex(0xF59E0B), 0);
    lv_label_set_text(lv_obj_get_child(np_btn_pause, 0), np_is_paused ? "PLAY" : "PAUSE");

    const char* poster_url = s["poster_thumb"];
    if (!poster_url) poster_url = s["poster_url"];
    if (poster_url && strcmp(current_poster_url, poster_url) != 0 && (millis() - last_poster_fetch_ms > 15000)) {
        last_poster_fetch_ms = millis();
        String full_url;
        if (poster_url[0] == '/') {
            full_url = "http://" + server_ip + ":" + String(server_port) + String(poster_url);
        } else {
            full_url = String(poster_url);
        }
        downloadPoster(full_url.c_str());
        strncpy(current_poster_url, poster_url, 255);
        current_poster_url[255] = '\0';
        lv_img_set_src(np_img, &img_poster_dsc);
        lv_obj_invalidate(np_img);
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
        if (len > 0 && len < 100000) { // Limit to 100KB
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
                strncpy(discovered_server_ip, ip.c_str(), sizeof(discovered_server_ip) - 1);
                discovered_server_ip[sizeof(discovered_server_ip) - 1] = '\0';
                discovered_server_port = port;
                Serial.print("UDP discovery from ");
                Serial.print(discovered_server_ip);
                Serial.print(":");
                Serial.println(discovered_server_port);
            }
        }
    }
}

void stopSession(const char* session_id) {
    if (!is_connected) return;
    
    HTTPClient http;
    String url = "http://" + server_ip + ":" + String(server_port) + "/api/dashboard/session/" + String(session_id) + "/stop";
    
    http.begin(url);
    http.setConnectTimeout(1500);
    http.setTimeout(1500);
    int httpCode = http.POST("");
    http.end();
}

void pauseSession(const char* session_id) {
    if (!is_connected) return;
    
    HTTPClient http;
    String action = np_is_paused ? "resume" : "pause";
    String url = "http://" + server_ip + ":" + String(server_port) + "/api/dashboard/session/" + String(session_id) + "/" + action;
    http.begin(url);
    http.setConnectTimeout(1500);
    http.setTimeout(1500);
    http.POST("");
    http.end();
}
