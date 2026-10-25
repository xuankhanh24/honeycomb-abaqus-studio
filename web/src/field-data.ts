export type Vector = [number, number, number];
export type Mesh = {
    name: string;
    original_elements: number;
    node_labels: number[];
    coordinates: Vector[];
    elements: { label: number; type: string; nodes: number[] }[];
};
export type FieldFrame = {
    step: string;
    frame: number;
    time_s: number;
    instances: {
        u: (Vector | null)[];
        mises: (number | null)[];
        peeq: (number | null)[];
    }[];
};
export type FieldData = {
    kind: "honeycomb-field-view";
    schema_version: 1;
    source: Record<string, unknown>;
    solver_release: string;
    units: Record<string, string>;
    sampling: {
        display_elements: number;
        original_shell_elements: number;
        element_fields: string;
        method: string;
        research_data_replaced: false;
    };
    instances: Mesh[];
    frames: FieldFrame[];
};
export type Field = "u3" | "umag" | "mises" | "peeq";
const scalar = (v: unknown) =>
    v === null || (typeof v === "number" && Number.isFinite(v));
const vector = (v: unknown): v is Vector =>
    Array.isArray(v) &&
    v.length === 3 &&
    v.every((n) => typeof n === "number" && Number.isFinite(n));

/** Imported files are untrusted: bound loops and validate all connectivity first. */
export function validateFieldData(value: unknown): FieldData {
    const d = value as FieldData;
    if (
        !d ||
        d.kind !== "honeycomb-field-view" ||
        d.schema_version !== 1 ||
        !d.source ||
        !Array.isArray(d.instances) ||
        !d.instances.length ||
        d.instances.length > 64 ||
        !Array.isArray(d.frames) ||
        !d.frames.length ||
        d.frames.length > 25 ||
        d.units?.coordinates !== "mm" ||
        d.units?.u !== "mm" ||
        d.units?.mises !== "MPa" ||
        d.sampling?.research_data_replaced !== false
    )
        throw Error(
            "Tệp không đúng định dạng hiển thị Honeycomb hoặc thiếu đơn vị.",
        );
    let count = 0,
        nodes = 0;
    for (const m of d.instances) {
        if (
            !m ||
            typeof m.name !== "string" ||
            !Array.isArray(m.coordinates) ||
            !m.coordinates.length ||
            !Array.isArray(m.node_labels) ||
            m.node_labels.length !== m.coordinates.length ||
            !Array.isArray(m.elements)
        )
            throw Error("Lưới hiển thị thiếu nhãn hoặc tọa độ nút.");
        count += m.elements.length;
        nodes += m.coordinates.length;
        if (
            count > 6000 ||
            nodes > 24000 ||
            !m.coordinates.every(vector) ||
            !m.node_labels.every(Number.isSafeInteger) ||
            new Set(m.node_labels).size !== m.node_labels.length ||
            !m.elements.every(
                (e) =>
                    Number.isSafeInteger(e.label) &&
                    typeof e.type === "string" &&
                    Array.isArray(e.nodes) &&
                    e.nodes.length >= 3 &&
                    e.nodes.length <= 4 &&
                    e.nodes.every(
                        (i) =>
                            Number.isSafeInteger(i) &&
                            i >= 0 &&
                            i < m.coordinates.length,
                    ),
            )
        )
            throw Error(
                "Lưới vượt giới hạn hoặc chứa liên kết nút không hợp lệ.",
            );
    }
    if (d.sampling.display_elements !== count)
        throw Error("Số phần tử không khớp metadata.");
    for (const f of d.frames) {
        if (
            !Number.isFinite(f.time_s) ||
            !Number.isSafeInteger(f.frame) ||
            typeof f.step !== "string" ||
            !Array.isArray(f.instances) ||
            f.instances.length !== d.instances.length
        )
            throw Error("Frame thiếu thông tin thời gian hoặc instance.");
        f.instances.forEach((v, i) => {
            const m = d.instances[i];
            if (
                !v ||
                !Array.isArray(v.u) ||
                v.u.length !== m.coordinates.length ||
                !v.u.every((x) => x === null || vector(x)) ||
                !Array.isArray(v.mises) ||
                v.mises.length !== m.elements.length ||
                !v.mises.every(scalar) ||
                !Array.isArray(v.peeq) ||
                v.peeq.length !== m.elements.length ||
                !v.peeq.every(scalar)
            )
                throw Error(
                    "Trường dữ liệu không khớp lưới; không thể hiển thị.",
                );
        });
    }
    return d;
}

export function elementValue(
    mesh: Mesh,
    frame: FieldFrame["instances"][number],
    element: number,
    field: Field,
): number | null {
    if (field === "mises" || field === "peeq") return frame[field][element];
    const values = mesh.elements[element].nodes.map((i) => frame.u[i]);
    if (values.some((v) => v === null)) return null;
    return (
        values.reduce(
            (sum, v) => sum + (field === "u3" ? v![2] : Math.hypot(...v!)),
            0,
        ) / values.length
    );
}

export async function verifiedFieldData(
    bytes: ArrayBuffer,
    sha256?: string,
): Promise<FieldData> {
    if (bytes.byteLength > 16 * 1024 ** 2)
        throw Error("Tệp hiển thị vượt giới hạn 16 MiB.");
    if (sha256) {
        const actual = Array.from(
            new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
            (b) => b.toString(16).padStart(2, "0"),
        ).join("");
        if (actual !== sha256)
            throw Error(
                "SHA-256 không khớp. Dừng hiển thị để tránh dùng sai dữ liệu.",
            );
    }
    return validateFieldData(JSON.parse(new TextDecoder().decode(bytes)));
}
