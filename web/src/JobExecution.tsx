import { useState } from "react";
import { ExternalLink, FolderOpen, RefreshCw, CheckCircle2, AlertCircle } from "lucide-react";
import { actionRunUrl } from "./action-links";
import { jobState, shardLabel, stateLabel } from "./job-state";

type Doc = Record<string, any>;
export default function JobExecution({job, parameters, owner, busy: externalBusy, openData, perform}: {
    job: Doc; parameters: Doc[]; owner: boolean; busy: boolean; openData: () => void;
    perform: (operation: "recover" | "collect") => Promise<void>;
}) {
    const [operation, setOperation] = useState<"recover" | "collect" | null>(null);
    const [filter, setFilter] = useState("all");
    const [pending, setPending] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const busy = externalBusy || pending;
    async function execute() {
        if (!operation) return;
        setPending(true); setError("");
        try {
            await perform(operation);
            setNotice(operation === "collect" ? "Đã gửi yêu cầu đóng gói. Mở lịch sử đóng gói để theo dõi lượt mới." : "Đã gửi yêu cầu chạy bù. Đợi GitHub nhận bài.");
            setOperation(null);
        } catch (e) { setError(String(e)); }
        finally { setPending(false); }
    }
    const state = jobState(job);
    const url = actionRunUrl(job.workflow_run_id);
    const shards: Doc[] = job.shards ?? [];
    const visible = shards.filter(s => filter === "all" || (filter === "errors"
        ? !["draft", "dispatching", "preflight", "running", "completed", "review"].includes(s.status)
            || (["completed", "review"].includes(s.status) && !s.archive_verified)
        : ["draft", "dispatching", "preflight", "running"].includes(s.status)));
    return <section className="execution-panel" aria-label="Tiến trình và thao tác job">
        <header className="execution-heading"><div>
            <h3>{job.parameter_title ?? job.name}</h3>
            <p>{job.name} · {stateLabel(job.status)} · {job.profile}</p>
        </div>{url && <a className="button" href={url} target="_blank" rel="noopener noreferrer">
            Mở Actions hiện tại <ExternalLink size={15}/></a>}</header>
        <p className="hint">Một đợt = một lần gửi khoảng tham số. Mỗi lượt = một job trên runner riêng.
            Các đợt cùng dùng quota GitHub; khi có slot trống, GitHub có thể nhận lượt đang chờ từ đợt khác.
            Tổng hợp dữ liệu sau khi toàn bộ lượt trong đợt kết thúc.</p>
        <ol className="execution-steps" aria-label="Các bước xử lý">
            <li data-done="true"><strong>1. Đầu vào đã lưu</strong><span>Thông số và cấu hình gốc</span></li>
            <li data-done={state.total > 0 && state.complete === state.total}><strong>2. Mô phỏng</strong>
                <span>{state.total ? `${state.complete}/${state.total} lượt đã lưu kết quả` : "Chưa bố trí runner"}</span></li>
            <li data-done={state.packed}><strong>3. Đóng gói dữ liệu</strong>
                <span>{state.packed ? "Workflow hoàn tất" : state.packagingFailed ? "Cần đóng gói lại"
                    : state.total && state.complete + state.failed === state.total
                        ? state.active ? "Workflow đang tổng hợp / đóng gói" : "Đợt đã kết thúc · xem dữ liệu và log"
                        : "Chờ các lượt kết thúc"}</span></li>
            <li><strong>4. Kiểm tra và tải</strong><button onClick={openData}>Mở thư mục dữ liệu <FolderOpen size={14}/></button></li>
        </ol>
        {!!state.total && <div className="execution-progress"><label htmlFor={`progress-${job.id}`}>
            {state.complete}/{state.total} lượt đã có kết quả lưu · {state.failed} lượt cần xử lý</label>
            <progress id={`progress-${job.id}`} value={state.complete} max={state.total}/>
            <p role="status">{state.waiting} chờ runner · {state.processing} đang xử lý · {state.complete} đã lưu · {state.failed} lỗi</p>
            {!job.queue_snapshot_available && state.active && <p className="hint">Số chờ dựa trên catalog; mở Actions để xem trạng thái runner mới nhất.</p>}
            <p className="hint">Tiến độ theo số lượt đã lưu. Tiến độ solver và tốc độ truyền xem trong log Actions.</p></div>}
        {state.packagingFailed && <p className="execution-warning"><AlertCircle size={18}/>
            Các lượt mô phỏng đã có kết quả. Workflow lỗi hoặc bị dừng ở phần sau; mở log để kiểm tra, rồi đóng gói lại nếu cần. Không cần chạy lại solver.</p>}
        {job.recovery_dispatch_pending && <p role="status">Đã gửi yêu cầu chạy bù. Đang chờ GitHub nhận bài; liên kết Actions hiện tại sẽ cập nhật khi workflow mới nhận job.</p>}
        {notice && <p role="status">{notice} <a href="https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/workflows/collect-training.yml" target="_blank" rel="noopener noreferrer">Lịch sử đóng gói <ExternalLink size={14}/></a></p>}
        {error && <p role="alert" className="execution-error">{error}</p>}
        <div className="actions">
            {!!state.failed && <button disabled={!owner || busy || !state.canRecover} onClick={() => setOperation("recover")}>
                <RefreshCw size={15}/> Chạy bù {state.failed} lượt lỗi</button>}
            {!!state.complete && <button disabled={!owner || busy || !state.canPackage} onClick={() => setOperation("collect")}>
                Đóng gói lại dữ liệu đã lưu</button>}
            {!owner && <span className="hint">Đăng nhập quản trị để chạy bù hoặc đóng gói lại.</span>}
        </div>
        {operation && <section className="execution-confirm" aria-label="Kiểm tra phạm vi thao tác">
            <h4>{operation === "recover" ? `Chạy bù ${state.failed} lượt cần xử lý` : "Đóng gói lại từ kết quả đã lưu"}</h4>
            <p>{operation === "recover"
                ? `${state.complete} lượt đã lưu được giữ nguyên. Các lượt lỗi chạy lại từ đầu, trong cùng job và thư mục; lịch sử cũ vẫn được giữ.`
                : "Tạo lại gói dữ liệu và bảng tổng hợp từ các bản lưu trên Releases. Không chạy solver. Nguồn chưa hoàn chỉnh sẽ được ghi rõ trong báo cáo."}</p>
            <div className="actions"><button className="primary" disabled={busy || !owner || !(operation === "recover" ? state.canRecover : state.canPackage)}
                onClick={() => void execute()}>{pending ? "Đang gửi…" : `Xác nhận ${operation === "recover" ? "chạy bù" : "đóng gói"}`}</button>
                <button disabled={busy} onClick={() => setOperation(null)}>Quay lại</button></div>
        </section>}
        {!!shards.length && <details open><summary>Từng lượt mô phỏng · tham số, trạng thái và lịch sử</summary>
            <div className="execution-filter"><label>Lọc lượt <select value={filter} onChange={e => setFilter(e.target.value)}>
                <option value="all">Tất cả ({shards.length})</option><option value="errors">Lượt lỗi</option><option value="active">Đang chạy / chờ</option>
            </select></label></div>
            <div className="execution-runs">{visible.map(s => <details key={s.id} className="execution-run">
                <summary><span>{s.display_name ?? `Lượt ${s.index + 1}`}</span>
                    <span className="execution-status">{s.status === "completed" ? <CheckCircle2 size={15}/> : null}{shardLabel(s)}</span></summary>
                <dl><dt>Lưu kết quả</dt><dd>{s.archive_verified ? "Bản lưu đã xác minh checksum" : "Chưa có bản lưu đã xác minh"}</dd>
                    <dt>Chất lượng số</dt><dd>{s.runs?.length ? `${s.runs.filter((r: Doc) => r.quality?.ml_eligible).length}/${s.runs.length} mẫu đạt tiêu chí huấn luyện` : "Chưa có đánh giá"}</dd></dl>
                {s.error && <p className="execution-error">{s.error}</p>}
                <div className="actions">{Number.isSafeInteger(s.action_job_id) && s.action_job_id > 0 && url
                    ? <a href={`${url}/job/${s.action_job_id}`} target="_blank" rel="noopener noreferrer">Mở log job của lượt <ExternalLink size={14}/></a>
                    : actionRunUrl(s.workflow_run_id) && <a href={actionRunUrl(s.workflow_run_id)!} target="_blank" rel="noopener noreferrer">Mở log workflow của lượt <ExternalLink size={14}/></a>}
                    {s.release_url && <a href={s.release_url} target="_blank" rel="noopener noreferrer">Bản lưu gốc <ExternalLink size={14}/></a>}</div>
                {!!s.previous_attempts?.length && <details><summary>Lịch sử {s.previous_attempts.length} lần thử trước</summary>
                    {s.previous_attempts.map((a: Doc, i: number) => <p key={i}>Lần {i + 1}: {stateLabel(a.status)} · {actionRunUrl(a.workflow_run_id) &&
                        <a href={actionRunUrl(a.workflow_run_id)!} target="_blank" rel="noopener noreferrer">Mở Actions #{a.workflow_run_id}</a>}{a.release_url && <> · <a href={a.release_url} target="_blank" rel="noopener noreferrer">Dữ liệu cũ</a></>}</p>)}
                </details>}
            </details>)}{!visible.length && <p>Không có lượt thuộc bộ lọc này.</p>}</div>
        </details>}
        <details><summary>Đầu vào áp dụng · tên tham số và đơn vị</summary>
        {!!job.spec?.axes?.length && <section><h4>Tham số thay đổi theo từng lượt</h4><ul>{job.spec.axes.map((axis: Doc, i: number) => {
            const parameter = parameters.find(p => p.key === axis.parameter);
            return <li key={i}>{parameter?.title ?? axis.parameter}: {axis.values ? axis.values.join(", ") : `${axis.start} → ${axis.stop}, bước ${axis.step}`}{parameter?.unit ? ` (${parameter.unit})` : ""}</li>;
        })}</ul></section>}
        {!!job.spec?.designs?.length && <details><summary>Bảng thiết kế ({job.spec.designs.length} dòng)</summary><pre>{JSON.stringify(job.spec.designs, null, 2)}</pre></details>}
        <p className="hint">Cấu hình nền bên dưới được kết hợp với tham số thay đổi; giá trị từng lượt hiển thị ở danh sách phía trên.</p>
        <dl className="execution-inputs">
            {Object.entries(job.spec?.model ?? {}).map(([key, value]) => {
                const parameter = parameters.find(p => p.key === key);
                return <div key={key}><dt>{parameter?.title ?? key}{parameter?.unit ? ` (${parameter.unit})` : ""}</dt>
                    <dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>;
            })}
        </dl></details>
    </section>;
}
