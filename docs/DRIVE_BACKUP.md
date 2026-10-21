# Google Drive: cấu hình, backup và khôi phục

## Cấu hình lần đầu

1. Trong Google Cloud Console, tạo/chọn project và bật Google Drive API.
2. Cấu hình OAuth consent screen. Nếu còn Testing, thêm tài khoản Google của bạn làm test user.
3. Tạo OAuth client loại **Desktop app**, tải client JSON và giữ ngoài repo/thư mục dữ liệu mô phỏng.
4. Trong ứng dụng, nhập đường dẫn JSON và chọn **Đăng nhập Google Drive**. Trình duyệt hệ thống mở để bạn tự đăng nhập/chấp thuận. Ứng dụng không thu mật khẩu.

Scope `drive.file` dùng cho file do ứng dụng tạo/quản lý. Token refresh/access được mã hóa bằng Windows DPAPI dưới người dùng hiện tại. Token không nằm trong ZIP backup và không được commit. Khôi phục trên máy khác cần đăng nhập lại.

Project hiện ở trạng thái **Testing** và chỉ thêm tài khoản chủ dự án làm test user. Google giới hạn refresh token của ứng dụng External/Testing dùng Drive ở **7 ngày**; khi hết hạn, đăng nhập lại trong Cài đặt rồi tiếp tục backup đang chờ. Không tự chuyển ứng dụng sang Production. Nguồn: [Google — refresh token expiration](https://developers.google.com/identity/protocols/oauth2/#expiration).

## Upload

Job được đóng gói ZIP64 với manifest và snapshot SQLite nhất quán. Chỉ snapshot kết quả khi file không đang được solver ghi. Drive dùng resumable upload 8 MiB/chunk; state lưu ở backup-manifests, có offset, bytes, speed và ETA.

Mất mạng hoặc lỗi tạm thời được retry có backoff; nếu chưa hoàn tất, chọn backup ID và **Tiếp tục upload**. Session hết hạn sẽ tạo session mới ở lần tiếp tục. Không đánh dấu hoàn tất trước khi Drive trả kích thước và MD5 trùng bản local. Manifest SHA-256 dùng để kiểm tra khi tải về/khôi phục.

Backup không đổi kết quả mô phỏng thành failed và không tự xóa ODB local. Nếu chưa cấu hình OAuth, ứng dụng giữ nguyên dữ liệu và báo cần kết nối. Quota Drive phụ thuộc tài khoản; một ODB tham chiếu đã khoảng 2,67 GB, chưa kể Parquet và backup ZIP local.

## Khôi phục

Có thể dùng ZIP local hoặc Drive file ID + SHA-256 của gói trong backup manifest. Khôi phục kiểm tra SHA-256 gói tải về, chặn ZIP path traversal/symlink, kiểm tra từng file rồi tạo job ID mới. Không ghi đè job cũ; process ownership được xóa khi đăng ký bản khôi phục.

## Kiểm thử tích hợp thật

Test upload/restore mạng thật cần OAuth client và người dùng đăng nhập. Credential được cấu hình trong Google Cloud với sự cho phép của chủ tài khoản; người dùng tự đăng nhập và cấp quyền. Không đọc mật khẩu hoặc đưa client JSON/token vào repo. Bộ kiểm thử tự động kiểm tra archive, checksum và khôi phục local; quy trình nghiệm thu Drive thật gồm ngắt mạng giữa upload, tiếp tục, tải về và so checksum.

Nguồn: [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [resumable uploads](https://developers.google.com/workspace/drive/api/guides/manage-uploads).

## Kết quả tích hợp trên máy hiện tại

Ngày 21/10/2026, OAuth Desktop và Drive API đã được cấu hình trong project `honeycomb-abaqus-studio-2004` theo tài khoản chủ dự án chọn. Client JSON nằm tại `%LOCALAPPDATA%/HoneycombStudio/drive-desktop-client.json`; refresh/access token chỉ nằm trong file DPAPI riêng. Không sao chép các file này vào dữ liệu hay gói phát hành.

Đã upload và restore job tổng hợp khoảng 24 MiB trên Drive thật, tiếp tục đúng offset sau khi chủ động ngắt client sau chunk 8 MiB, kiểm tra size/MD5/SHA-256 và checksum dữ liệu khôi phục. Chạy lại bằng `uv run python scripts/validate_drive.py --root C:/UET/DO_AN/honeycomb-drive-validation --account <email>`; script giữ file thử và đánh dấu không dùng cho ML, không tắt mạng của máy.
