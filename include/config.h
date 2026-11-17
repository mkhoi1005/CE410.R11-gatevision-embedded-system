//Giả định: Sử dụng PlatformIO (Arduino framework) cho ESP32-S3-N16R8 CAM với PSRAM hoạt động ở chế độ Octal.

/**
 * @file config.h
 * @brief Cấu hình mạng Wi-Fi, Server và các tham số thời gian
 */
#pragma once

//Điểm CHƯA CHỐT: Địa chỉ IP của Raspberry Pi Server và thông tin Wi-Fi mạng LAN được đặt qua file cấu hình

#define WIFI_SSID         "GateVision_LAN"     // Thay bằng SSID thực tế trong LAN
#define WIFI_PASSWORD     "gatevision123"      // Mật khẩu Wi-Fi 2.4GHz

// Sử dụng IP tĩnh cho Server (Raspberry Pi 4) theo quy định dự án
#define SERVER_URL        "http://192.168.1.100:8000/api/v1/capture"
#define DEVICE_KEY        "secret_device_key_change_me"

// Các hằng số nghiệp vụ
#define DISTANCE_THRESHOLD_CM   40.0   // Khoảng cách kích hoạt (cm)
#define DETECT_STABLE_MS        300    // Thời gian vật cản liên tục để chụp (ms)
#define GATE_OPEN_MAX_S         10     // Thời gian giữ mở tối đa (giây)
#define CLEAR_CHECK_MS          1000   // Thời gian xe đi qua hẳn để đóng cổng (ms)
#define COOLDOWN_MS             5000   // Thời gian chống kích hoạt lặp (ms)
#define SERVER_TIMEOUT_MS       8000   // Timeout HTTP POST (8 giây)