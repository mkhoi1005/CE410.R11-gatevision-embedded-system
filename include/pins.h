/**
 * @file pins.h
 * @brief Định nghĩa sơ đồ chân GPIO cho Nút B (ESP32-S3-N16R8 CAM - Cổng RA)
 */
#pragma once

// Cảm biến khoảng cách HC-SR04 (Đã qua mạch chia áp cho chân ECHO)
#define HC_SR04_TRIG_PIN  43
#define HC_SR04_ECHO_PIN  44

// Servo SG90 quay liên tục (360 độ) điều khiển thanh chắn
#define DIN_SERVO_PIN     21

// Định danh thiết bị Nút B
#define DEVICE_ID         "node_b_out"
#define GATE_TYPE         "OUT"
