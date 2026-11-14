# Nâng cấp surrogate và kiểm chứng độc lập — 14/11/2026

Tác giả đồ án: **Lưu Xuân Khánh**. Phạm vi là độ tin cậy của dự báo SEA lõi
và sàng lọc không xóa phần tử mặt sau; không công nhận an toàn thực nghiệm.

## Những thay đổi đã chạy

- Xác minh hash ZIP nguồn, từng thành viên, 489 hình học duy nhất, vai trò
  411 development/78 test lịch sử, requested/resolved, đơn vị và công thức SEA.
- Thêm S1–S5 đã chạy thật thành năm quan sát phát triển tuần tự; nhóm chúng
  chung fold khi tinh chỉnh và hiệu chỉnh xác suất. Không dùng lại chúng làm test.
- So 14 cấu hình v5 và 20 cấu hình v6 trong nested CV 5×3. Scaler, biến đổi y,
  siêu tham số và lựa chọn mô hình nằm trong fold huấn luyện tương ứng.
- V6 thêm hồi quy năng lượng rồi chia khối lượng tính từ hình học. Khối lượng
  này khớp 494 quan sát tới sai số làm tròn (max tương đối dưới 1e-14); không dùng
  khối lượng ODB làm đặc trưng dự báo.
- Giữ riêng fitting/calibration/qualification theo giao thức; 78 test vẫn là
  test lịch sử đã lộ. Qualification v6 là đánh giá hồi cứu sau v5, không phải test mù.
- Khóa mô hình trước khi mở qualification. Khoảng residual conformal có kiểm tra
  độ bao phủ và điều kiện áp dụng; không bảo đảm riêng cho điểm do tối ưu chọn.
- Loại hình học không hợp lệ, ngoài miền hỗ trợ và lân cận quan sát đã vi phạm.
  Nếu không chứng minh được tỷ lệ vi phạm theo ngưỡng đã đặt, policy từ chối
  công nhận an toàn, thay vì tự nới ngưỡng hoặc gọi xác suất thấp là bảo đảm.

## Kết quả và giới hạn

| Đánh giá | v5 | v6 |
|---|---:|---:|
| Nested OOF MAE, J/kg, cùng 411 ID/fold | 38,047 | 32,933 |
| Nested OOF RMSE, J/kg | 51,480 | 47,118 |
| Nested OOF R² | 0,92657 | 0,93849 |
| Qualification nội bộ MAE, J/kg | 36,971 | 32,217 |
| Qualification MAPE, % | 4,976 | 3,993 |
| Qualification bao phủ khoảng 95%, % | 90,36 | 95,18 |

MAE OOF giảm **13,44%** trong so sánh v5–v6 cùng giao thức. Tuy vậy, sai số tuyệt
đối lớn nhất tăng từ khoảng **184,32 lên 236,75 J/kg**. Không được bỏ điểm này
khỏi báo cáo hoặc gọi bản mới tốt hơn ở mọi thiết kế. So sánh trực tiếp với
MAE v4.1 37,251 J/kg phải ghi khác seed và tiêu chí chọn mô hình.

Kiểm tra bổ sung leave-one-geometry-cluster-out: chia 411 hình học thành năm
vùng bằng KMeans trên X chuẩn hóa theo biên (không dùng nhãn). Giữ họ mô hình
đã chọn, fit lại và dự báo từng vùng bị bỏ ra. Đây là stress test hồi cứu, không
phải một vòng chọn mô hình mới. MAE gộp **36,782 J/kg**, RMSE **53,737 J/kg**;
MAE từng vùng khoảng **22,71–51,12 J/kg**. Ngưỡng xác suất 0,10 dùng chẩn đoán
cho lọt **3/55** ca được nhận dù có thêm miền hỗ trợ. Điều này củng cố quyết định
giữ policy chính ở trạng thái chưa đủ bằng chứng; không biến ngưỡng 0,10 thành
bảo đảm an toàn. Không gọi đây là kiểm chứng mù hoặc tỷ lệ lỗi đã được chứng nhận.

V6 chưa đạt mục tiêu MAE <=20 J/kg, MAPE <=2%, APE q95 <=5% và chưa có đủ bằng
chứng rủi ro mặt sau <=5%. Threshold được chọn là `null`: không có thiết kế được
policy chứng nhận. Sáu đề xuất là điểm thu thập FEA, không phải sáu nghiệm tối ưu
khả thi. S5 vẫn có sai số lớn trong chẩn đoán fitting; sửa khối lượng không giải
quyết hết độ phức tạp biến dạng/hư hỏng.

Chưa có dữ liệu thực nghiệm để hiệu chuẩn vật liệu/hư hỏng; chưa xác nhận hội tụ
lưới hoặc toàn sự kiện. Chỉ 4/489 mẫu nguồn có cờ kết thúc sự kiện và 0 mẫu đủ
điều kiện ML toàn sự kiện. Mọi cờ gốc được giữ nguyên. Các giới hạn này không
thể biến thành đạt chỉ bằng điều chỉnh mô hình học máy.

## Kiểm chứng tiếp theo trên Actions

`reliability-study.json` khóa sáu tọa độ V6-01…V6-06, dự báo, khoảng dự báo,
hash mô hình/protocol và các mô-đun vật lý. Controller chỉ gửi **một batch sáu ca**
sau khi lượt 12-ms B0249/S5 hiện hữu và lần phục hồi tài nguyên của nó đã hoàn
tất có archive/restart hợp lệ. Không sửa ownership hoặc hủy B0249 đang chạy.

Mỗi ca mới chạy tới 12 ms bằng Abaqus 2020 trên Actions, 4 CPU double, giữ lưới,
vật liệu, tải và cadence output. `horizon-8ms.json` giữ riêng năng lượng, SEA,
damage và kết thúc sự kiện tại 8 ms bằng mẫu native có provenance/checksum.
Kết quả 12 ms báo riêng; không trộn nhãn huấn luyện. Trích subwindow đã thử
với dữ liệu native S5 8 ms (lấy 4 ms), xác minh checksum từ Releases; phép thực
8-ms-from-12-ms trên batch mới còn chờ.

Claim bền vững ngăn POST trùng khi controller chạy lại hoặc mất phản hồi. Lỗi
solver/upload/quality không được tự tính lại; giữ kết quả để xem xét. Khi đủ
kết quả, controller tính MAE, MAPE, APE q95, độ bao phủ khoảng và số ca mặt sau
còn nguyên, rồi lưu vào artifact/catalog. Kết quả thất bại không tự kích hoạt
tinh chỉnh theo test hoặc hạ điều kiện nghiệm thu.

## Sản phẩm cục bộ

- `C:/UET/DO_AN/outputs/ml-reliability-v5-20261114`: nghiên cứu đầu, kết quả âm
  được giữ nguyên, đã kiểm độc lập metrics/ID/hash.
- `C:/UET/DO_AN/outputs/ml-reliability-v6-1-physics-20261114`: bản mới đầy đủ,
  có README, báo cáo, mô hình, dự báo OOF, split ID, snapshot mã, dữ liệu và hash.
- `C:/UET/DO_AN/outputs/reliability-review-20261114`: hình so sánh và biên bản
  native/preflight. Bản v6 không có “-1” là lượt trung gian đã đánh dấu dừng.

Đồ án cũ và mô hình v4.1 không bị ghi đè; chưa viết kết luận mới chưa được FEA xác nhận.
