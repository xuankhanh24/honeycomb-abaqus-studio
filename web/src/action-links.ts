export function actionRunUrl(value: unknown): string | null {
    const id = typeof value === "number" ? value : Number(value);
    return (typeof value === "number" || typeof value === "string") && Number.isSafeInteger(id) && id > 0
        ? `https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/${id}`
        : null;
}
