import { Component } from "react";
import type { ReactNode } from "react";

/** A stale deployment chunk must never take down the management page. */
export default class ResultBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
    state = { failed: false };

    static getDerivedStateFromError() {
        return { failed: true };
    }

    render() {
        if (this.state.failed) return <section role="alert" className="error">
            <p>Chưa tải được bộ xem kết quả. Có thể trang đang dùng phiên bản cũ hoặc kết nối bị gián đoạn. Bài chạy và dữ liệu đã lưu vẫn được giữ.</p>
            <p>Nếu đang sửa thông số, hãy tải input trước khi tải lại trang.</p>
            <button onClick={() => location.reload()}>Tải lại trang để mở kết quả</button>
        </section>;
        return this.props.children;
    }
}
