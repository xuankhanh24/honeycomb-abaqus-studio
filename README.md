# Honeycomb Abaqus Studio

Ứng dụng Windows **WinUI 3 + Python** để tự động hóa khảo sát va đập tấm sandwich honeycomb bằng **Abaqus/Explicit 2017**, tạo dữ liệu có thể truy vết và báo cáo nghiên cứu.

Mô hình nền tái dựng theo Foo, Seah & Chai, *Composite Structures* 85 (2008), DOI [10.1016/j.compstruct.2007.10.016](https://doi.org/10.1016/j.compstruct.2007.10.016). Mô hình không tự nhận là đã hội tụ hoặc tương đương thí nghiệm.

## Chức năng

- Xem/sửa hình học, bảng vật liệu, điều kiện tải, liên kết, lưới và output; preview input thực tế và toàn bộ lượt trước khi chạy.
- Quét năng lượng/vận tốc với bước nhảy, tổ hợp nhiều biến, Latin Hypercube có seed hoặc bảng CSV.
- Một solver tại một thời điểm; tiến độ vật lý, ETA, log, CPU/RAM, datacheck và điều kiện tài nguyên.
- Dừng hàng đợi hoặc dừng ngay; tiếp tục lượt bị dừng từ đầu, giữ các lượt đã hoàn tất và mọi attempt.
- Mở CAE/ODB bằng Abaqus; xuất toàn bộ history và mọi field đã lưu trong ODB sang Parquet, giữ integration/section point và cơ sở tọa độ.
- CSV, JSON, Parquet, PDF từng lượt/toàn job, ZIP64 có manifest và checksum.
- Tập dữ liệu có chia nhóm thiết kế để tránh rò rỉ train/test; đường cong gốc và nội suy riêng; so sánh Pareto theo cùng điều kiện tải.
- Google Drive OAuth, upload tiếp tục, kiểm tra checksum và khôi phục về job mới.

## Chạy từ mã nguồn

Yêu cầu Windows x64, .NET SDK **10.0.402**, `uv`, Python 3.13 (uv có thể cung cấp) và Abaqus đã cài/license hợp lệ. Python hiện đại không thay thế Python của Abaqus.

```powershell
git clone https://github.com/xuankhanh24/honeycomb-abaqus-studio.git
cd honeycomb-abaqus-studio
./scripts/setup.ps1
./scripts/start-app.ps1
```

Ứng dụng tự kết nối/khởi động engine nền. Đóng giao diện không dừng solver. Xem log engine trực tiếp bằng `./scripts/start-engine.ps1` khi chưa có engine khác.

Dữ liệu mặc định: `C:/UET/DO_AN/honeycomb-data`; lệnh Abaqus: `C:/SIMULIA/Commands/abaqus.bat`. Đổi trong **Backup và cài đặt** cho lần khởi động engine tiếp theo. File session/token nằm trong `%LOCALAPPDATA%/HoneycombStudio`, không đưa vào repo.

## Lưới mặc định

Lõi 0,7 mm tại vùng tâm bán kính 22 mm, ngoài 1,3 mm, 20 lớp theo chiều cao. Mặt 0,75/1,25 mm. Thời gian vật lý 6 ms, 120 khoảng field và 1.200 khoảng history. Tám CPU, double precision, không mass scaling. **20–30 phút là ngân sách dự báo, không phải cam kết cho mọi thiết kế và máy.** Thời gian trích xuất toàn field, PDF và backup được tính riêng.

## Kiểm thử và đóng gói

```powershell
./scripts/test.ps1
uv run python scripts/validate_abaqus.py --smoke
uv run python scripts/validate_abaqus.py --convergence
./scripts/publish.ps1
```

CI dùng solver giả lập chỉ để kiểm tra điều phối; kiểm thử mô phỏng thật cần máy có Abaqus. Script convergence chạy ba mức lưới 7 J và ghi tiêu chí/sai lệch, không tự ép kết quả khớp bài báo.

## Tài liệu

- [Hướng dẫn sử dụng](docs/USER_GUIDE.md)
- [Kiến trúc và giao thức](docs/ARCHITECTURE.md), [API](docs/API.md)
- [Tham số và đơn vị](docs/PARAMETERS.md), [Từ điển dữ liệu](docs/DATA_DICTIONARY.md)
- [Kiểm chứng khoa học](docs/SCIENTIFIC_VALIDATION.md), [Nghiệm thu](docs/ACCEPTANCE.md)
- [Google Drive](docs/DRIVE_BACKUP.md), [Xử lý lỗi](docs/TROUBLESHOOTING.md)
- [Phát triển và phát hành](docs/DEVELOPMENT.md)

Repo chứa mã nguồn, tài liệu, schema và cấu hình nhỏ. CAE/ODB, dữ liệu huấn luyện, credential và bản phát hành được lưu riêng.
