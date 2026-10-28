# Honeycomb Abaqus Studio

Ứng dụng Windows **WinUI 3 + Python** để tự động hóa khảo sát va đập tấm sandwich honeycomb bằng **Abaqus/Explicit 2017**, tạo dữ liệu có thể truy vết và báo cáo nghiên cứu.

**Tiến độ cloud:** repo đã public, runner Ubuntu đã được đo thực tế (145,19 GiB tổng, 85,64 GiB trống), engine đã qua CI Linux. Abaqus Linux/license và backend mô phỏng đầy đủ chưa được nghiệm thu. Xem [bằng chứng và các điều kiện còn chặn](docs/CLOUD_STATUS.md).

Mô hình nền tái dựng theo Foo, Seah & Chai, *Composite Structures* 85 (2008), DOI [10.1016/j.compstruct.2007.10.016](https://doi.org/10.1016/j.compstruct.2007.10.016). Mô hình không tự nhận là đã hội tụ hoặc tương đương thí nghiệm.

## Bản Windows x64

[Tải bản 0.2.0 preview](https://github.com/xuankhanh24/honeycomb-abaqus-studio/releases/tag/v0.2.0-preview). Giải nén đầy đủ vào đường dẫn ASCII, ví dụ `C:/HoneycombStudio`, rồi mở `HoneycombStudio.exe`. Bản này có .NET/WinAppSDK và Python riêng; Abaqus/license dùng bản đã cài trên máy. Không chạy exe tách khỏi các DLL/runtime đi kèm.

Xem [kết quả nghiệm thu](docs/VALIDATION_RESULTS.md) để phân biệt các kiểm thử đã đạt với kiểm tra hội tụ, gián đoạn Abaqus thật và reboot chưa hoàn tất. Drive thật đã được kiểm tra upload, tiếp tục và khôi phục. Đây là bản nghiên cứu nội bộ chưa ký mã.

## Dữ liệu gọn từ bản 0.2.0

Nút **Dữ liệu ML gọn** xuất `samples.csv/Parquet` (mỗi lượt một dòng), đường cong và từ điển cột. Mặc định không nhân bản dữ liệu trường của ODB. PDF mỗi lượt 5 trang tiếng Việt; bảng dẻo và thống kê nút/phần tử nằm ngoài PDF. CSV nút/phần tử là chức năng nâng cao có thể tạo hàng chục GB, không cần cho mô hình ML dạng bảng.

## Cloud: chạy đồng thời và dữ liệu tổng hợp

**Mỗi lần bấm chạy tạo một job cha, một workflow và một thư mục dữ liệu chung**, chứa các lượt đồng thời. Trên web có nút **Mở thư mục dữ liệu job**, theo dõi Actions, tải ZIP nhỏ và gói đầy đủ ODB/CAE/INP. Có bảng **mọi kết quả đã mô phỏng** và bảng huấn luyện chỉ gồm mẫu đạt chất lượng. Xem [hướng dẫn thư mục, X/y và sửa mẫu chưa đạt](docs/ML_DATA_WORKFLOW.md).

Web cho phép **20 lượt mỗi batch, tối đa 20 runner đồng thời**, mỗi runner giải một lượt.
Giới hạn 8 trước đây do ứng dụng tự đặt; giới hạn batch 10 cũng đã được nâng lên 20.
[GitHub Free cho phép 20 job đồng thời trên runner tiêu chuẩn](https://docs.github.com/en/actions/reference/limits#job-concurrency-limits-for-github-hosted-runners).
Quota này dùng chung với các workflow khác của tài khoản. License Abaqus, CPU/RAM/đĩa và thời gian cài đặt vẫn quyết định khả năng chạy thực tế.
Chọn **Đồng thời** và nhập số runner mong muốn ở web. Các batch mô phỏng được xếp theo nhóm workflow dùng chung; 20 là mức tối đa bên trong một batch, không phải 20 batch chạy cùng lúc.
Trên máy cá nhân, worker vẫn kiểm tra tài nguyên trước khi nhận lượt.

### Đầu vào và đầu ra là gì?

| Giai đoạn | Đầu vào | Đầu ra |
| --- | --- | --- |
| Mô phỏng Abaqus | Hình học: panel, skin, core_height, foil, cell_size… (mm); vật liệu; ngàm; năng lượng (J) hoặc vận tốc (m/s); lưới; thời gian (s) | Kết quả lực (N), chuyển vị (mm), năng lượng (J), ứng suất (MPa), đường cong theo thời gian; trạng thái và kiểm tra chất lượng |
| Huấn luyện dạng bảng | **X**: đúng các cột `input.*` trong `dataset.json.features`, gồm hình học, tải, ngàm và tham số vật liệu được chọn | **y**: chọn một hoặc nhiều cột trong `dataset.json.targets` theo bài toán; ví dụ lực cực đại, chuyển vị cực đại hoặc SEA |

Ví dụ mục tiêu dự đoán:

| Tên cột giữ nguyên trong dữ liệu | Ý nghĩa | Đơn vị |
| --- | --- | --- |
| `peak_raw_contact_force_N` | Lực tiếp xúc cực đại từ các mẫu đã ghi | N |
| `max_top_centre_downward_mm` | Chuyển vị xuống cực đại tại tâm tấm mặt trên | mm |
| `physical_dissipation_J` | Năng lượng tiêu tán vật lý theo các kênh năng lượng đã ghi | J |
| `SEA_J_kg` | Năng lượng tiêu tán vật lý chia cho khối lượng tấm sandwich | J/kg |
| `mises_max_MPa` | Ứng suất von Mises cực đại trong các frame đã ghi | MPa |

`run_id`, `batch_id`, `design_id`, `input_hash`, `split`, số attempt và thông tin chất lượng dùng **truy vết/chia tập**, không đưa vào X.
Các chỉ số sai số/năng lượng nhân tạo dùng sàng lọc chất lượng; chọn y vật lý phù hợp thay vì dùng tất cả cột một cách máy móc.
Lưới, CPU và thời gian mô phỏng được lưu trong `resolved.json` để kiểm tra; không phải mọi tham số mô phỏng đều được chọn làm X mặc định.
Biến phân loại cần mã hóa, ô trống/null là giá trị thiếu, không tự thay bằng 0.

### Lấy file chung ở đâu?

Trên **web → Dữ liệu → Dữ liệu huấn luyện tổng hợp** có nút tải CSV, Parquet, ZIP, tổng hợp lại và theo dõi Actions.
Mỗi batch cloud kết thúc sẽ tự chạy tổng hợp từ các job đã có bản lưu hoàn tất; cũng có thể chạy riêng workflow [Tổng hợp dữ liệu huấn luyện](https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/workflows/collect-training.yml).
Bản tổng hợp được phát hành dưới tag `training-<workflow-id>-<attempt>`, giữ lịch sử từng phiên bản và SHA-256.
Không cần bật Abaqus hoặc license để chỉ tổng hợp dữ liệu đã lưu.

```text
honeycomb-training-<workflow-id>-<attempt>/
├── README.md                         # Hướng dẫn đọc bộ dữ liệu
├── collection.json                   # Số mẫu, số lượt, thời điểm tổng hợp
├── 01_training/
│   ├── samples.csv                   # FILE HUẤN LUYỆN CHUNG: mỗi dòng một mẫu đạt
│   ├── samples.parquet               # Cùng bảng, định dạng có kiểu cho Python
│   ├── dataset.json                  # Danh sách X/y, số mẫu và chia tập
│   ├── readiness.json                # Thiếu đầu vào/đầu ra, số mẫu và độ phủ chia tập
│   ├── data-dictionary.csv/json      # Tên cột, tiếng Việt, đơn vị, vai trò
│   ├── FIELD_DESCRIPTIONS.md
│   ├── curves/<run-id>/              # Đường cong của mẫu được chọn, nếu có
│   └── provenance/<run-id>/          # Đầu vào, kết quả, chất lượng của mẫu
├── 02_audit/
│   ├── source-jobs.json              # Tên bài, ID, link release, checksum nguồn
│   ├── run-selection.csv             # Nhận/loại từng lượt và lý do
│   └── input-output-contract.json    # X, y ứng viên và cột chỉ để truy vết
├── 03_simulations/
│   └── job--<ten-bai-khong-dau>--<id12>/run-0001--delta-20deg--energy-7J--<run-id>/
│       ├── input/requested.json      # Đầu vào người dùng yêu cầu
│       ├── input/resolved.json       # Đầu vào thực tế sau xử lý
│       └── output/
│           ├── summary.json          # Chỉ số kết quả
│           ├── quality.json          # Kiểm tra chất lượng
│           └── attempt-001/          # Đường cong theo thời gian, nếu có
├── 05_all_results/
│   └── simulation-results.csv/parquet # Mọi lượt, kể cả review/smoke, có lý do nhận/loại
└── artifact-manifest.json            # Danh sách tệp và SHA-256
```

Tên thư mục chứa tên bài không dấu và ID; từng lượt có số thứ tự, góc và năng lượng để đối chiếu. Tên bài gốc nằm trong `source-jobs.json`.
Mỗi job còn có gói dữ liệu đầy đủ riêng: `04_solver_archive` giữ ODB/CAE/INP, log và báo cáo gốc. Trên web mở **Thư mục dữ liệu job** để tải ZIP đầy đủ hoặc `download_full.py` khi gói được chia nhiều phần; checksum được kiểm tra khi tải. Thư mục solver đang chạy giữ nguyên.
Chỉ nhận lượt `completed`, `ml_eligible=true`, không phải `test_only`. Smoke/review/failed giữ hồ sơ nhưng không vào bảng huấn luyện.
Khử trùng `input_hash` trên toàn bộ job, chia train/validation/test theo `design_id` toàn cục; dùng cột `split` có sẵn để tránh rò rỉ dữ liệu.
Nếu chưa có mẫu đạt, `samples=0`, CSV chỉ có tiêu đề; không coi đó là bộ dữ liệu đã sẵn sàng huấn luyện.
Job chưa có bản lưu hoàn tất được ghi lý do trong `source-jobs.json`; lỗi checksum hoặc thiếu nguồn đã xác nhận sẽ làm bước tổng hợp thất bại và giữ bản tổng hợp trước đó.

## Chức năng

- Chọn lõi lục giác hoặc **auxetic re-entrant hình 1 — 0°**; chỉnh kích thước ô lõm, dịch pha X/Z và lưới chiều sâu Y. Xem [kiểm tra tích hợp](docs/AUXETIC_0_VALIDATION.md).
- Xem/sửa hình học, bảng vật liệu, điều kiện tải, liên kết, lưới và output; preview input thực tế và toàn bộ lượt trước khi chạy.
- Quét năng lượng/vận tốc với bước nhảy, tổ hợp nhiều biến, Latin Hypercube có seed hoặc bảng CSV.
- Thực thi tuần tự hoặc đồng thời có kiểm tra tài nguyên; cloud hỗ trợ tối đa 20 runner trong một batch; tiến độ vật lý, ETA, log, CPU/RAM và datacheck.
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

## Bật cấp license cho GitHub Actions bằng CMD

GitHub Actions kết nối qua **Tailscale** tới dịch vụ **SIMULIA FlexNet Server** trên máy chủ dự án để xin license. Máy này phải bật, có Internet và không Sleep/Hibernate trong suốt lượt mô phỏng. Không cần mở Abaqus hoặc upload key mỗi lần chạy.

Trên máy Windows đang giữ license, tìm **CMD** trong Start → chọn **Run as administrator**, rồi chạy:

```cmd
sc config "SIMULIA FlexNet Server" start= auto
net start "SIMULIA FlexNet Server"
net start Tailscale
"C:\Program Files\Tailscale\tailscale.exe" up
```

Nếu Tailscale hiện đường dẫn đăng nhập, mở đường dẫn đó và đăng nhập tài khoản đã cấu hình cho dự án. Nếu báo dịch vụ đã chạy rồi thì không cần khởi động lại.

Kiểm tra dịch vụ và kết nối:

```cmd
sc query "SIMULIA FlexNet Server"
sc query Tailscale
"C:\Program Files\Tailscale\tailscale.exe" status
```

Hai dịch vụ cần hiện **RUNNING**; Tailscale cần kết nối, không báo đang đăng xuất hoặc đã dừng. Đây là kiểm tra dịch vụ/mạng; Actions sẽ kiểm tra kết nối và khả năng lấy license thực tế khi chạy.

Để máy không tự ngủ hoặc tự Hibernate **khi cắm điện**, chạy:

```cmd
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

Các lệnh trên thay đổi thiết lập nguồn hiện tại; không thay đổi hành vi khi gập nắp laptop. Giữ máy cắm nguồn và không gập nắp nếu thao tác đó làm máy ngủ. Sau khi mô phỏng kết thúc, có thể đặt lại thời gian trong **Settings → System → Power & battery**.

Sau đó mở [web quản lý](https://honeycomb-abaqus-studio.vercel.app) → đăng nhập **Chủ dự án** → **Công việc** → **Chọn bài đã lưu** → **Chạy mô phỏng**. Bấm **Theo dõi trên GitHub Actions** để xem log. Không đưa file license, key hoặc mật khẩu vào repo hay log công khai.

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

## Public web preview

[Open Honeycomb Studio](https://honeycomb-abaqus-studio.vercel.app) to inspect inputs, geometry and genuine Windows circular-clamp reference curves. Owner login and private runner connectivity are verified. The licensed Ubuntu solver remains blocked pending authorized Linux media and native qualification. See [measured cloud status](docs/CLOUD_STATUS.md) and [deployment settings and remaining acceptance](docs/CLOUD_WEB.md).
