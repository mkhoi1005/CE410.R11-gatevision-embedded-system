/* Cấu hình web GATE VISION. Mọi hằng số đổi được nằm ở đây. */
window.GV_CONFIG = {
  // true: dữ liệu giả chạy ngay trong trình duyệt (không cần server).
  // false: gọi server thật qua API_BASE và WS_PATH.
  USE_MOCK: true,
  API_BASE: '/api/v1',
  WS_PATH: '/ws/events',
  // Chỉ dùng cho dữ liệu giả. ĐỀ XUẤT - CẦN XÁC NHẬN (Q10: HOLD_MAX_S)
  HOLD_MAX_S: 120,
  TZ: 'Asia/Ho_Chi_Minh'
};
