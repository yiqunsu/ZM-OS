import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { SignJWT } from "jose";

const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL ?? "http://backend:8000";
const secretKey = new TextEncoder().encode(process.env.AUTH_SECRET);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Credentials({
      credentials: { email: {}, password: {} },
      authorize: async (credentials) => {
        const res = await fetch(`${BACKEND_INTERNAL_URL}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: credentials.email, password: credentials.password }),
        });
        if (!res.ok) return null;
        const user = await res.json();
        return { id: user.id, email: user.email, role: user.role };
      },
    }),
  ],
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  trustHost: true,
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.uid = user.id as string;
        token.role = (user as { role: string }).role;
      }
      // Separate, backend-verifiable token (HS256, shared AUTH_SECRET) — distinct from
      // NextAuth's own encrypted session cookie, which the FastAPI backend can't decode.
      token.backendToken = await new SignJWT({
        sub: token.uid as string,
        email: token.email as string,
        role: token.role as string,
      })
        .setProtectedHeader({ alg: "HS256" })
        .setIssuedAt()
        .setExpirationTime("8h")
        .sign(secretKey);
      return token;
    },
    async session({ session, token }) {
      session.backendToken = token.backendToken as string;
      session.user.id = token.uid as string;
      session.user.role = token.role as string;
      return session;
    },
  },
});
