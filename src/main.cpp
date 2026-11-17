/**
 * @file main.cpp
 * @brief Firmware chính cho Nút B (Cổng RA) - GateVision v2
 */
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_camera.h>
#include <ArduinoJson.h>
#include "pins.h"
#include "config.h"

// Định nghĩa cấu hình chân Camera OV2640 cho ESP32-S3-CAM
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     15
#define SIOD_GPIO_NUM     4
#define SIOC_GPIO_NUM     5
#define Y9_GPIO_NUM       16
#define Y8_GPIO_NUM       17
#define Y7_GPIO_NUM       18
#define Y6_GPIO_NUM       12
#define Y5_GPIO_NUM       10
#define Y4_GPIO_NUM       8
#define Y3_GPIO_NUM       9
#define Y2_GPIO_NUM       11
#define VSYNC_GPIO_NUM    6
#define HREF_GPIO_NUM     7
#define PCLK_GPIO_NUM     13

// Các trạng thái của máy trạng thái (State Machine)
enum GateState {
    IDLE,
    DETECTED,
    CAPTURING,
    WAITING_SERVER,
    GATE_OPENING,
    GATE_OPEN,
    GATE_CLOSING,
    HOLD,
    COOLDOWN,
    ERROR_STATE
};

GateState currentState = IDLE;
unsigned long stateTimer = 0;
unsigned long detectStartMs = 0;

// Khởi tạo camera OV2640
bool initCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size = FRAMESIZE_SVGA; // Mặc định SVGA
    config.jpeg_quality = 12;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_PSRAM;

    if (psramFound()) {
        config.jpeg_quality = 10;
        config.fb_count = 2;
    }

    esp_err_t err = esp_camera_init(&config);
    return (err == ESP_OK);
}

// Đo khoảng cách bằng HC-SR04
float readDistanceCM() {
    digitalWrite(HC_SR04_TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(HC_SR04_TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(HC_SR04_TRIG_PIN, LOW);

    long duration = pulseIn(HC_SR04_ECHO_PIN, HIGH, 30000); // Timeout 30ms
    if (duration == 0) return 999.0;
    return duration * 0.034 / 2.0;
}

// Điều khiển Servo 360 độ (Mở / Đóng / Dừng)
void controlServo(String action) {
    // Với servo 360 độ quay liên tục:
    // Ghi xung PWM điều khiển chiều quay và thời gian, sau đó dừng.
    if (action == "OPEN") {
        pinMode(DIN_SERVO_PIN, OUTPUT);
        digitalWrite(DIN_SERVO_PIN, HIGH); // Quay mở cổng
        delay(1500); // Thời gian quay tương ứng hành trình mở
        digitalWrite(DIN_SERVO_PIN, LOW);  // Dừng
    } else if (action == "CLOSE") {
        pinMode(DIN_SERVO_PIN, OUTPUT);
        digitalWrite(DIN_SERVO_PIN, HIGH); // Quay đóng cổng
        delay(1500); // Thời gian quay tương ứng hành trình đóng
        digitalWrite(DIN_SERVO_PIN, LOW);  // Dừng
    }
}

// Gửi ảnh HTTP POST lên Server
String sendCaptureToServer(camera_fb_t *fb, String &outDecision) {
    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("X-Device-Key", DEVICE_KEY);
    http.setTimeout(SERVER_TIMEOUT_MS);

    String boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW";
    String header = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"gate\"\r\n\r\n" + GATE_TYPE + "\r\n" +
                    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"device_id\"\r\n\r\n" + DEVICE_ID + "\r\n" +
                    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"image\"; filename=\"capture.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
    
    String footer = "\r\n--" + boundary + "--\r\n";
    size_t totalLen = header.length() + fb->len + footer.length();

    http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);

    // Xây dựng payload và gửi yêu cầu
    uint8_t *payload = (uint8_t *)malloc(totalLen);
    if (!payload) {
        http.end();
        return "ERROR";
    }

    memcpy(payload, header.c_str(), header.length());
    memcpy(payload + header.length(), fb->buf, fb->len);
    memcpy(payload + header.length() + fb->len, footer.c_str(), footer.length());

    int httpResponseCode = http.POST(payload, totalLen);
    free(payload);

    String responseBody = "";
    if (httpResponseCode > 0) {
        responseBody = http.getString();
        StaticJsonDocument<256> doc;
        DeserializationError error = deserializeJson(doc, responseBody);
        if (!error) {
            outDecision = doc["decision"].as<String>(); // Nhận "OPEN" hoặc "HOLD"[cite: 1]
        } else {
            outDecision = "HOLD";
        }
    } else {
        outDecision = "ERROR"; // Fail-safe: lỗi mạng coi như giữ lại
    }

    http.end();
    return outDecision;
}

void setup() {
    Serial.begin(115200);
    pinMode(HC_SR04_TRIG_PIN, OUTPUT);
    pinMode(HC_SR04_ECHO_PIN, INPUT);
    pinMode(DIN_SERVO_PIN, OUTPUT);
    digitalWrite(DIN_SERVO_PIN, LOW);

    // Kết nối Wi-Fi LAN
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWiFi connected.");

    // Khởi tạo Camera
    if (!initCamera()) {
        Serial.println("Camera init failed!");
        currentState = ERROR_STATE;
    }
}

void loop() {
    // Nguyên tắc Fail-safe cốt lõi: Mất kết nối Wi-Fi -> Cổng đóng, không tự mở[cite: 1]
    if (WiFi.status() != WL_CONNECTED) {
        currentState = ERROR_STATE;
    }

    switch (currentState) {
        case IDLE: {
            float dist = readDistanceCM();
            if (dist > 0 && dist <= DISTANCE_THRESHOLD_CM) {
                if (detectStartMs == 0) detectStartMs = millis();
                else if (millis() - detectStartMs >= DETECT_STABLE_MS) {
                    currentState = DETECTED;
                    detectStartMs = 0;
                }
            } else {
                detectStartMs = 0;
            }
            break;
        }

        case DETECTED: {
            currentState = CAPTURING;
            break;
        }

        case CAPTURING: {
            camera_fb_t *fb = esp_camera_fb_get();
            if (!fb) {
                currentState = IDLE;
                break;
            }

            currentState = WAITING_SERVER;
            String decision = "";
            sendCaptureToServer(fb, decision);
            esp_camera_fb_return(fb);

            if (decision == "OPEN") {
                currentState = GATE_OPENING;
            } else {
                // HOLD hoặc lỗi mạng -> Giữ cổng đóng, chuyển sang trạng thái chờ xử lý thủ công[cite: 1]
                currentState = HOLD;
            }
            break;
        }

        case GATE_OPENING: {
            controlServo("OPEN");
            stateTimer = millis();
            currentState = GATE_OPEN;
            break;
        }

        case GATE_OPEN: {
            // Giữ mở tối đa GATE_OPEN_MAX_S hoặc khi xe đã đi qua hẳn
            float dist = readDistanceCM();
            bool clearPassed = (dist > DISTANCE_THRESHOLD_CM);

            if (clearPassed || (millis() - stateTimer >= (GATE_OPEN_MAX_S * 1000UL))) {
                currentState = GATE_CLOSING;
            }
            break;
        }

        case GATE_CLOSING: {
            controlServo("CLOSE");
            stateTimer = millis();
            currentState = COOLDOWN;
            break;
        }

        case HOLD: {
            // Trạng thái giữ cổng đóng, chờ nhân viên xử lý thủ công trên web (poll command)[cite: 1]
            // Chuyển về COOLDOWN sau một khoảng thời gian chờ hoặc nhận lệnh DENY
            delay(2000); 
            currentState = COOLDOWN;
            break;
        }

        case COOLDOWN: {
            delay(COOLDOWN_MS);
            currentState = IDLE;
            break;
        }

        case ERROR_STATE: {
            // Fail-safe: Đảm bảo cổng luôn đóng khi có lỗi hệ thống hoặc mất mạng[cite: 1]
            digitalWrite(DIN_SERVO_PIN, LOW);
            delay(2000);
            if (WiFi.status() == WL_CONNECTED) {
                currentState = IDLE;
            }
            break;
        }
    }
}
/*Lệnh Build và Kiểm thử
* Sử dụng PlatformIO để biên dịch và nạp firmware cho board ESP32-S3:
  ```bash
  pio run --target upload
  */