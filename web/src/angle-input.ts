type Model = Record<string, any>;

/** Switching input representation preserves the current cell, not stale inactive values. */
export function updateAngleInput(model: Model, key: string, value: unknown): Model {
    const next = {...model, [key]: value};
    if (key !== "reentrant_geometry" || value === model.reentrant_geometry) return next;
    const height = model.reentrant_cell_height;
    if (typeof height !== "number" || !Number.isFinite(height) || height <= 0) return next;
    if (value === "angle" && typeof model.reentrant_indent === "number")
        next.reentrant_delta_deg = Math.atan2(model.reentrant_indent, height / 2) * 180 / Math.PI;
    if (value === "indent" && typeof model.reentrant_delta_deg === "number")
        next.reentrant_indent = height / 2 * Math.tan(model.reentrant_delta_deg * Math.PI / 180);
    return next;
}
