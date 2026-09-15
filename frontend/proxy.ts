import { NextResponse } from "next/server";
import { auth } from "@/auth";

export default auth((req) => {
  // The Agent proxy returns a JSON 401, including for an expired SSE subscription.
  if (req.nextUrl.pathname.startsWith("/api/agent/v2/")) return NextResponse.next();
  const isLoggedIn = Boolean(req.auth);
  const isLoginPage = req.nextUrl.pathname.startsWith("/login");

  if (!isLoggedIn && !isLoginPage) {
    return NextResponse.redirect(new URL("/login", req.nextUrl));
  }
  if (isLoggedIn && isLoginPage) {
    return NextResponse.redirect(new URL("/", req.nextUrl));
  }
  if (req.nextUrl.pathname.startsWith("/settings") && req.auth?.user.role !== "OWNER") {
    return NextResponse.redirect(new URL("/", req.nextUrl));
  }
});

export const config = {
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico|icons|manifest.json).*)"],
};
