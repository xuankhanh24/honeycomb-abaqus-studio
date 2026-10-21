# Hướng dẫn sử dụng

## Tạo khảo sát

1. Mở **Tạo job**, đặt tên và kiểm tra các nhóm hình học, vật liệu, va đập, liên kết, lưới, solver/output. Mỗi dòng có đơn vị và nguồn. `bottom_skin=null` nghĩa là mặt dưới bằng mặt trên.
2. Chọn `loading=energy` để quét `energy_J`; chọn `loading=velocity` để quét `velocity_m_s`. Khối lượng thay đổi sẽ làm đại lượng phụ thuộc được tính lại.
3. Trong **Khoảng và bước nhảy**, khai báo đầu/cuối/bước hoặc danh sách JSON. Ví dụ `[0.85,2,4,7,10,13]`. Các hàng được tổ hợp khi chọn grid; LHS dùng khoảng đầu/cuối và số mẫu/seed, không dùng bước.
4. Để thay seed thủ công, chọn `mesh_preset=custom`. Các preset còn lại ghi đè seed bằng thông số preset trong input thực tế. Quick/fine chưa tự động được công nhận hội tụ.
5. Chọn **Kiểm tra và preview**. Kiểm tra số lượt, input thực tế, dữ liệu vật liệu, thời gian/dung lượng ước tính; sau đó tạo job. Tạo job chưa tự chạy solver.
6. Sang **Job mô phỏng**, chọn job và bấm **Chạy / Tiếp tục**.

## Theo dõi và dừng

Job hiển thị số lượt theo trạng thái. Chọn lượt để xem input/output/attempt, log, ảnh và đường cong. Phần trăm solver tính từ thời gian vật lý, không phải phần trăm thời gian thực. Dựng hình/render có thể không có phần trăm đo được.

- **Dừng**: dừng hàng đợi và lượt đang thực thi, giữ file attempt. Khi tiếp tục, lượt chưa tính xong chạy lại từ 0 trong attempt mới.
- **Dừng sau lượt này**: giữ lượt hiện tại chạy hết, sau đó tạm dừng.
- **Chạy lại lượt**: chỉ chọn lại một lượt. Lỗi trích xuất/render/PDF sau solver hoàn tất chỉ làm lại hậu xử lý.
- Đóng cửa sổ không dừng engine. Khi mở lại, ứng dụng kết nối tới engine đang chạy. Sau sự cố engine, ownership PID + thời điểm tạo tiến trình được dùng để nhận diện tiến trình cũ.

Không chỉnh bộ input của job đã tạo. Tạo job mới để giữ lịch sử tái lập.

## Xem và xuất

Mở ODB/CAE bằng nút trong lượt; ODB dùng Abaqus/Viewer, CAE dùng Abaqus/CAE. PDF và thư mục dùng ứng dụng Windows mặc định. File chỉ xuất hiện khi giai đoạn tương ứng đã hoàn tất.

Mỗi lượt có JSON input, dữ liệu Parquet/CSV, ảnh và PDF; ZIP đóng gói toàn bộ dữ liệu đã hoàn tất kèm checksum. Field → CSV có thể tạo nhiều file lớn; Parquet vẫn là bản xuất mặc định cho dữ liệu trường.

PDF toàn job gồm bảng mọi lượt và so sánh. Các giá trị nút/phần tử đầy đủ nằm trong Parquet, không in hàng triệu dòng lên PDF.

## Dataset và Pareto

Trong thư viện, lọc lượt đủ chất lượng, chọn nhiều lượt rồi xuất dataset. Tên feature có tiền tố `input.`, ví dụ `input.skin,input.core_height,input.foil`; target ví dụ `peak_raw_contact_force_N,SEA_J_kg`.

Dataset giữ provenance, input đầy đủ riêng và đường cong gốc; dữ liệu nội suy có tên riêng. Các thiết kế giống nhau qua tải/lưới/attempt được nhóm trong cùng split. Ít thiết kế có thể làm validation/test trống; cần bổ sung thiết kế độc lập trước khi đánh giá ML.

Pareto chia theo điều kiện tải, đồng thời giảm khối lượng/lực/độ võng và tăng SEA. Đây là phân tích tập dữ liệu đã mô phỏng, chưa phải quá trình huấn luyện hoặc tự sinh thiết kế AI.

## Cài đặt và backup

Thay thư mục/lệnh Abaqus được lưu cho lần khởi động engine tiếp theo. Đường dẫn kỹ thuật nên dùng ASCII để tương thích Abaqus 2017. Không chạy nhiều engine thủ công trên cùng dữ liệu.

Google Drive cần OAuth client Desktop. Khi kết nối thành công có thể backup job và tiếp tục upload bị gián đoạn. Khôi phục luôn tạo job mới và kiểm tra file; không ghi đè job gốc. Xem [hướng dẫn Drive](DRIVE_BACKUP.md).
