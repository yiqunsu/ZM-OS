import { redirect } from "next/navigation";

// AI 助手已成为首页，旧的 /chat 路由重定向到根路径
export default function ChatPage() {
  redirect("/");
}
