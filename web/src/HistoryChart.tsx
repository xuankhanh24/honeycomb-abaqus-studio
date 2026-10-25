import {
    ResponsiveContainer,
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
} from "recharts";

export default function HistoryChart({
    curve,
}: {
    curve: Record<string, number>[];
}) {
    return (
        <ResponsiveContainer width="100%" height={320}>
            <LineChart data={curve}>
                <CartesianGrid stroke="#e2e7ed" />
                <XAxis
                    dataKey="time_ms"
                    type="number"
                    domain={[0, 6]}
                    tickFormatter={(v) => Number(v).toFixed(1)}
                    label={{
                        value: "Thời gian (ms)",
                        position: "insideBottom",
                        offset: -7,
                    }}
                />
                <YAxis
                    width={65}
                    label={{
                        value: "Lực (N)",
                        angle: -90,
                        position: "insideLeft",
                    }}
                />
                <Tooltip />
                <Legend verticalAlign="top" />
                <Line
                    dataKey="contact_force_N_from_m_a"
                    name="Lực tiếp xúc m·a"
                    stroke="#1769aa"
                    dot={false}
                    isAnimationActive={false}
                />
            </LineChart>
        </ResponsiveContainer>
    );
}
