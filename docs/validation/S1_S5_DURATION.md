# S1–S5: kiểm chứng thời lượng 8–12 ms

Yêu cầu thực hiện trên GitHub Actions: để sáu ca 8 ms hoàn tất, sau đó kiểm chứng 12 ms cho B0249 và ứng viên có SEA FEA cao nhất trong các ca đạt chất lượng số, còn nguyên mặt đáy. Không huấn luyện lại mô hình hoặc sửa bộ 489 mẫu đã đóng băng.

## Phạm vi đã khóa

- Source workflow: `43566570839`, SHA `7448dfc4811dc304d5c6bceb447b810556905ffa`.
- Source catalog: `3bc66c62749746a7839df1a87392d798`.
- Follow-up catalog: `16582a107020fec6da4eb3b066b9d5b8` (chỉ được tạo khi nguồn đã hoàn tất và hợp lệ).
- Cấu hình: `s1-s5-duration-followup.json` chứa input hash và SHA-256 sáu mô-đun vật lý.

Workflow `validation-duration-followup.yml` nhận sự kiện hoàn tất của đúng lượt nguồn. Nó kiểm tra toàn bộ sáu kết quả đã lưu, trạng thái solver, lịch sử đầu ra, chất lượng số và đầu vào từng shard trước khi chọn ứng viên. Không dùng SEA dự báo để lựa chọn. Nếu dữ liệu thiếu/lỗi hoặc không có ứng viên còn nguyên mặt đáy, bước chọn dừng với thông báo; không tạo kết quả thay thế.

Hai ca mới giữ hình học, vật liệu, lưới, vận tốc, 4 CPU và double precision. Chỉ thay thời lượng thành 12 ms và tăng field/history intervals lên 1200/6000 để giữ chu kỳ lưu 10 µs/2 µs. Mức dự phòng đĩa vẫn là 20 GB. Dọn thêm .NET, GHC và CodeQL không dùng trên runner Linux tạm để có đủ chỗ cho lượt 12 ms và bộ restart. Trước khi cấp runner, bước prepare đối chiếu source SHA với yêu cầu đã khóa để chặn việc nhánh main thay đổi giữa lúc gửi và nhận bài.

Job ID cố định và thao tác claim trên catalog ngăn gửi trùng khi controller chạy lại hoặc mất phản hồi dispatch. Workflow chỉ nối tiếp đợt đã chỉ định; không phải lịch chạy định kỳ. Có thể chạy thủ công controller để kiểm tra trạng thái: khi nguồn còn chạy, nó chỉ trả `waiting_for_source` và không tạo solver mới.

## Lưu trạng thái restart

Các runner 8 ms đang chạy đã nạp mã trước thay đổi này. Không thể bổ sung bước lưu restart vào tiến trình đang chạy; vì vậy hai ca 12 ms được tính lại từ đầu.

Từ phiên bản này, worker nghiên cứu chỉ niêm phong restart sau khi solver và hậu xử lý đóng tệp, có bằng chứng solver hoàn tất đúng thời gian yêu cầu. Phải có đủ các họ `.abq`, `.mdl`, `.pac`, `.stt`, `.prt`, `.res`, `.sel`, `.odb`, kể cả các tệp miền CPU như `.abq.1`. Receipt `attempts/NNN/restart-state.json` lưu input hash, phiên bản runtime, CPU, precision, provenance và checksum từng tệp.

Các tệp native được hard-link khi chuẩn bị xuất để tránh nhân đôi dung lượng lớn; bản lưu chia part và kiểm tra checksum như các kết quả khác. Nếu tệp bị thay đổi hoặc thiếu họ cần thiết thì không công bố manifest hoàn chỉnh. Đây là trạng thái ở cuối step, không phải cam kết khôi phục từ mọi thời điểm giữa step. Lần restart sau phải dùng runtime/CPU tương thích và đọc đúng trạng thái, không khởi tạo lại biến dạng, vận tốc hay hư hỏng. Giữ được tệp chưa thay thế thử nghiệm restart bằng Abaqus trên chính ca đó.

## Báo cáo sau 12 ms

### Khôi phục ca chưa giải do giới hạn ổ đĩa

Lượt 12 ms đầu đã chặn S5 trước khi giải: ngân sách full-export yêu cầu khoảng 125,56 GB, runner còn 97,7 GiB (khoảng 104,9 GB). ODB S5 8 ms được xác minh trong manifest hoàn chỉnh có kích thước 16,519 GB, tổng bản lưu 16,656 GB. Không có thay đổi vật lý nào để xử lý lỗi tài nguyên.

Worker native research được bật riêng chính sách `research-hardlinks`: hai lần dung lượng ODB dự đoán (gồm một ODB làm biên dự phòng), ngân sách trạng thái native và một part truyền tối đa 1 GiB. Vẫn giữ thêm 20 GB dự phòng của batch, kiểm tra CPU/RAM và theo dõi ổ trống trong khi chạy. Các chế độ thông thường/full-export giữ nguyên chính sách cũ; không thay lưới, vật liệu, thời lượng hay ngưỡng chất lượng. Cả hai cửa kiểm tra tài nguyên của Engine dùng cùng chính sách.

Sau khi workflow 12 ms hiện tại kết thúc, controller được phép phục hồi tối đa một lần, chỉ đối với shard `blocked_environment` có lỗi admission CPU/RAM/disk và chưa có kết quả solver. Ca B0249 đã có kết quả hợp lệ và archive/restart xác minh được giữ nguyên. Không dùng cơ chế này để chạy lại lỗi solver, lỗi upload, kết quả dở dang hoặc dữ liệu kém chất lượng. Lịch sử workflow/SHA cũ được giữ, source mới phải qua kiểm tra sáu mô-đun vật lý, và input hash không đổi. Không sửa ownership của batch khi B0249 còn đang chạy.

Sau khi lượt 12 ms hoàn tất, cùng controller kiểm tra đúng catalog và source SHA rồi xuất `duration-comparison.json`, `.csv`, `.md` trong artifact `duration-followup-receipt`. Báo cáo cũng được lưu vào catalog của lượt 12 ms.

Báo cáo so sánh SEA, độ võng mặt đáy, xóa phần tử, lực/vận tốc cuối và chỉ tiêu chất lượng ở 8/12 ms. Ngưỡng chênh lệch 2% là tiêu chí dự án. Không kết luận 8 ms đủ chỉ vì SEA gần nhau nếu kiểm tra kết thúc sự kiện chưa đạt; cũng không mặc định 12 ms đủ nếu `event_finished` còn false. Hai ca kiểm chứng không chứng minh hội tụ thời lượng cho toàn bộ miền thiết kế và không thay thế thực nghiệm.

Tham khảo: [Abaqus — Restarting an Analysis](https://docs.software.vt.edu/abaqusv2026/English/SIMACAEANLRefMap/simaanl-c-restart.htm), [GitHub — workflow_run](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).
