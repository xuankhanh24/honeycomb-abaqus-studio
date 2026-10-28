type Doc = Record<string, any>;
export const statusLabels: Record<string, string> = {
    draft: "Chưa gửi chạy", dispatching: "Đã gửi, chờ GitHub", preflight: "Kiểm tra môi trường",
    running: "Đang thực hiện", completed: "Hoàn tất", review: "Cần xem chất lượng",
    failed: "Có lỗi", archive_failed: "Lỗi lưu dữ liệu", cancelled: "Đã dừng", timed_out: "Hết thời gian",
    blocked_environment: "Lỗi môi trường", blocked_license: "Chưa cấp được license",
    blocked_platform_policy: "Bị chặn bởi cấu hình nền tảng",
};
export const stateLabel = (value: string) => statusLabels[value] ?? value;
export function jobState(job: Doc) {
    const shards: Doc[] = job.shards ?? [];
    const complete = shards.filter(s => ["completed", "review"].includes(s.status) && s.archive_verified).length;
    const failed = shards.filter(s => !["draft", "dispatching", "running", "preflight", "completed", "review"].includes(s.status)
        || (["completed", "review"].includes(s.status) && !s.archive_verified)).length;
    const active = job.workflow && job.workflow.status !== "completed";
    const packed = job.workflow?.conclusion === "success";
    const packagingFailed = shards.length > 0 && complete === shards.length && job.workflow?.status === "completed" && !packed;
    return {total: shards.length, complete, failed, active, packed, packagingFailed,
        canRecover: !!failed && !active && !job.cancel_requested && !job.recovery_dispatch_pending,
        canPackage: !!complete && !active && !job.recovery_dispatch_pending};
}
