import { useEffect, useMemo, useRef, useState } from "react";
import { verifiedFieldData, elementValue } from "./field-data";
import type { Field, FieldData, Vector } from "./field-data";

const fields: Record<Field, [string, string]> = {
    u3: ["Chuyển vị U3", "mm"],
    umag: ["Độ lớn chuyển vị |U|", "mm"],
    mises: ["Ứng suất von Mises · cực đại phần tử", "MPa"],
    peeq: ["PEEQ · cực đại phần tử", "1"],
};
const palette = [
    [36, 55, 111],
    [40, 116, 166],
    [67, 174, 189],
    [234, 201, 99],
    [194, 103, 33],
];
function color(value: number, min: number, max: number) {
    const t =
        max === min
            ? 0.5
            : Math.max(0, Math.min(1, (value - min) / (max - min)));
    const x = t * 4,
        i = Math.min(3, Math.floor(x)),
        f = x - i;
    return `rgb(${palette[i].map((v, c) => Math.round(v * (1 - f) + palette[i + 1][c] * f)).join(",")})`;
}
function project(p: number[], plane: string): Vector {
    if (plane === "XY") return [p[0], -p[1], p[2]];
    if (plane === "XZ") return [p[0], -p[2], -p[1]];
    if (plane === "YZ") return [p[1], -p[2], p[0]];
    return [
        0.8 * p[0] - 0.6 * p[1],
        0.32 * (p[0] + p[1]) - p[2],
        p[0] + p[1] + p[2] * 0.3,
    ];
}
const format = (v: number | null) =>
    v === null
        ? "Không ghi"
        : v.toLocaleString("vi-VN", { maximumSignificantDigits: 5 });

export default function FieldView({
    src,
    sha256,
}: {
    src?: string;
    sha256?: string;
}) {
    const [data, setData] = useState<FieldData | null>(null),
        [error, setError] = useState(""),
        [loading, setLoading] = useState(false),
        [frame, setFrame] = useState(0),
        [instance, setInstance] = useState("all"),
        [field, setField] = useState<Field>("u3"),
        [plane, setPlane] = useState("ISO"),
        [scale, setScale] = useState(1),
        [playing, setPlaying] = useState(false);
    const canvas = useRef<HTMLCanvasElement>(null),
        sequence = useRef(0);
    function accept(d: FieldData) {
        setData(d);
        setFrame(0);
        setPlaying(false);
        setInstance(
            String(
                Math.max(
                    0,
                    d.instances.findIndex((i) =>
                        i.name.toUpperCase().includes("CORE"),
                    ),
                ),
            ),
        );
    }
    useEffect(() => {
        const controller = new AbortController(),
            id = ++sequence.current;
        setData(null);
        setError("");
        setPlaying(false);
        setLoading(!!src);
        if (src)
            void (async () => {
                try {
                    const response = await fetch(src, {
                        signal: controller.signal,
                    });
                    if (!response.ok)
                        throw Error(
                            "Chưa tải được trường kết quả. Thử tải lại hoặc mở tệp JSON đã tải.",
                        );
                    if (
                        Number(response.headers.get("Content-Length")) >
                        16 * 1024 ** 2
                    )
                        throw Error("Tệp vượt giới hạn hiển thị 16 MiB.");
                    const d = await verifiedFieldData(
                        await response.arrayBuffer(),
                        sha256,
                    );
                    if (id === sequence.current) accept(d);
                } catch (e) {
                    if (id === sequence.current && !controller.signal.aborted)
                        setError(String(e));
                } finally {
                    if (id === sequence.current) setLoading(false);
                }
            })();
        return () => {
            controller.abort();
            sequence.current++;
        };
    }, [src, sha256]);
    useEffect(() => {
        if (!playing || !data) return;
        const timer = setInterval(
            () => setFrame((f) => (f + 1) % data.frames.length),
            250,
        );
        return () => clearInterval(timer);
    }, [playing, data]);
    const range = useMemo(() => {
        let min = Infinity,
            max = -Infinity,
            missing = 0;
        if (data)
            for (const f of data.frames)
                data.instances.forEach((m, i) => {
                    if (instance !== "all" && Number(instance) !== i) return;
                    m.elements.forEach((_, e) => {
                        const v = elementValue(m, f.instances[i], e, field);
                        if (v === null) missing++;
                        else {
                            min = Math.min(min, v);
                            max = Math.max(max, v);
                        }
                    });
                });
        return { min, max, missing, valid: Number.isFinite(min) };
    }, [data, field, instance]);
    const extrema = useMemo(() => {
        const rows: {
            instance: string;
            label: number;
            value: number;
            nodes: number[];
        }[] = [];
        if (data)
            data.instances.forEach((m, i) => {
                if (instance !== "all" && Number(instance) !== i) return;
                m.elements.forEach((e, j) => {
                    const value = elementValue(
                        m,
                        data.frames[frame].instances[i],
                        j,
                        field,
                    );
                    if (value !== null)
                        rows.push({
                            instance: m.name,
                            label: e.label,
                            value,
                            nodes: e.nodes.map((n) => m.node_labels[n]),
                        });
                });
            });
        return rows.sort((a, b) => b.value - a.value).slice(0, 5);
    }, [data, frame, instance, field]);
    useEffect(() => {
        const el = canvas.current;
        if (!el || !data) return;
        function draw() {
            const ctx = el!.getContext("2d");
            if (!ctx || !data) return;
            const width = el!.clientWidth,
                height = el!.clientHeight,
                dpr = window.devicePixelRatio || 1;
            el!.width = width * dpr;
            el!.height = height * dpr;
            ctx.scale(dpr, dpr);
            ctx.fillStyle = "#f4f6f8";
            ctx.fillRect(0, 0, width, height);
            const polygons: { points: Vector[]; value: number | null }[] = [];
            let xmin = Infinity,
                xmax = -Infinity,
                ymin = Infinity,
                ymax = -Infinity;
            data.instances.forEach((m, i) => {
                if (instance !== "all" && Number(instance) !== i) return;
                const f = data.frames[frame].instances[i];
                // Keep the viewport fixed across time, so deformation does not change zoom.
                for (const recorded of data.frames)
                    m.coordinates.forEach((p, n) => {
                        const u = recorded.instances[i].u[n];
                        const q = project(
                            p.map((v, k) => v + (u?.[k] ?? 0) * scale),
                            plane,
                        );
                        xmin = Math.min(xmin, q[0]);
                        xmax = Math.max(xmax, q[0]);
                        ymin = Math.min(ymin, q[1]);
                        ymax = Math.max(ymax, q[1]);
                    });
                m.elements.forEach((e, j) => {
                    if (e.nodes.some((n) => f.u[n] === null) && scale !== 0)
                        return;
                    polygons.push({
                        points: e.nodes.map((n) =>
                            project(
                                m.coordinates[n].map(
                                    (v, k) => v + (f.u[n]?.[k] ?? 0) * scale,
                                ),
                                plane,
                            ),
                        ),
                        value: elementValue(m, f, j, field),
                    });
                });
            });
            const zoom = Math.min(
                (width - 48) / Math.max(1, xmax - xmin),
                (height - 48) / Math.max(1, ymax - ymin),
            );
            polygons.sort(
                (a, b) =>
                    a.points.reduce((s, p) => s + p[2], 0) / a.points.length -
                    b.points.reduce((s, p) => s + p[2], 0) / b.points.length,
            );
            for (const p of polygons) {
                ctx.beginPath();
                p.points.forEach((v, n) => {
                    const x = (v[0] - (xmin + xmax) / 2) * zoom + width / 2,
                        y = (v[1] - (ymin + ymax) / 2) * zoom + height / 2;
                    if (n === 0) ctx.moveTo(x, y);
                    else ctx.lineTo(x, y);
                });
                ctx.closePath();
                ctx.fillStyle =
                    p.value === null
                        ? "#e1e5ea"
                        : color(p.value, range.min, range.max);
                ctx.fill();
                ctx.strokeStyle = "#566678";
                ctx.lineWidth = 0.3;
                ctx.stroke();
            }
        }
        draw();
        const observer = new ResizeObserver(draw);
        observer.observe(el);
        return () => observer.disconnect();
    }, [data, frame, field, instance, plane, scale, range]);
    return (
        <section
            className="parameter-group field-view"
            aria-label="Xem trường kết quả ODB"
        >
            <div className="sheet-title">
                <h3>Biến dạng và trường kết quả</h3>
                <label className="button field-file">
                    Mở JSON hiển thị
                    <input
                        type="file"
                        accept=".json,application/json"
                        onChange={async (e) => {
                            const file = e.target.files?.[0];
                            if (!file) return;
                            const id = ++sequence.current;
                            setData(null);
                            setError("");
                            setPlaying(false);
                            setLoading(true);
                            try {
                                if (file.size > 16 * 1024 ** 2)
                                    throw Error("Tệp vượt giới hạn 16 MiB.");
                                const d = await verifiedFieldData(
                                    await file.arrayBuffer(),
                                );
                                if (id === sequence.current) accept(d);
                            } catch (e) {
                                if (id === sequence.current)
                                    setError(String(e));
                            } finally {
                                if (id === sequence.current) setLoading(false);
                            }
                            e.target.value = "";
                        }}
                    />
                </label>
            </div>
            {loading && (
                <p role="status">Đang tải và kiểm tra dữ liệu hiển thị…</p>
            )}
            {error && (
                <p role="alert" className="field-error">
                    {error}
                </p>
            )}
            {!data && !loading && (
                <p className="hint">
                    Mở field-view.json từ bộ kết quả đã tải. Trình duyệt xử lý
                    tệp trên máy bạn.
                </p>
            )}
            {data && (
                <>
                    <p className="hint">
                        {String(data.source.platform ?? data.solver_release)} ·
                        ngàm{" "}
                        {data.source.clamp_mode === "circular"
                            ? "ngoài lỗ tròn"
                            : data.source.clamp_mode === "perimeter"
                              ? "bốn cạnh"
                              : "theo metadata"}{" "}
                        ·{" "}
                        {data.source.energy_J == null
                            ? ""
                            : `${data.source.energy_J} J · `}
                        {data.sampling.display_elements.toLocaleString("vi-VN")}{" "}
                        /{" "}
                        {data.sampling.original_shell_elements.toLocaleString(
                            "vi-VN",
                        )}{" "}
                        phần tử vỏ. Bản giảm mẫu để hiển thị; ODB và Parquet giữ
                        dữ liệu số đầy đủ.
                    </p>
                    <div className="field-controls">
                        <label className="field">
                            <span>Trường · đơn vị {fields[field][1]}</span>
                            <select
                                value={field}
                                onChange={(e) =>
                                    setField(e.target.value as Field)
                                }
                            >
                                {Object.entries(fields).map(([key, v]) => (
                                    <option value={key} key={key}>
                                        {v[0]}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="field">
                            <span>Instance</span>
                            <select
                                value={instance}
                                onChange={(e) => setInstance(e.target.value)}
                            >
                                <option value="all">
                                    Toàn bộ instance hiển thị
                                </option>
                                {data.instances.map((m, i) => (
                                    <option value={i} key={m.name}>
                                        {m.name}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="field">
                            <span>Mặt chiếu</span>
                            <select
                                value={plane}
                                onChange={(e) => setPlane(e.target.value)}
                            >
                                {["ISO", "XY", "XZ", "YZ"].map((p) => (
                                    <option key={p}>{p}</option>
                                ))}
                            </select>
                        </label>
                        <label className="field">
                            <span>Phóng đại biến dạng ×{scale}</span>
                            <input
                                type="number"
                                min="0"
                                max="20"
                                step="0.5"
                                value={scale}
                                onChange={(e) =>
                                    setScale(
                                        Math.max(
                                            0,
                                            Math.min(
                                                20,
                                                Number(e.target.value),
                                            ),
                                        ),
                                    )
                                }
                            />
                        </label>
                    </div>
                    <figure className="field-figure">
                        <canvas
                            ref={canvas}
                            role="img"
                            aria-label={`${fields[field][0]}, ${data.frames[frame].step}, frame ${data.frames[frame].frame}, ${(data.frames[frame].time_s * 1000).toFixed(3)} ms; bảng giá trị lớn nhất bên dưới`}
                        />
                        <figcaption>
                            Trục {plane === "ISO" ? "chiếu xiên XYZ" : plane} ·
                            tọa độ mm · ×{scale}.{" "}
                            {range.valid
                                ? `Thang màu cố định mọi frame: ${format(range.min)} đến ${format(range.max)} ${fields[field][1]}.`
                                : "Không có giá trị trường đã chọn."}{" "}
                            Màu xám: không ghi trường; bỏ hình biến dạng ở nút
                            thiếu U.
                        </figcaption>
                    </figure>
                    {range.valid && (
                        <div className="field-legend" aria-label="Thang màu">
                            <span>{format(range.min)}</span>
                            <div>
                                {Array.from({ length: 64 }, (_, i) => (
                                    <i
                                        key={i}
                                        style={{
                                            backgroundColor: color(
                                                range.min +
                                                    ((range.max - range.min) *
                                                        i) /
                                                        63,
                                                range.min,
                                                range.max,
                                            ),
                                        }}
                                    />
                                ))}
                            </div>
                            <span>
                                {format(range.max)} {fields[field][1]}
                            </span>
                        </div>
                    )}
                    <div className="field-timeline">
                        <button onClick={() => setPlaying((p) => !p)}>
                            {playing ? "Tạm dừng" : "Phát các frame"}
                        </button>
                        <label className="field">
                            <span>
                                {data.frames[frame].step} · frame gốc{" "}
                                {data.frames[frame].frame} ·{" "}
                                {(data.frames[frame].time_s * 1000).toFixed(3)}{" "}
                                ms
                            </span>
                            <input
                                aria-label="Thời điểm kết quả"
                                type="range"
                                min="0"
                                max={data.frames.length - 1}
                                value={frame}
                                onChange={(e) => {
                                    setPlaying(false);
                                    setFrame(Number(e.target.value));
                                }}
                            />
                        </label>
                        <span>
                            {frame + 1}/{data.frames.length}
                        </span>
                    </div>
                    <p className="hint">
                        U3 và |U| tô màu bằng trung bình giá trị nút của phần tử
                        hiển thị. S Mises / PEEQ lấy cực đại tại các điểm tích
                        phân và section point đã ghi, không làm trơn. Cực trị
                        dưới đây chỉ thuộc tập hiển thị, không thay cực trị toàn
                        ODB.
                    </p>
                    <details>
                        <summary>
                            5 phần tử hiển thị có giá trị lớn nhất · nguồn dữ
                            liệu
                        </summary>
                        <div className="table-scroll">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Instance</th>
                                        <th>Nhãn phần tử</th>
                                        <th>{fields[field][1]}</th>
                                        <th>Nhãn nút</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {extrema.map((row) => (
                                        <tr
                                            key={`${row.instance}-${row.label}`}
                                        >
                                            <td>{row.instance}</td>
                                            <td>{row.label}</td>
                                            <td>{format(row.value)}</td>
                                            <td>{row.nodes.join(", ")}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        <pre>
                            {JSON.stringify(
                                {
                                    source: data.source,
                                    solver_release: data.solver_release,
                                    sampling: data.sampling,
                                },
                                null,
                                2,
                            )}
                        </pre>
                    </details>
                </>
            )}
        </section>
    );
}
