# Sửa cuộn và cập nhật tiến độ WinUI

## Nguyên nhân

- Bộ hẹn giờ 2 giây xóa toàn bộ `Batches` và `Runs` rồi tạo lại các hàng. Việc này thay container, chạy lại hiệu ứng tiến độ và có thể làm mất vị trí cuộn/chọn.
- Một số ScrollViewer chỉ dùng cuộn ngang vẫn cho phép đo nội dung theo chiều dọc không giới hạn. Danh sách bên trong không có viewport cuộn độc lập đúng kích thước.
- EngineClient giữ URL/token lúc khởi tạo nên cửa sổ đang mở vẫn gọi cổng cũ sau khi engine khởi động lại.
- Khi chọn job khác, chi tiết lượt cũ chưa được xóa; phản hồi bất đồng bộ có thể về sau khi đã đổi lựa chọn.

## Thay đổi

- Đối chiếu hàng theo ID, chỉ thêm/xóa/di chuyển khi danh sách thực sự đổi. Các hàng phát thông báo thay đổi thuộc tính; x:Bind dùng OneWay.
- Tắt đo/cuộn dọc ở viewport chỉ dùng cuộn ngang; bật cuộn dọc ở bảng lượt và các bảng chi tiết. Tab chi tiết giãn theo chiều cao được cấp.
- Cài đặt hiển thị cột cũng phát thông báo thay đổi, không dựng lại hàng.
- Đọc lại session trước yêu cầu API. GET bị lỗi kết nối có thể kết nối lại và thử một lần; POST không được tự gửi lại vì có thể đã thực thi.
- Xóa chi tiết khi đổi job, bỏ phản hồi chi tiết không còn thuộc lượt đang chọn. Không mở lại thông báo giống hệt liên tục.

## Kiểm tra

`dotnet test tests/Desktop.Tests` kiểm tra giữ nguyên đối tượng hàng, không phát sự kiện thay đổi collection khi chỉ tăng tiến độ, không thông báo lại tiến độ không đổi; kiểm tra chuyển giữa hai engine HTTP cục bộ khi session đổi và POST chỉ gửi một lần.

Build/publish Release WinUI trên Windows. Kiểm tra trực tiếp job 13 lượt: cuộn bảng input và bảng lượt, giữ vị trí qua nhiều chu kỳ cập nhật; thanh tiến độ tăng trong cùng hàng. Cập nhật riêng giao diện, không dừng engine hay solver.
