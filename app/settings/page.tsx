"use client";

import { useEffect, useState } from "react";
import SiteHeader from "@/app/components/site-header";
import {useNotice} from '@/app/components/use-notice';

type Connection = { enabled: boolean; state: string; last_checked: string | null; browser_available: boolean; legacy_cookie_override: boolean; profile_path: string };
const labels: Record<string, string> = { NOT_CONNECTED: "Chưa kết nối", AWAITING_SIGN_IN: "Đang chờ đăng nhập", CLOSE_LOGIN_WINDOW:"Cần đóng cửa sổ profile YouTube trước", SESSION_SAVED: "Đã lưu phiên đăng nhập", SIGN_IN_REQUIRED: "Cần đăng nhập lại" };

export default function Settings() {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useNotice();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let mounted = true;
    fetch("/api/settings/youtube", { cache: "no-store" }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      return data as Connection;
    }).then(data => {
      if (mounted) setConnection(data);
    }).catch(error => {
      if (!mounted) return;
      setFailed(true);
      setMessage(error instanceof Error ? error.message : "Không tải được kết nối YouTube.");
    });
    return () => { mounted = false; };
  }, [setMessage]);

  async function act(action: "open" | "check" | "disconnect") {
    setBusy(true); setMessage(""); setFailed(false);
    try {
      const response = await fetch("/api/settings/youtube", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
      const data = await response.json();
      if (typeof data.enabled === "boolean") setConnection(data);
      if (!response.ok) throw new Error(data.error);
      setMessage(action === "open" ? "Cửa sổ YouTube bình thường đã mở. Đăng nhập thủ công, đóng cửa sổ đó rồi bấm Kiểm tra kết nối." : action === "check" ? "Đã tìm thấy phiên đăng nhập. Những lần tải tiếp theo sẽ tự lấy cookie mới từ profile này." : "Đã ngừng dùng profile. Phiên đã lưu vẫn được giữ trên máy để kết nối lại.");
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : "Không cập nhật được kết nối.");
    } finally { setBusy(false); }
  }

  return <main className="studio"><SiteHeader /><section className="hero">
    <span className="eyebrow">SETTINGS</span><h1>Kết nối YouTube</h1>
    <p>Đăng nhập một lần trong profile riêng của Audio Studio. App tự lấy cookie mới cho mỗi lần tải; phiên đăng nhập được giữ khi cập nhật app.</p>
    <section className="youtube-connection" aria-label="YouTube connection">
      <h2>{connection ? labels[connection.state] || "Chưa kết nối" : "Đang tải…"}</h2>
      {connection && <>
        {!connection.browser_available && <p>Cài Microsoft Edge hoặc Google Chrome để dùng kết nối này.</p>}
        {connection.legacy_cookie_override && <p>App đang dùng file cookie đã cấu hình. Khi kết nối profile, app sẽ ưu tiên phiên trong profile.</p>}
        <ol><li>Đóng cửa sổ profile YouTube cũ đang báo lỗi, nếu có. Không cần xóa profile.</li><li>Bấm Kết nối YouTube để mở Edge/Chrome bình thường, không điều khiển từ xa.</li><li>Tự đăng nhập YouTube và xử lý xác minh Google nếu có.</li><li>Đóng cửa sổ profile YouTube riêng đó, rồi quay lại đây bấm Kiểm tra kết nối.</li></ol>
        {connection.state==='CLOSE_LOGIN_WINDOW'&&<p role="status">App không điều khiển cửa sổ đăng nhập. Đóng cửa sổ profile riêng trước khi mở lại hoặc kiểm tra phiên đã lưu.</p>}
        <div className="youtube-actions">
          <button className="action-button" disabled={busy || !connection.browser_available} onClick={() => void act("open")}>{connection.enabled ? "Đăng nhập lại / Mở YouTube" : "Kết nối YouTube"}</button>
          <button className="action-button" disabled={busy || !connection.enabled} onClick={() => void act("check")}>Kiểm tra kết nối</button>
          <button className="text-button" disabled={busy || !connection.enabled} onClick={() => void act("disconnect")}>Ngừng sử dụng profile</button>
        </div>
        {connection.last_checked && <p>Lần kiểm tra gần nhất: {new Date(connection.last_checked).toLocaleString("vi-VN")}</p>}
        <details><summary>Nơi lưu profile trên máy</summary><code>{connection.profile_path}</code></details>
      </>}
      {busy && <p role="status">Đang xử lý kết nối…</p>}
      {message && <p className={failed ? "alert" : "connection-message"} role={failed ? "alert" : "status"}>{message}</p>}
    </section>
    <p>App chỉ kiểm tra phiên đã lưu; quyền truy cập từng video được YouTube xác nhận khi tải. Nếu YouTube hết hạn phiên hoặc yêu cầu xác minh, hãy dùng Đăng nhập lại. Cookie không được đưa vào bộ cài hay gửi cho Admin.</p>
    <p>Nếu Google vẫn báo trình duyệt không an toàn, hãy cập nhật Edge/Chrome và thử đăng nhập thủ công trong trình duyệt đó. App không tắt bảo mật, giả mạo trình duyệt hay tự vượt CAPTCHA/2FA.</p>
  </section></main>;
}
