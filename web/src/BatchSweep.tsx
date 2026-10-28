type Doc = Record<string, any>;

export default function BatchSweep({spec, parameters, update}: {
    spec: Doc; parameters: Doc[]; update: (changes: Doc) => void;
}) {
    const axes: Doc[] = spec.axes ?? [];
    let count: number | null = 1;
    for (const axis of axes) {
        const {start, stop, step} = axis;
        if (axis.values) count *= new Set(axis.values).size;
        else if (![start, stop, step].every(v => typeof v === "number" && Number.isFinite(v)) || step <= 0 || stop < start) {
            count = null; break;
        } else {
            const quotient = (stop - start) / step;
            const aligned = Math.abs(quotient - Math.round(quotient)) < 1e-9;
            count *= Math.floor(quotient + 1e-9) + 1 + (axis.include_stop && !aligned ? 1 : 0);
        }
    }
    const patchAxis = (index: number, patch: Doc) => update({axes: axes.map((axis, i) => i === index ? {...axis, ...patch} : axis)});
    const addAxis = () => {
        const preferred = ["reentrant_delta_deg", "energy_J", "velocity_m_s", "reentrant_cell_height", "core_height"];
        const available = parameters.filter(p => !axes.some(axis => axis.parameter === p.key));
        const parameter = preferred.map(key => available.find(p => p.key === key)).find(Boolean) ?? available[0];
        if (!parameter) return;
        const initial = typeof parameter.default === "number" ? parameter.default : 1;
        update({sampling: "grid", designs: [], axes: [...axes, {parameter: parameter.key, start: initial, stop: initial, step: 1, include_stop: false}]});
    };
    return <section className="parameter-group batch-sweep" aria-labelledby="batch-sweep-title">
        <h3 id="batch-sweep-title">Chạy đồng loạt theo khoảng</h3>
        <p className="hint">Thêm một hoặc nhiều tham số. Mỗi tổ hợp tạo một lượt riêng, giữ input và kết quả riêng.
            Các điểm đúng bước luôn được tính; có thể thêm điểm cuối khi khoảng không chia hết cho bước.</p>
        {spec.sampling !== "grid" ? <p>Đang dùng bảng thiết kế hoặc LHS từ JSON.
            <button type="button" onClick={() => update({sampling: "grid", designs: [], axes: []})}>Chuyển sang khoảng và bước</button></p> : <>
            {axes.map((axis, index) => <fieldset className="sweep-axis" key={index}>
                <legend>Tham số {index + 1}</legend>
                <label className="field sweep-parameter"><span>Tham số và đơn vị</span>
                    <select value={axis.parameter} onChange={e => {
                        const parameter = parameters.find(p => p.key === e.target.value);
                        const initial = typeof parameter?.default === "number" ? parameter.default : 1;
                        patchAxis(index, {parameter: e.target.value, start: initial, stop: initial, step: 1, values: null});
                    }}>
                        {!parameters.some(p => p.key === axis.parameter) && <option value={axis.parameter}>{axis.parameter} · không áp dụng</option>}
                        {parameters.map(p => <option key={p.key} value={p.key} disabled={axes.some((a, i) => i !== index && a.parameter === p.key)}>{p.title}{p.unit ? ` (${p.unit})` : ""}</option>)}
                    </select>
                </label>
                {([['start','Đầu'],['stop','Cuối'],['step','Bước nhảy']] as const).map(([key, label]) =>
                    <label className="field" key={key}><span>{label}</span>
                        <input type="number" step="any" value={axis[key] ?? ""} disabled={!!axis.values}
                            onChange={e => patchAxis(index, {[key]: e.target.value === "" ? undefined : Number(e.target.value)})} />
                    </label>)}
                <button type="button" aria-label={`Bỏ tham số ${index + 1}`} onClick={() => update({axes: axes.filter((_, i) => i !== index)})}>Bỏ</button>
                <label className="sweep-end"><input type="checkbox" checked={!!axis.include_stop}
                    onChange={e => patchAxis(index, {include_stop: e.target.checked})} />Thêm điểm cuối nếu lệch bước</label>
                {axis.values && <p>Đang dùng danh sách từ JSON: {JSON.stringify(axis.values)}.
                    <button type="button" onClick={() => patchAxis(index, {values: null})}>Nhập theo khoảng</button></p>}
            </fieldset>)}
            <button type="button" onClick={addAxis} disabled={axes.length >= parameters.length}>Thêm tham số khảo sát</button>
            <p className="measure" role="status">{axes.length ? `${axes.length} tham số · ${count === null ? "Khoảng chưa hợp lệ" : `${count.toLocaleString("vi-VN")} tổ hợp dự kiến`}` : "Một lượt với thông số hiện tại."}
                {count !== null && count > 20 && " Vượt giới hạn cloud 20 lượt/batch. Giảm khoảng, tăng bước hoặc tải input để chạy trên máy đủ tài nguyên."}</p>
        </>}
        <div className="fields">
            <label className="field"><span>Cách thực thi</span><select value={spec.execution_mode ?? "sequential"}
                onChange={e => update({execution_mode: e.target.value})}>
                <option value="sequential">Tuần tự · một lượt mỗi lần</option>
                <option value="parallel">Đồng thời · mỗi lượt một runner riêng</option>
            </select></label>
            {spec.execution_mode === "parallel" && <label className="field"><span>Số lượt đồng thời tối đa</span>
                <input type="number" min={1} max={20} step={1} value={spec.max_parallel_runs ?? 2}
                    onChange={e => update({max_parallel_runs: Number(e.target.value)})} /></label>}
            <label className="field"><span>Dự trù RAM mỗi lượt <small>GiB</small></span>
                <input type="number" min={0.5} step={0.5} value={spec.ram_per_run_gb ?? 4}
                    onChange={e => update({ram_per_run_gb: Number(e.target.value)})} /></label>
        </div>
        <p className="hint">Mỗi lượt cloud chạy trong một GitHub job trên runner riêng có 4 CPU; mặc định solver dùng đủ 4 CPU.
            Hai lượt đồng thời dùng hai runner, tổng cộng 8 CPU. Quota GitHub và license có thể khiến job chờ.
            Worker kiểm tra RAM/đĩa riêng trên từng runner.
            Dự trù tài nguyên và thời gian là ước tính, không tự thay đổi lưới hoặc thời gian vật lý.</p>
    </section>;
}
