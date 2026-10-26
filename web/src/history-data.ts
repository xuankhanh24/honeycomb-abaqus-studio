export type HistoryRow = Record<string, number | null>;

export async function decodeHistory(bytes: ArrayBuffer, expected: string): Promise<HistoryRow[]> {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const checksum = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
    if (checksum !== expected) throw new Error("Checksum history không khớp; chưa hiển thị dữ liệu.");
    const lines = new TextDecoder().decode(bytes).trim().split(/\r?\n/);
    const keys = lines.shift()!.split(",");
    if (!keys.includes("time_ms") ||
        !(keys.includes("contact_force_N") || keys.includes("contact_force_N_from_m_a")))
        throw new Error("History thiếu cột thời gian hoặc lực tiếp xúc.");
    return lines.map(line => {
        const values = line.split(",");
        if (values.length !== keys.length) throw new Error("History có hàng không đủ cột.");
        const row: HistoryRow = {};
        values.forEach((value, i) => {
            const number = value.trim() === "" ? null : Number(value);
            if (number !== null && !Number.isFinite(number)) throw new Error("History có giá trị không hợp lệ.");
            row[keys[i]] = number;
        });
        row.contact_force_N = row.contact_force_N ?? row.contact_force_N_from_m_a ?? null;
        if (row.time_ms === null || row.contact_force_N === null)
            throw new Error("History thiếu giá trị thời gian hoặc lực tiếp xúc.");
        return row;
    });
}
