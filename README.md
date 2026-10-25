# Honeycomb Abaqus Studio

Ứng dụng Windows **WinUI 3 + Python** để tự động hóa khảo sát va đập tấm sandwich honeycomb bằng **Abaqus/Explicit 2017**, tạo dữ liệu có thể truy vết và báo cáo nghiên cứu.

**Tiến độ cloud:** repo đã public, runner Ubuntu đã được đo thực tế (145,19 GiB tổng, 85,64 GiB trống), engine đã qua CI Linux. Abaqus Linux/license và backend mô phỏng đầy đủ chưa được nghiệm thu. Xem [bằng chứng và các điều kiện còn chặn](docs/CLOUD_STATUS.md).

Mô hình nền tái dựng theo Foo, Seah & Chai, *Composite Structures* 85 (2008), DOI [10.1016/j.compstruct.2007.10.016](https://doi.org/10.1016/j.compstruct.2007.10.016). Mô hình không tự nhận là đã hội tụ hoặc tương đương thí nghiệm.

## Bản Windows x64

[Tải bản 0.2.0 preview](https://github.com/xuankhanh24/honeycomb-abaqus-studio/releases/tag/v0.2.0-preview). Giải nén đầy đủ vào đường dẫn ASCII, ví dụ `C:/HoneycombStudio`, rồi mở `HoneycombStudio.exe`. Bản này có .NET/WinAppSDK và Python riêng; Abaqus/license dùng bản đã cài trên máy. Không chạy exe tách khỏi các DLL/runtime đi kèm.

Xem [kết quả nghiệm thu](docs/VALIDATION_RESULTS.md) để phân biệt các kiểm thử đã đạt với kiểm tra hội tụ, gián đoạn Abaqus thật và reboot chưa hoàn tất. Drive thật đã được kiểm tra upload, tiếp tục và khôi phục. Đây là bản nghiên cứu nội bộ chưa ký mã.

## Dữ liệu gọn từ bản 0.2.0

Nút **Dữ liệu ML gọn** xuất `samples.csv/Parquet` (mỗi lượt một dòng), đường cong và từ điển cột. Mặc định không nhân bản dữ liệu trường của ODB. PDF mỗi lượt 5 trang tiếng Việt; bảng dẻo và thống kê nút/phần tử nằm ngoài PDF. CSV nút/phần tử là chức năng nâng cao có thể tạo hàng chục GB, không cần cho mô hình ML dạng bảng.

## Chức năng

- Chọn lõi lục giác hoặc **auxetic re-entrant hình 1 — 0°**; chỉnh kích thước ô lõm, dịch pha X/Z và lưới chiều sâu Y. Xem [kiểm tra tích hợp](docs/AUXETIC_0_VALIDATION.md).
- Xem/sửa hình học, bảng vật liệu, điều kiện tải, liên kết, lưới và output; preview input thực tế và toàn bộ lượt trước khi chạy.
- Quét năng lượng/vận tốc với bước nhảy, tổ hợp nhiều biến, Latin Hypercube có seed hoặc bảng CSV.
- Một solver tại một thời điểm; tiến độ vật lý, ETA, log, CPU/RAM, datacheck và điều kiện tài nguyên.
- Dừng hàng đợi hoặc dừng ngay; tiếp tục lượt bị dừng từ đầu, giữ các lượt đã hoàn tất và mọi attempt.
- Mở CAE/ODB bằng Abaqus; mặc định xuất chỉ số, đường cong và cực trị để huấn luyện/tối ưu; chế độ nâng cao sao chép mọi field ODB sang Parquet.
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
