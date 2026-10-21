# Từ điển dữ liệu

## Cấp lưu trữ

`projects/<project-id>/batches/<batch-id>` chứa batch.json, run-index CSV/Parquet và reports. `runs/<run-id>` chứa requested-input.json, resolved-input.json, run.json và attempts/001…; mỗi attempt có raw, extracted, figures, reports, logs và artifact-manifest.json.

- `raw`: CAE, INP, ODB, datacheck, file solver và model_manifest.
- `extracted/inventory.json`: steps, frame, tên/component/position/invariant của field, số bản ghi, instance, mesh sets và sections.
- `extracted/fields/<step>/<field>/frame=NNNNN/part-*.parquet`: dữ liệu trường theo khối.
- `extracted/mesh/<instance>/nodes|elements`: tọa độ và topology gốc.
- `histories.json`, `all_histories.csv/parquet`: toàn bộ history gốc, không đồng bộ lại mốc thời gian.
- `impact_history.csv/parquet`: bảng dẫn xuất theo mốc A3 của RP, các history khác nội suy tuyến tính để đối chiếu.
- `summary.json`, `quality.json`, `export-verification.json`: chỉ số, chất lượng và đối chiếu số dòng.
- `figures/render-manifest.json`: frame, thời gian, biến, view và hệ số biến dạng của ảnh.

## Field Parquet

Metadata schema `honeycomb` chứa field name gốc, descriptions, components theo đúng thứ tự, step/frame/time_s, instance index mapping, section-point descriptions, start_row và định nghĩa cơ sở tọa độ.

| Cột | Ý nghĩa |
|---|---|
| instance_index | Index trong metadata.instances; -1 là assembly/không gắn instance |
| node_label / element_label | Nhãn gốc trong instance; không phải chỉ số toàn mô hình |
| integration_point | Số điểm tích phân, -1 nếu không áp dụng |
| section_point | Điểm qua chiều dày shell, -1 nếu không áp dụng |
| position | NODAL, INTEGRATION_POINT… |
| data | Vector/tensor/scalar theo componentLabels gốc |
| conjugate_data | Thành phần phức nếu có; NaN/null khi không có |
| local_quaternion | Quaternion gốc từ ODB bulk access; không tự diễn giải thành basis với quy ước khác |
| local_basis | Cơ sở 3×3 theo thứ tự hàng từ FieldValue fallback; không có thì NaN/null |
| mises | Invariant von Mises của S nếu được ODB cung cấp |

Không tự lấy trung bình qua section point hoặc biến tensor thành invariant để thay bản gốc. Giá trị stress/strain giữ hệ tọa độ output của ODB; chỉ chuyển hệ khi người phân tích thực hiện rõ ràng.

Node mesh: label, x/y/z (mm). Element mesh: label, element_type và connectivity JSON list các node label gốc. Sets/section assignments giữ ánh xạ vùng; local instance labels phải được dùng cùng instance.

## Chỉ số

| Chỉ số | Đơn vị / định nghĩa |
|---|---|
| initial_kinetic_energy_J | ALLKE[0]/1000 |
| peak_raw_contact_force_N | max m_tonne×(A3+g_mm_s²), đầu va đập rigid dẫn hướng Z |
| peak_force_time_ms | Thời điểm lực đỉnh trên history gốc |
| max_impactor_displacement_mm | max(-RP.U3), có bao gồm rơi qua khe hở |
| max_indentation_from_contact_mm | Hành trình viên đặt lại mốc tại lần đầu F>10 N |
| max_top/bottom_centre_downward_mm | max(-U3) của nút gần tâm va đập được chọn khi dựng |
| contact_duration_ms | Khoảng lần đầu tới lần cuối F>10 N; ngưỡng được công bố |
| plastic_dissipation_J | ALLPD cuối step /1000 |
| physical_dissipation_J | ALLPD + các thành phần ALLFD/ALLDMD/ALLCD có ghi; không gộp ALLAE/bulk viscosity |
| transferred_energy_at_last_contact_J | K0 − K(t) + công trọng lực lên viên; không đồng nhất với tiêu tán |
| panel_mass_kg | Khối lượng hai mặt và lõi hữu hạn, không bao gồm đầu rơi |
| SEA_J_kg | Tiêu tán vật lý / khối lượng sandwich |
| energy drift | max abs(ETOTAL−ETOTAL[0])/K0 ×100% |
| artificial energy ratio | max abs(ALLAE)/max ALLIE ×100% |

Field extrema lưu cả value, step, frame, time, instance, label, integration/section point. Mất output không được thay bằng 0.

## Dataset ML

`samples-full.csv`: toàn bộ input scalar và các chỉ số/provenance. `samples.csv/parquet`: cột được chọn. `data-dictionary.json`, `dataset.json` mô tả seed, grouping, split, source runs và quy tắc resample. `curves/<run-id>` giữ original histories, resolved input và resampled.parquet riêng.

physical design ID giữ hình học và vật liệu; thay tải, lưới hoặc attempt không tạo nhóm vật lý mới. Mặc định split theo thiết kế 70/15/15; với ít thiết kế, một số split có thể trống. Không tự lấp bằng cách chia các đường cong của cùng thiết kế qua nhiều tập.

Giữ cờ `physical_validation=not_established` khi huấn luyện trên mô hình chưa kiểm chứng. Không gọi đó là dữ liệu thí nghiệm.
