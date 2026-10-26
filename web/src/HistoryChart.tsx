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
    curve: Record<string, number | null>[];
}) {
    return (
        <ResponsiveContainer width="100%" height={320}>
            <LineChart data={curve}>
                <CartesianGrid stroke="#e2e7ed" />
                <XAxis
                    dataKey="time_ms"
                    type="number"
                    domain={["dataMin", "dataMax"]}
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
                    dataKey="contact_force_N"
                    name="Lực tiếp xúc"
                    stroke="#1769aa"
                    dot={false}
                    isAnimationActive={false}
                />
            </LineChart>
        </ResponsiveContainer>
    );
}
